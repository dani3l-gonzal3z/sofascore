"""Comandos de los agentes analistas y de la clasificación.

Tres verbos y ya: ver qué agentes hay, poner a uno a analizar un partido, y
mirar quién va acertando. El orden no es casual — la tabla es el punto de todo
esto, y sin ella un agente es una opinión más bien escrita.
"""

from __future__ import annotations

import argparse
import json

from . import comun
from .comun import depuracion, envolver, imprimir


def _almacen(args: argparse.Namespace):
    from ..almacen import Almacen

    return Almacen(getattr(args, "db", None) or "datos/cancha.db")


def cmd_agentes(args: argparse.Namespace) -> int:
    """Los agentes que hay, con su huella y lo que tengan mal."""
    from ..agentes import cargar, guardar, huella, ruta, validar

    donde = ruta(getattr(args, "agentes", None))
    agentes = cargar(donde)

    if args.borrar:
        if args.borrar not in agentes:
            imprimir(f"No tengo ningún agente llamado «{args.borrar}».")
            return 1
        del agentes[args.borrar]
        guardar(agentes, donde)
        imprimir(f"Borrado «{args.borrar}». Lo que ya predijo sigue en el registro: "
                 "un historial que se puede reescribir no vale nada.")
        return 0

    if args.crear:
        if args.crear in agentes:
            imprimir(f"Ya hay un agente «{args.crear}». Edítalo en {donde} o en la "
                     "pestaña Agentes.")
            return 1
        problemas = validar(args.crear, {"instrucciones": "(escribe aquí tu estilo)"})
        # El único problema aceptable de un esqueleto es que le falten las
        # instrucciones: eso es justo lo que va a escribir el usuario.
        graves = [p for p in problemas if "Sin instrucciones" not in p]
        if graves:
            for problema in graves:
                for linea in envolver(f"✗ {problema}", 74):
                    imprimir(linea)
            return 1
        agentes[args.crear] = _esqueleto(args.crear)
        guardar(agentes, donde)
        imprimir(f"Escrito el esqueleto de «{args.crear}» en {donde}.")
        imprimir("Ábrelo y escríbele las instrucciones: es lo único que lo hace un "
                 "agente y no el analista de siempre con otro nombre.")
        return 0

    if not agentes:
        imprimir(f"No hay agentes legibles en {donde}.")
        return 1
    imprimir(f"{len(agentes)} agentes ({donde}):\n")
    for clave, agente in sorted(agentes.items()):
        marca = " " if agente.activo else "·"
        cuantas = (f"{len(agente.herramientas)} herramientas"
                   if agente.herramientas else "todas las herramientas")
        imprimir(f"{marca} {clave}  —  {agente.nombre}   [{huella(agente)}]")
        imprimir(f"      {agente.modelo or 'el modelo de los ajustes'} · "
                 f"{agente.vueltas} vueltas · crudo: {agente.crudo} · {cuantas}")
        for linea in envolver(agente.instrucciones, 70):
            imprimir(f"      {linea}")
        for problema in validar(clave, agente.as_dict()):
            imprimir(f"      ✗ {problema}")
        imprimir("")
    imprimir("Ponlo a analizar con:  cancha agente <nombre> \"Girona vs Osasuna\"")
    imprimir("Mira quién acierta con: cancha clasificacion")
    return 0


def _esqueleto(clave: str) -> dict:
    """Un agente nuevo: todo lo demás tiene valor por defecto menos el estilo."""
    from ..agentes import Agente

    return Agente(clave=clave, nombre=clave.replace("-", " ").capitalize(),
                  instrucciones="").as_dict()


def cmd_agente(args: argparse.Namespace) -> int:
    """Pone a un agente a analizar un partido, y apunta lo que diga."""
    from .. import ajustes as modulo_ajustes
    from ..agentes import cargar, correr, ruta
    from ..analista import OllamaNoDisponible, texto_de_paso

    agentes = cargar(ruta(getattr(args, "agentes", None)))
    agente = agentes.get(args.nombre)
    if agente is None:
        imprimir(f"No tengo ningún agente llamado «{args.nombre}».")
        imprimir("Los que hay: " + (", ".join(sorted(agentes)) or "ninguno"))
        return 1

    guardados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
    valor = modulo_ajustes.valor
    clave = args.api_key or guardados.get("ollama_api_key") or ""
    cliente = comun.construir_cliente(args)
    almacen = _almacen(argparse.Namespace(
        db=valor(args, "db", guardados["memoria"])))
    try:
        if args.solo_expediente:
            from ..expediente import a_texto, expediente

            datos = expediente(almacen, args.consulta, cliente=cliente,
                               crudo=agente.crudo)
            if not datos.get("disponible"):
                imprimir(datos.get("nota", "No hay expediente."))
                return 1
            imprimir(a_texto(datos))
            imprimir("")
            imprimir(f"({datos['tamano']['caracteres']} caracteres, "
                     f"~{datos['tamano']['tokens_aprox']} tokens) · "
                     f"{len(agente.herramientas) or 'todas las'} herramientas "
                     "a su alcance")
            return 0

        imprimir(f"{agente.nombre} ({args.nombre}) mirando «{args.consulta}»")
        if clave:
            imprimir("⚠ Esto sale de tu ordenador: el expediente viaja a Ollama.")
        imprimir("")
        try:
            salida = correr(almacen, cliente, agente, args.consulta,
                            modelo_por_defecto=valor(args, "modelo",
                                                     guardados["modelo"]),
                            api_key=clave,
                            url=args.url or ("" if clave else guardados["ollama"]),
                            al_paso=lambda paso: imprimir(texto_de_paso(paso)))
        except OllamaNoDisponible as exc:
            imprimir(f"✗ {exc}")
            return 2
        if not salida.get("disponible"):
            imprimir(salida.get("nota", "No he podido."))
            return 1

        imprimir("")
        for linea in (salida["respuesta"] or "").splitlines():
            imprimir(linea)
        imprimir("")
        if salida["sin_numeros"]:
            for linea in envolver(
                    "⚠ No ha terminado dando probabilidades, así que su análisis se "
                    "guarda pero no puntúa: no se puede comparar con nadie. Que esto "
                    "le pase a menudo a un agente es, en sí, información sobre él.",
                    74):
                imprimir(linea)
        else:
            imprimir(f"{salida['apuntadas']} predicciones apuntadas a nombre de "
                     f"«{args.nombre}». Cuando se juegue, cancha resultados "
                     "--resolver las puntúa.")
            if salida.get("reparado"):
                imprimir("(Se le tuvo que pedir el bloque de números una segunda vez.)")
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()


def cmd_clasificacion(args: argparse.Namespace) -> int:
    """Quién predice mejor: los agentes, el cálculo y el mercado, juntos."""
    from ..registro import comparar, resolver, tabla, texto_tabla

    almacen = _almacen(args)
    try:
        if args.resolver:
            hechas = resolver(almacen)
            imprimir(f"{hechas['resueltas']} resueltas, "
                     f"{hechas['sin_jugar_todavia']} sin jugar todavía.\n")
        if args.comparar:
            uno, otro = args.comparar
            datos = comparar(almacen, uno, otro)
            if args.json:
                imprimir(json.dumps(datos, ensure_ascii=False, indent=2))
                return 0
            imprimir(f"{uno} contra {otro}, sobre las predicciones que han hecho los "
                     f"dos ({datos.get('casos', 0)} casos en común):")
            imprimir("")
            for linea in envolver(datos.get("lectura", ""), 74):
                imprimir(linea)
            return 0

        datos = tabla(almacen, desde=args.desde, hasta=args.hasta)
        if args.json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2))
            return 0
        for linea in texto_tabla(datos):
            imprimir(linea)
        imprimir("")
        for linea in envolver(datos["como_leerlo"], 74):
            imprimir(linea)
        return 0
    finally:
        almacen.close()


def registrar(sub, comun_p, informe, listado) -> None:
    """Añade los comandos de los agentes."""
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--db", help="Fichero de la memoria.")
    base.add_argument("--agentes", help="Fichero de agentes (por defecto: "
                                        "datos/agentes.json).")

    p_agentes = sub.add_parser(
        "agentes", parents=[comun_p, base],
        help="Los agentes analistas que tienes, cada uno con su estilo.",
        description="Un agente es el analista con nombre y carácter: sus "
                    "instrucciones, su modelo, su presupuesto de vueltas y —lo que "
                    "de verdad lo hace distinto— a qué datos llega. Y está obligado "
                    "a terminar dando probabilidades, que es lo que permite ponerlos "
                    "en una tabla con el cálculo y el mercado y ver quién acierta.",
    )
    p_agentes.add_argument("--crear", metavar="NOMBRE",
                           help="Escribe el esqueleto de un agente nuevo.")
    p_agentes.add_argument("--borrar", metavar="NOMBRE",
                           help="Quita un agente (lo que ya predijo se queda).")
    p_agentes.set_defaults(func=cmd_agentes)

    p_agente = sub.add_parser(
        "agente", parents=[comun_p, base],
        help="Pon a un agente a analizar un partido.",
        description="Le monta el expediente con el detalle que lleve configurado, "
                    "le deja pedir por su cuenta los datos que vea necesarios, y le "
                    "exige acabar con sus probabilidades. El análisis se guarda con "
                    "el partido y las probabilidades entran en el registro a su "
                    "nombre. Si no da números, se guarda pero no puntúa.",
    )
    p_agente.add_argument("nombre", help="El agente, por su nombre corto.")
    p_agente.add_argument("consulta", help="El partido: «Girona vs Osasuna».")
    p_agente.add_argument("--modelo", help="Modelo (si no, el del agente o el de los ajustes).")
    p_agente.add_argument("--url", help="Ollama (por defecto el de los ajustes).")
    p_agente.add_argument("--api-key", default="",
                          help="Clave de la nube de Ollama. Ojo: esto se paga.")
    p_agente.add_argument("--solo-expediente", action="store_true",
                          help="Enseña lo que recibiría, sin gastar una llamada.")
    p_agente.set_defaults(func=cmd_agente)

    p_clas = sub.add_parser(
        "clasificacion", parents=[comun_p, base],
        help="Quién acierta más: los agentes, el cálculo y el mercado.",
        description="Ordena por la ventaja sobre el mercado y no por el Brier a "
                    "secas, porque un Brier bueno se consigue prediciendo solo "
                    "partidos fáciles. Enseña además a qué distancia del precio se "
                    "mueve cada uno —quien no se separa está copiándolo— y con "
                    "cuánta antelación predice, que es la otra forma de parecer "
                    "listo. Con menos casos que el mínimo, nadie tiene puesto.",
    )
    p_clas.add_argument("--desde", help="Solo partidos desde esta fecha.")
    p_clas.add_argument("--hasta", help="Solo partidos hasta esta fecha.")
    p_clas.add_argument("--resolver", action="store_true",
                        help="Puntuar antes las que ya tengan resultado.")
    p_clas.add_argument("--comparar", nargs=2, metavar=("UNO", "OTRO"),
                        help="Dos autores, cara a cara, solo donde han opinado los dos.")
    p_clas.add_argument("--json", action="store_true", help="Volcar el JSON.")
    p_clas.set_defaults(func=cmd_clasificacion)
