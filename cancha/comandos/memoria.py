"""Comandos de la memoria: llenarla y preguntarle.

El barrido trae partidos y los guarda; el resto son preguntas a lo guardado.
Sin barrido antes, todos avisan de que no hay con qué trabajar en vez de
devolver un informe vacío.
"""

from __future__ import annotations

import argparse
import json

from ..almacen import Almacen
from ..barrido import GRUPOS, agenda, barrer, ligas_de
from ..entities import find_entity
from ..perfiles import (
    estilo_de_equipo,
    evolucion_de_estilo,
    forma_de_jugador,
    perfil_de_arbitro,
)
from ..previa import previa, texto
from ..resolve import normalizar
from ..sistemas import (
    desglose_por_favorito,
    duelo,
    jugador_contra_sistema,
    lo_relevante,
    sistema_habitual,
)
from . import comun
from .comun import depuracion, envolver, imprimir

RUTA_POR_DEFECTO = "datos/cancha.db"


def _almacen(args: argparse.Namespace) -> Almacen:
    return Almacen(getattr(args, "db", None) or RUTA_POR_DEFECTO)


def _equipo_id(almacen: Almacen, consulta: str, cliente=None) -> tuple[int | None, str]:
    """El id de un equipo, buscándolo primero en lo que ya está guardado.

    Preguntar por «Real Madrid» no debería costar una petición si ese equipo
    lleva semanas en la base.
    """
    if str(consulta).isdigit():
        return int(consulta), str(consulta)
    buscado = normalizar(consulta)
    for fila in almacen.consulta(
        "SELECT DISTINCT local_id AS id, local AS nombre FROM partidos "
        "UNION SELECT DISTINCT visitante_id, visitante FROM partidos"
    ):
        if fila["nombre"] and buscado in normalizar(fila["nombre"]):
            return fila["id"], fila["nombre"]
    if cliente is not None:
        ficha = find_entity(cliente, consulta, "team")
        return int(ficha["id"]), ficha.get("name") or consulta
    return None, consulta


def _jugador_id(almacen: Almacen, consulta: str, cliente=None) -> tuple[int | None, str]:
    if str(consulta).isdigit():
        return int(consulta), str(consulta)
    buscado = normalizar(consulta)
    for fila in almacen.consulta(
        "SELECT DISTINCT jugador_id AS id, jugador AS nombre FROM actuaciones"
    ):
        if fila["nombre"] and buscado in normalizar(fila["nombre"]):
            return fila["id"], fila["nombre"]
    if cliente is not None:
        ficha = find_entity(cliente, consulta, "player")
        return int(ficha["id"]), ficha.get("name") or consulta
    return None, consulta


# ------------------------------------------------------------------- comandos

def cmd_barrido(args: argparse.Namespace) -> int:
    """Trae los partidos del día y el historial de quien juega."""
    cliente = comun.construir_cliente(args)
    almacen = _almacen(args)
    try:
        grupos = args.grupos.split(",") if args.grupos else None
        ligas = ligas_de(grupos)
        imprimir(f"Barriendo {len(ligas)} competiciones hacia {args.db or RUTA_POR_DEFECTO}")
        if args.max:
            imprimir(f"Con tope de {args.max} peticiones.")
        imprimir("")
        resumen = barrer(
            cliente, almacen, fecha=args.date, grupos=grupos, ultimos=args.ultimos,
            maximo_peticiones=args.max, avisar=imprimir if not args.quiet else None,
        )
        imprimir("")
        imprimir(f"Partidos del día: {resumen['partidos_del_dia']} · "
                 f"equipos: {resumen['equipos']}")
        imprimir(f"Guardados: {resumen['guardados']} · ya estaban: {resumen['ya_estaban']} · "
                 f"fallos: {resumen['fallos']} · peticiones: {resumen['peticiones']}")
        for fallo in resumen.get("fallos_detalle") or []:
            imprimir(f"    {fallo}")
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        cliente.close()


def cmd_memoria(args: argparse.Namespace) -> int:
    """Qué hay guardado."""
    almacen = _almacen(args)
    try:
        datos = almacen.resumen()
        if not datos["partidos"]:
            imprimir(f"La memoria de {datos['ruta']} está vacía.")
            imprimir("Llénala con: cancha barrido")
            return 0
        imprimir(f"{datos['ruta']}")
        imprimir(f"  {datos['partidos']} partidos "
                 f"({datos['con_estadisticas']} con estadísticas), "
                 f"del {datos['desde']} al {datos['hasta']}")
        imprimir(f"  {datos['actuaciones']} actuaciones de jugadores · "
                 f"{datos['tiros']} tiros")
        imprimir(f"  último barrido: {datos['ultimo_barrido']}\n")
        for liga, cuantos in list(datos["ligas"].items())[:15]:
            imprimir(f"    {cuantos:>4}  {liga}")
        return 0
    finally:
        almacen.close()


def cmd_agenda(args: argparse.Namespace) -> int:
    """Qué se juega hoy en las competiciones elegidas."""
    cliente = comun.construir_cliente(args)
    try:
        grupos = args.grupos.split(",") if args.grupos else None
        partidos = agenda(cliente, args.date, grupos)
        if not partidos:
            imprimir("No hay partidos ese día en esas competiciones.")
            return 0
        por_liga: dict[str, list] = {}
        for evento in partidos:
            por_liga.setdefault(evento.tournament or "?", []).append(evento)
        for liga in sorted(por_liga):
            imprimir(f"\n{liga}")
            for evento in por_liga[liga]:
                hora = evento.kickoff.strftime("%H:%M") if evento.kickoff else "  ?  "
                imprimir(f"  {hora}  {evento.home} - {evento.away}   id={evento.id}")
        imprimir(f"\n{len(partidos)} partidos en {len(por_liga)} competiciones.")
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_estilo(args: argparse.Namespace) -> int:
    """Cómo juega un equipo, comparado con su liga."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args) if args.buscar else None
    try:
        equipo_id, nombre = _equipo_id(almacen, args.consulta, cliente)
        if equipo_id is None:
            imprimir(f"No encuentro '{args.consulta}' en la memoria.")
            imprimir("Prueba con --buscar para preguntárselo a la API, o haz un barrido.")
            return 1
        if args.evolucion:
            return _imprimir_evolucion(
                evolucion_de_estilo(almacen, equipo_id, ultimos=args.ultimos), args)
        datos = estilo_de_equipo(almacen, equipo_id, ultimos=args.ultimos)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            return 1
        r = datos["resultados"]
        imprimir(f"{datos['equipo']} — {datos['liga']}")
        imprimir(f"  {datos['partidos_mirados']} últimos partidos ({datos['desde']} → "
                 f"{datos['hasta']}): {r['racha']}, {r['goles_favor']}-{r['goles_contra']}\n")
        if datos["lo_que_le_distingue"]:
            imprimir("  Lo que le distingue de su liga")
            for rasgo in datos["lo_que_le_distingue"]:
                imprimir(f"    · {rasgo['rasgo']:<34} {rasgo['cuanto']}")
        else:
            imprimir("  No se sale de la media de su liga en nada llamativo.")
        concede = datos["concede"]
        imprimir(f"\n  Concede por partido: {concede['xg']} xG · "
                 f"{concede['tiros']} tiros · {concede['ocasiones_claras']} ocasiones claras")
        if datos.get("aviso"):
            for linea in envolver(datos["aviso"], 74):
                imprimir(f"  {linea}")
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def _imprimir_evolucion(datos: dict, args: argparse.Namespace) -> int:
    """Cómo está jugando ahora frente a cómo jugaba antes."""
    if args.stdout_json:
        imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        return 0
    if not datos["disponible"]:
        imprimir(datos["nota"])
        return 1
    ahora, antes = datos["ahora"], datos["antes"]
    imprimir(f"{datos['equipo']} — ¿ha cambiado?\n")
    imprimir(f"  Ahora  ({ahora['desde']} → {ahora['hasta']}): {ahora['partidos']} partidos, "
             f"{ahora['racha']}, {ahora['puntos_por_partido']} puntos/partido"
             + (f", dibujo {ahora['formacion']}" if ahora.get("formacion") else ""))
    imprimir(f"  Antes  ({antes['desde']} → {antes['hasta']}): {antes['partidos']} partidos, "
             f"{antes['racha']}, {antes['puntos_por_partido']} puntos/partido"
             + (f", dibujo {antes['formacion']}" if antes.get("formacion") else ""))
    imprimir("")
    if datos["lo_que_ha_cambiado"]:
        imprimir("  Lo que ha cambiado")
        for cambio in datos["lo_que_ha_cambiado"]:
            imprimir(f"    · {cambio['lectura']:<34} {cambio['cambio']:>6}  "
                     f"({cambio['antes']} → {cambio['ahora']})")
    else:
        imprimir("  Juega igual que antes en todo lo que se mide aquí.")
    if datos.get("cambio_de_dibujo"):
        imprimir(f"\n  Ha cambiado de dibujo: {antes['formacion']} → {ahora['formacion']}")
    concede = datos.get("concede") or {}
    if concede:
        imprimir("\n  Concede: " + " · ".join(
            f"{k} {v['antes']} → {v['ahora']}" for k, v in concede.items()))
    imprimir("")
    for linea in envolver(datos["como_leerlo"], 74):
        imprimir(f"  {linea}")
    return 0


def cmd_forma(args: argparse.Namespace) -> int:
    """Cómo está un jugador y qué rachas lleva."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args) if args.buscar else None
    try:
        jugador_id, nombre = _jugador_id(almacen, args.consulta, cliente)
        if jugador_id is None:
            imprimir(f"No encuentro '{args.consulta}' en la memoria.")
            imprimir("Prueba con --buscar, o haz un barrido de su equipo.")
            return 1
        datos = forma_de_jugador(almacen, jugador_id, ultimas=args.ultimos)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            return 1
        imprimir(f"{datos['jugador']}")
        imprimir(f"  {datos['partidos_mirados']} partidos · "
                 f"{datos['titularidades']} de titular · "
                 f"{datos['minutos_totales']} minutos · nota media {datos['rating_medio']}\n")
        if datos["rachas"]:
            imprimir("  Rachas")
            for racha in datos["rachas"]:
                imprimir(f"    · {racha['racha']} (desde el {racha['desde']})")
            imprimir("")
        imprimir("  Por partido")
        for metrica, valor in datos["por_partido"].items():
            imprimir(f"    {metrica:<18} {valor}")
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def cmd_arbitro(args: argparse.Namespace) -> int:
    """Cómo pita alguien, según los partidos suyos guardados."""
    almacen = _almacen(args)
    try:
        datos = perfil_de_arbitro(almacen, args.nombre, ultimos=args.ultimos)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            conocidos = almacen.consulta(
                "SELECT arbitro, COUNT(*) AS n FROM partidos WHERE arbitro IS NOT NULL "
                "GROUP BY arbitro ORDER BY n DESC LIMIT 10")
            if conocidos:
                imprimir("\nÁrbitros que sí están en la memoria:")
                for fila in conocidos:
                    imprimir(f"    {fila['n']:>3}  {fila['arbitro']}")
            return 1
        por = datos["por_partido"]
        imprimir(f"{datos['arbitro']} — {datos['partidos_mirados']} partidos\n")
        imprimir(f"  {por['amarillas']} amarillas · {por['rojas']} rojas · "
                 f"{por['penaltis']} penaltis · {por['faltas']} faltas, por partido")
        reparto = datos["reparto_de_tarjetas"]
        imprimir(f"  Tarjetas: {reparto['al_local']} al local, "
                 f"{reparto['al_visitante']} al visitante")
        imprimir(f"  Gana el local en {datos['victorias_locales']}")
        if datos.get("aviso"):
            imprimir(f"\n  {datos['aviso']}")
        return 0
    finally:
        almacen.close()


def cmd_previa(args: argparse.Namespace) -> int:
    """Todo lo que se sabe de un partido antes de jugarse."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args)
    try:
        if getattr(args, "abastecer", False) or getattr(args, "plan", False):
            from ..abastecer import abastecer, planear

            if args.plan:
                plan = planear(cliente, almacen, args.consulta, ultimos=args.contexto)
                cuentas = plan.cuentas(almacen)
                imprimir(f"{cuentas['partido']}")
                imprimir(f"  hacen falta {cuentas['en_total']} partidos: "
                         f"{cuentas['de_cada_uno']['local']} del local, "
                         f"{cuentas['de_cada_uno']['visitante']} del visitante, "
                         f"{cuentas['entre_ellos']} entre ellos"
                         + (f", {cuentas['del_arbitro']} de {cuentas['arbitro']}"
                            if cuentas["arbitro"] else ""))
                imprimir(f"  ya están {cuentas['ya_estaban']}; faltan "
                         f"{cuentas['hay_que_pedir']} (~{cuentas['peticiones_estimadas']} "
                         "peticiones)")
                return 0
            resumen = abastecer(cliente, almacen, args.consulta, ultimos=args.contexto,
                                maximo_peticiones=args.max, avisar=imprimir)
            imprimir("")
            imprimir(f"{resumen['guardados']} traídos, {resumen['ya_estaban']} ya estaban, "
                     f"{resumen['peticiones']} peticiones, {resumen['fallos']} fallos.")
            for linea in envolver(resumen["como_leerlo"], 74):
                imprimir(f"  {linea}")
            imprimir("")

        datos = previa(almacen, args.consulta, cliente=cliente,
                       ultimos=args.ultimos, jugadores_por_equipo=args.jugadores)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        for linea in texto(datos):
            imprimir(linea)
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        cliente.close()


def cmd_pronostico(args: argparse.Namespace) -> int:
    """El pronóstico de un partido: marcador, córners y tarjetas, calculados."""
    from ..pronostico import pronostico
    from ..pronostico import texto as texto_pronostico

    almacen = _almacen(args)
    cliente = comun.construir_cliente(args)
    try:
        if args.abastecer:
            from ..abastecer import abastecer

            abastecer(cliente, almacen, args.consulta, avisar=imprimir)
            imprimir("")
        datos = pronostico(almacen, args.consulta, cliente=cliente, ultimos=args.contexto)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        for linea in texto_pronostico(datos):
            imprimir(linea)
        depuracion(args, cliente)
        return 0 if datos.get("disponible") else 1
    finally:
        almacen.close()
        cliente.close()


# --------------------------------------------------------- jugador contra sistema

EJES = {"presion": "la presión del rival", "linea": "la línea defensiva del rival",
        "balon": "quién domina el balón"}


def _fila_metrica(datos: dict) -> str:
    """Una métrica comparada, en una línea legible."""
    signo = "+" if datos["diferencia"] >= 0 else ""
    marca = {"señal": "!!", "indicio": " !", "sin muestra": " ?"}.get(datos["veredicto"], "  ")
    cola = "" if "p" not in datos else f"  p={datos['p']:.3f}"
    return (f"  {marca} {datos['por_90']:>6.2f} /90  "
            f"(su media {datos['su_media_por_90']:>5.2f}, {signo}{datos['diferencia']:.2f})"
            f"{cola}")


def cmd_sistema(args: argparse.Namespace) -> int:
    """Con qué suele plantear un equipo."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args) if args.buscar else None
    try:
        equipo_id, nombre = _equipo_id(almacen, args.consulta, cliente)
        if equipo_id is None:
            imprimir(f"No encuentro '{args.consulta}' en la memoria. Prueba con --buscar.")
            return 1
        datos = sistema_habitual(almacen, equipo_id, ultimos=args.ultimos)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            return 1
        imprimir(f"{datos['equipo']} — {datos['partidos']} partidos mirados\n")
        formaciones = ", ".join(f"{f} ({n})" for f, n in datos["formaciones"].items())
        imprimir(f"  Dibujo:    {formaciones or '—'}")
        imprimir(f"  Posesión:  {datos['posesion']}%")
        imprimir(f"  Presión:   {datos['presion']} pases concedidos por acción defensiva")
        imprimir(f"  Concede:   {datos['xg_concedido']} xG · "
                 f"{datos['tiros_concedidos']} tiros por partido\n")
        imprimir("  Así juega, comparado con su liga")
        for eje, etiqueta in datos["asi_juega"].items():
            imprimir(f"    · {eje:<8} {etiqueta}")
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def cmd_contra(args: argparse.Namespace) -> int:
    """Cómo rinde un jugador según el sistema que le pongan delante."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args) if args.buscar else None
    try:
        jugador_id, nombre = _jugador_id(almacen, args.consulta, cliente)
        if jugador_id is None:
            imprimir(f"No encuentro '{args.consulta}' en la memoria. Prueba con --buscar.")
            return 1
        if args.desglose:
            return _imprimir_desglose(desglose_por_favorito(almacen, jugador_id, eje=args.eje),
                                      args)
        datos = jugador_contra_sistema(almacen, jugador_id, eje=args.eje, solo=args.solo)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            return 1

        media = datos["su_media"]
        imprimir(f"{datos['jugador']} — agrupado por {EJES.get(args.eje, args.eje)}"
                 + (f", solo siendo {args.solo.replace('_', ' ')}" if args.solo else ""))
        imprimir(f"  {media['partidos']} partidos, {media['minutos']} minutos en total"
                 + (f" · {datos['partidos_con_cuotas']} con cuotas"
                    if datos.get("partidos_con_cuotas") else ""))
        imprimir("")

        for etiqueta, grupo in datos["grupos"].items():
            reparto = grupo.get("siendo_favorito") or {}
            favorito = (f", favorito en {reparto['favorito']}"
                        if reparto.get("favorito") or reparto.get("no_favorito") else "")
            imprimir(f"  Contra {etiqueta}  ({grupo['partidos']} partidos, "
                     f"{grupo['minutos']} min, nota {grupo.get('rating') or '—'}{favorito})")
            for metrica in args.metricas.split(",") if args.metricas else _destacadas(grupo):
                fila = grupo["comparado_con_su_media"].get(metrica.strip())
                if fila:
                    imprimir(f"    {metrica.strip():<16}{_fila_metrica(fila)}")
            imprimir("")

        relevante = lo_relevante(datos)
        if relevante:
            imprimir("  Lo que se sale de su propia media")
            for hallazgo in relevante:
                imprimir(f"    · contra {hallazgo['contra']}: {hallazgo['metrica']} "
                         f"{hallazgo['por_90']}/90 frente a {hallazgo['su_media']} "
                         f"({hallazgo['veredicto']}, p={hallazgo['p']})")
        else:
            imprimir("  Nada se sale de lo que explicaría el azar.")

        if datos["partidos_sin_clasificar"]:
            imprimir(f"\n  {datos['partidos_sin_clasificar']} partidos sin clasificar "
                     "(faltan estadísticas o alineación del rival).")
        imprimir("")
        for linea in envolver(datos["lo_que_no_dice"], 74):
            imprimir(f"  {linea}")
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def _imprimir_desglose(datos: dict, args: argparse.Namespace) -> int:
    """El análisis partido en dos: siendo favorito y sin serlo."""
    if args.stdout_json:
        imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        return 0
    if not datos.get("disponible"):
        imprimir(datos["siendo_favorito"].get("nota") or datos["sin_ser_favorito"].get("nota"))
        return 1
    imprimir(f"{datos['jugador']} — ¿es el sistema o es el contexto?\n")
    for clave, titulo in (("siendo_favorito", "Siendo favorito"),
                          ("sin_ser_favorito", "Sin ser favorito")):
        bloque = datos[clave]
        if not bloque.get("disponible"):
            imprimir(f"  {titulo}: {bloque.get('nota')}\n")
            continue
        imprimir(f"  {titulo}: {bloque['su_media']['partidos']} partidos")
        for etiqueta, grupo in bloque["grupos"].items():
            imprimir(f"    contra {etiqueta:<16} {grupo['partidos']} partidos, "
                     f"{grupo['por_90'].get('tiros', 0):.2f} tiros/90, "
                     f"{grupo['por_90'].get('goles', 0):.2f} goles/90")
        imprimir("")
    if datos["lectura"]:
        imprimir("  Lo que se sale de su media, y de dónde viene")
        for fila in datos["lectura"]:
            imprimir(f"    · contra {fila['contra']}, {fila['metrica']}: {fila['veredicto']}")
    else:
        imprimir("  Nada se sale de su media en ninguno de los dos desgloses.")
    imprimir("")
    for linea in envolver(datos["como_leerlo"], 74):
        imprimir(f"  {linea}")
    return 0


def _destacadas(grupo: dict) -> list[str]:
    """Las métricas que se enseñan por defecto: pocas, y solo si dicen algo.

    Una fila de ceros contra una media de cero no es información, es ruido con
    formato de tabla: se cae de la lista.
    """
    comparado = grupo["comparado_con_su_media"]
    return [m for m in ("tiros", "tiros_a_puerta", "goles", "asistencias",
                        "pases_clave", "regates", "duelos_ganados", "xg")
            if m in comparado
            and (comparado[m]["por_90"] or comparado[m]["su_media_por_90"])]


def cmd_duelo(args: argparse.Namespace) -> int:
    """Qué le pasa a este jugador contra lo que ese rival suele plantear."""
    almacen = _almacen(args)
    cliente = comun.construir_cliente(args) if args.buscar else None
    try:
        jugador_id, jugador = _jugador_id(almacen, args.jugador, cliente)
        rival_id, rival = _equipo_id(almacen, args.rival, cliente)
        if jugador_id is None or rival_id is None:
            imprimir(f"No encuentro '{args.jugador if jugador_id is None else args.rival}' "
                     "en la memoria. Prueba con --buscar.")
            return 1
        datos = duelo(almacen, jugador_id, rival_id)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        if not datos["disponible"]:
            imprimir(datos["nota"])
            return 1

        rival_datos = datos["rival"]
        imprimir(f"{datos['jugador']} contra el sistema de {rival_datos['equipo']}\n")
        formaciones = ", ".join(f"{f} ({n})" for f, n in rival_datos["formaciones"].items())
        imprimir(f"  {rival_datos['equipo']} en sus últimos {rival_datos['partidos']} "
                 f"partidos: {formaciones or 'sin alineaciones guardadas'}")
        imprimir(f"  {rival_datos['posesion']}% de posesión · presión "
                 f"{rival_datos['presion']} · concede {rival_datos['xg_concedido']} xG\n")

        for eje, bloque in datos["por_eje"].items():
            imprimir(f"  Como {eje}: {bloque['el_rival_es']}")
            resumen = bloque["resumen"]
            if not resumen:
                imprimir("    Este jugador no se ha medido nunca a eso "
                         "(de lo que hay guardado).\n")
                continue
            imprimir(f"    {resumen['partidos']} partidos, {resumen['minutos']} min, "
                     f"nota {resumen.get('rating') or '—'}")
            for hallazgo in resumen["relevante"] or []:
                imprimir(f"    · {hallazgo['metrica']}: {hallazgo['por_90']}/90 "
                         f"frente a su media de {hallazgo['su_media']} "
                         f"({hallazgo['veredicto']}, p={hallazgo['p']})")
            if not resumen["relevante"]:
                imprimir("    Nada que no explique el azar.")
            contra = ", ".join(f"{c['rival']} ({c['fecha']})"
                               for c in resumen["contra"][:8])
            for n, linea in enumerate(envolver(f"Contra: {contra}", 70)):
                imprimir(f"    {linea}" if n == 0 else f"            {linea}")
            imprimir("")

        for linea in envolver(datos["lo_que_no_dice"], 74):
            imprimir(f"  {linea}")
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def cmd_briefing(args: argparse.Namespace) -> int:
    """El documento de la mañana: todos los partidos del día, analizados."""
    from ..barrido import barrer
    from ..briefing import a_markdown, briefing, guardar

    cliente = comun.construir_cliente(args)
    almacen = _almacen(args)
    try:
        grupos = args.grupos.split(",") if args.grupos else None
        if args.barrer:
            imprimir("Barriendo antes de escribir el briefing…")
            resumen = barrer(cliente, almacen, fecha=args.date, grupos=grupos,
                             ultimos=args.ultimos, maximo_peticiones=args.max,
                             avisar=imprimir if not args.quiet else None)
            imprimir(f"Guardados {resumen['guardados']} partidos nuevos "
                     f"({resumen['peticiones']} peticiones).\n")
        datos = briefing(almacen, cliente, fecha=args.date, grupos=grupos,
                         ultimos=args.ultimos, jugadores=args.jugadores)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        texto_md = a_markdown(datos)
        if not args.quiet:
            imprimir(texto_md)
        if not args.no_guardar:
            rutas = guardar(datos, args.carpeta)
            imprimir(f"Escrito en {rutas['markdown']} y {rutas['json']}")
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        cliente.close()


def cmd_seguro(args: argparse.Namespace) -> int:
    """Lo que casi siempre pasa, con el número que lo sostiene."""
    from ..seguro import ELEVACION_MINIMA, MINIMO_CASOS, avisos, calibrar

    almacen = _almacen(args)
    cliente = None
    try:
        liga_id = None
        if args.liga:
            from ..catalog import find_league
            from ..ligas import por_nombre

            competicion = por_nombre(args.liga)
            liga_id = (competicion.id_conocido if competicion else None) or find_league(args.liga)

        if args.calibrar:
            datos = calibrar(almacen, liga_id=liga_id, desde=args.desde)
            if args.stdout_json:
                imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
                return 0
            imprimir(f"Calibrado sobre {datos['partidos_mirados']} partidos guardados\n")
            imprimir(f"  {'PATRÓN':<24}{'CASOS':>7}{'FREC':>8}{'SUELO':>8}{'BASE':>8}"
                     f"{'ELEV':>8}  {'VEREDICTO':<17}DESPUÉS")
            for medida in datos["patrones"]:
                fuera = medida.get("fuera_de_muestra") or {}
                if medida["frecuencia"] is None:
                    imprimir(f"  {medida['patron']:<24}{medida['casos']:>7}"
                             f"{'—':>8}{'—':>8}{'—':>8}{'—':>8}  sin casos")
                    continue
                imprimir(f"  {medida['patron']:<24}{medida['casos']:>7}"
                         f"{medida['frecuencia']:>8.0%}{medida['suelo']:>8.0%}"
                         f"{(medida['base'] or 0):>8.0%}{medida['elevacion']:>+8.0%}"
                         f"  {medida['veredicto']:<17}{fuera.get('veredicto', '—')}")
            imprimir("")
            for medida in datos["patrones"]:
                if medida.get("nota"):
                    imprimir(f"  · {medida['titulo']}: {medida['nota']}")
            imprimir("")
            # La comprobación fuera de muestra, que es la que más pesa: medido
            # con lo viejo, ¿se cumplió en lo nuevo?
            for medida in datos["patrones"]:
                fuera = medida.get("fuera_de_muestra")
                if fuera and fuera["veredicto"] != "sin muestra":
                    for numero, linea in enumerate(envolver(
                            f"{medida['titulo']}: {fuera['lectura']}", 70)):
                        imprimir(("  · " if numero == 0 else "    ") + linea)
            imprimir("")
            for linea in envolver(datos["como_leerlo"], 74):
                imprimir(f"  {linea}")
            imprimir("")
            for linea in envolver(datos["lo_que_no_dice"], 74):
                imprimir(f"  {linea}")
            return 0

        cliente = comun.construir_cliente(args)
        grupos = args.grupos.split(",") if args.grupos else None
        datos = avisos(almacen, cliente, fecha=args.date, grupos=grupos,
                       umbral=args.umbral)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0
        imprimir(f"{datos['fecha']} · {datos['partidos_mirados']} partidos mirados · "
                 f"calibrado con {datos['calibrado_con']} guardados\n")
        if not datos["avisos"]:
            imprimir("Nada que destacar hoy.")
            imprimir(f"Un patrón sale aquí si supera el {args.umbral:.0%} de suelo, tiene "
                     f"al menos {MINIMO_CASOS} casos y se separa {ELEVACION_MINIMA:.0%} de "
                     "su referencia. Si la memoria es corta, no hay nada que superar: "
                     "barre más y vuelve.")
            return 0
        partido_actual = ""
        for aviso in datos["avisos"]:
            if aviso["partido"] != partido_actual:
                partido_actual = aviso["partido"]
                imprimir(f"\n{aviso['hora_utc'] or '  ?  '}  {partido_actual}"
                         f"   ({aviso['competicion']})")
            mercado = (f" · el mercado le da {aviso['mercado']:.0%}"
                       if aviso.get("mercado") else "")
            imprimir(f"    {aviso['suelo']:>5.0%} suelo · {aviso['frecuencia']:.0%} en "
                     f"{aviso['casos']} casos ({aviso['elevacion']:+.0%} sobre su "
                     f"referencia){mercado}")
            fuera = aviso.get("fuera_de_muestra") or {}
            marca = {"aguanta": "  [aguanta después]", "se cae": "  [SE CAE después]"}.get(
                fuera.get("veredicto"), "")
            imprimir(f"          {aviso['sujeto']}: {aviso['dice']}  "
                     f"[{aviso['veredicto']}]{marca}")
        imprimir("")
        for linea in envolver(datos["lo_que_no_dice"], 74):
            imprimir(f"  {linea}")
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        if cliente:
            cliente.close()


def cmd_resultados(args: argparse.Namespace) -> int:
    """El registro: qué se predijo y cómo acabó."""
    from ..registro import AUTOR_CALCULO, anotar, balance, resolver, texto

    almacen = _almacen(args)
    cliente = None
    try:
        if args.anotar:
            cliente = comun.construir_cliente(args)
            salida = anotar(almacen, args.anotar, cliente=cliente)
            imprimir(f"{salida.get('guardadas', 0)} predicciones apuntadas"
                     + (f", {salida['ya_estaban']} ya estaban"
                        if salida.get("ya_estaban") else "")
                     + (f" · {salida['nota']}" if salida.get("nota") else ""))
        if args.resolver or args.anotar:
            hechas = resolver(almacen)
            imprimir(f"{hechas['resueltas']} resueltas, "
                     f"{hechas['sin_jugar_todavia']} sin jugar todavía.")
            imprimir("")
        # Por defecto, el cálculo: es exactamente lo que medía esta pantalla antes
        # de que hubiera más autores. Con `--autor todos` se piden todos juntos, y
        # entonces lo que sale es un promedio de gente distinta, que no mide a
        # nadie: para comparar está `cancha clasificacion`.
        autor = args.autor or AUTOR_CALCULO
        datos = balance(almacen, desde=args.desde, hasta=args.hasta,
                        mercado=args.mercado,
                        autor=None if autor == "todos" else autor)
        if autor == "todos":
            imprimir("⚠ Esto mezcla a todos los autores en un solo promedio, así "
                     "que no mide a ninguno. Para compararlos: cancha clasificacion.")
            imprimir("")
        if args.json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2))
            return 0
        for linea in texto(datos):
            imprimir(linea)
        if datos.get("casos"):
            imprimir("")
            for linea in envolver(datos["como_leerlo"], 74):
                imprimir(linea)
            imprimir("")
            for linea in envolver(datos["lo_que_no_dice"], 74):
                imprimir(linea)
        pendientes = (datos.get("pendientes") or {}).get("sin_resolver") or 0
        if pendientes:
            imprimir("")
            imprimir(f"{pendientes} predicciones esperando a que se juegue el partido.")
        return 0
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()


def cmd_mercados(args: argparse.Namespace) -> int:
    """Las casas contra nosotros: un partido, traer de fuera, o el marcador exacto."""
    from .. import ajustes as modulo_ajustes
    from ..registro import marcadores_frente_a_frente

    almacen = _almacen(args)
    cliente = None
    try:
        if args.traer:
            from ..sources.casas import CasaNoDisponible, traer

            guardados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
            try:
                salida = traer(almacen, guardados, args.traer, dias=args.dias)
            except CasaNoDisponible as exc:
                imprimir(f"✗ {exc}")
                return 1
            imprimir(f"{salida['fuente']}: {salida['partidos']} partidos, "
                     f"{salida['emparejados']} emparejados con los nuestros, "
                     f"{salida['filas']} cuotas nuevas.")
            if salida["cuantos_sin_pareja"]:
                imprimir(f"{salida['cuantos_sin_pareja']} sin pareja (ligas que no "
                         "sigues, o nombres que se escriben muy distinto):")
                for nombre in salida["sin_pareja"][:10]:
                    imprimir(f"    {nombre}")
            return 0

        if args.marcadores or not args.consulta:
            datos = marcadores_frente_a_frente(almacen)
            if not datos.get("casos"):
                imprimir(datos["nota"])
                return 0
            imprimir(f"Marcador exacto, {datos['casos']} partidos jugados:")
            imprimir("")
            imprimir(f"{'':<26}{'nosotros':>10}{'mercado':>10}")
            for etiqueta, clave in (("Prob. al que salió", "p_real"),
                                    ("Log score (más es mejor)", "log"),
                                    ("Acertó el primero", "top1"),
                                    ("Estaba entre los 3", "top3")):
                formato = ".3f" if clave == "log" else ".1%"
                imprimir(f"{etiqueta:<26}{format(datos[clave + '_uno'], formato):>10}"
                         f"{format(datos[clave + '_otro'], formato):>10}")
            imprimir("")
            for linea in envolver(datos["lectura"], 74):
                imprimir(linea)
            return 0

        from ..mercados import frente_al_mercado, refrescar
        from ..previa import _resolver
        from ..pronostico import pronostico

        cliente = comun.construir_cliente(args)
        evento = _resolver(almacen, args.consulta, cliente)
        if evento is None:
            imprimir("No encuentro ese partido.")
            return 1
        refrescar(cliente, almacen, evento, forzar=args.refrescar)
        datos = frente_al_mercado(almacen, evento.id,
                                  pronostico(almacen, evento, cliente=cliente))
        if args.json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2))
            return 0
        imprimir(f"{evento.home.name} - {evento.away.name}")
        if not datos.get("disponible"):
            imprimir(datos["nota"])
            return 0
        imprimir("")
        imprimir(f"{'':<22}{'nosotros':>9}{'mercado':>9}{'cuota':>7}{'dif.':>8}")
        for s in datos["sucesos"]:
            nuestra = f"{s['nuestra']:.0%}" if s["nuestra"] is not None else "—"
            suya = f"{s['mercado']:.0%}" if s["mercado"] is not None else "—"
            dif = f"{s['diferencia']:+.0%}" if s["diferencia"] is not None else "—"
            imprimir(f"{s['suceso']:<22}{nuestra:>9}{suya:>9}"
                     f"{s['cuota'] or '—':>7}{dif:>8}{'  ←' if s['discrepa'] else ''}")
        exacto = datos["marcador_exacto"]
        if exacto.get("mas_probables_nuestros"):
            imprimir("")
            imprimir(f"Marcador exacto ({exacto['casa']}):")
            for (m1, p1), (m2, p2) in zip(exacto["mas_probables_nuestros"],
                                          exacto["mas_probables_mercado"], strict=False):
                imprimir(f"    nosotros {m1:>5} {p1:5.1%}      mercado {m2:>5} {p2:5.1%}")
        elif exacto.get("nota"):
            imprimir("")
            imprimir(exacto["nota"])
        imprimir("")
        for linea in envolver(datos["como_leerlo"], 74):
            imprimir(linea)
        return 0
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()


def cmd_picks(args: argparse.Namespace) -> int:
    """Los picks del día con su regla, apuntarlos, resolverlos y su historial."""
    from .. import ajustes as modulo_ajustes
    from ..picks import REGLA, apuntados, apuntar, del_dia, historial, resolver

    almacen = _almacen(args)
    cliente = None
    try:
        if args.resolver:
            hechos = resolver(almacen)
            imprimir(f"{hechos['resueltos']} picks resueltos, {hechos['pendientes']} "
                     "esperando a que se juegue el partido.")
            imprimir("")
        if args.historial:
            for nivel in ("gratis", "premium"):
                h = historial(almacen, nivel)
                imprimir(f"{nivel.upper()}")
                if not h.get("picks"):
                    imprimir(f"  {h.get('nota')}")
                    imprimir("")
                    continue
                imprimir(f"  {h['picks']} picks ({h['desde']} → {h['hasta']}) · "
                         f"{h['aciertos']} acertados ({h['acierto']:.0%}) · cuota "
                         f"media {h['cuota_media']}")
                imprimir(f"  {h['unidades']:+.2f} unidades · rendimiento "
                         f"{h['rendimiento']:+.1%}"
                         + (f" [{h['intervalo'][0]:+.1%}, {h['intervalo'][1]:+.1%}]"
                            if h.get("intervalo") else "")
                         + f" · peor racha {h['peor_racha']:+.2f}")
                if h.get("gana_al_cierre") is not None:
                    imprimir(f"  gana al cierre en el {h['gana_al_cierre']:.0%} "
                             f"({h['con_cierre']} con cierre) · CLV medio "
                             f"{h['clv_medio']:+.1%}")
                for linea in envolver(h["lectura"], 72):
                    imprimir(f"  {linea}")
                imprimir("")
            return 0

        from datetime import datetime, timezone

        fecha = args.fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dia = None if args.apuntar else apuntados(almacen, fecha)
        if dia is None:
            cliente = comun.construir_cliente(args)
            guardados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
            dia = del_dia(almacen, cliente, fecha=fecha,
                          grupos=modulo_ajustes.grupos_de(guardados))
        if args.json:
            imprimir(json.dumps(dia, ensure_ascii=False, indent=2, default=str))
            return 0
        imprimir(f"Picks del {fecha} · {REGLA['version']}"
                 + (" · apuntados" if dia.get("apuntado") else " · calculados ahora"))
        imprimir("")
        if not dia["premium"]:
            for linea in envolver(dia.get("nota") or "Nada pasa la regla hoy.", 74):
                imprimir(linea)
        for n, pick in enumerate(dia["premium"], 1):
            marca = "GRATIS " if n == 1 else "       "
            imprimir(f"{marca}{pick.get('partido') or pick['partido_id']}")
            imprimir(f"        {pick['suceso']} a {pick['cuota']} ({pick['casa']}) · "
                     f"nosotros {pick['prob_nuestra']:.0%}, mercado "
                     f"{pick['prob_mercado']:.0%} · valor {pick['valor']:+.1%}")
        if dia.get("casi"):
            imprimir("")
            imprimir("Lo más cerca de pasar, y por qué no:")
            for casi in dia["casi"][:5]:
                imprimir(f"    {casi['partido']}: {casi['suceso']} a {casi['cuota']} — "
                         f"{', '.join(casi['por_que_no'])}")
        if args.apuntar:
            hechos = apuntar(almacen, dia)
            imprimir("")
            imprimir(f"{hechos['apuntados']} apuntados con el precio de ahora. Lo "
                     "apuntado ya no se puede cambiar.")
        return 0
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()


def cmd_historia(args: argparse.Namespace) -> int:
    """Traerse años de partidos de golpe, en vez de seis por equipo."""
    from .. import ajustes as modulo_ajustes
    from ..historia import plan, traer

    guardados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
    suyo = guardados.get("historia") or {}
    anos = args.anos or suyo.get("anos", 3)
    secciones = ([s.strip() for s in args.secciones.split(",") if s.strip()]
                 if args.secciones else list(suyo.get("secciones") or []))
    grupos = ([g.strip() for g in args.grupos.split(",") if g.strip()]
              if args.grupos else modulo_ajustes.grupos_de(guardados))
    maximo = args.max if args.max is not None else suyo.get("max", 0)

    almacen = _almacen(args)
    cliente = comun.construir_cliente(args)
    try:
        previsto = plan(cliente, almacen, grupos, anos=anos, secciones=secciones)
        imprimir(f"{previsto['ligas']} competiciones · {previsto['temporadas']} "
                 f"temporadas · desde {previsto['desde']}")
        imprimir(f"Con {', '.join(secciones) or 'las secciones de siempre'}: "
                 f"unos {previsto['partidos_estimados']:,} partidos y "
                 f"{previsto['peticiones_estimadas']:,} peticiones."
                 .replace(",", "."))
        imprimir("")
        for linea in envolver(previsto["aviso"], 74):
            imprimir(linea)
        if args.plan:
            imprimir("")
            for liga in previsto["por_liga"]:
                if liga.get("error"):
                    imprimir(f"  ✗ {liga['liga']}: {liga['error']}")
                else:
                    imprimir(f"  {liga['liga']}: {liga['temporadas']} temporadas")
            imprimir("")
            imprimir("Eso es el plan. Quítale --plan para traerlo de verdad.")
            return 0

        imprimir("")
        salida = traer(cliente, almacen, grupos, anos=anos, secciones=secciones,
                       maximo=maximo, avisar=imprimir)
        imprimir("")
        imprimir(f"{salida['guardados']} traídos · {salida['ya_estaban']} ya estaban "
                 f"· {salida['sin_estadisticas']} sin estadísticas · "
                 f"{salida['fallos']} fallos · {salida['peticiones']} peticiones")
        if not salida["completo"]:
            imprimir("")
            imprimir("Se ha parado en el tope. Vuelve a darle y sigue por donde iba: "
                     "lo que ya está no se vuelve a pedir.")
        imprimir("")
        for linea in envolver(salida["como_leerlo"], 74):
            imprimir(linea)
        depuracion(args, cliente)
        return 0
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()


def registrar(sub, comun_p, informe, listado) -> None:
    """Añade los comandos de la memoria."""
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--db", help=f"Fichero de la memoria (por defecto: {RUTA_POR_DEFECTO}).")
    base.add_argument("--ultimos", type=int, default=6,
                      help="Cuántos partidos recientes mirar (por defecto 6).")
    base.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON.")

    p_barrido = sub.add_parser(
        "barrido", parents=[comun_p, base],
        help="Trae los partidos del día y el historial de quien juega.",
        description="El primer barrido es caro; los siguientes casi no, porque "
                    "solo entra lo nuevo. Se puede cortar y reanudar.",
    )
    p_barrido.add_argument("--date", help="Día a barrer (AAAA-MM-DD; por defecto, hoy).")
    p_barrido.add_argument("--grupos",
                           help=f"Competiciones: {', '.join(GRUPOS)} o nombres sueltos, "
                                "separados por comas.")
    p_barrido.add_argument("--max", type=int, default=0,
                           help="Tope de peticiones, para probar sin gastar la mañana.")
    p_barrido.add_argument("--quiet", action="store_true", help="Sin ir contando.")
    p_barrido.set_defaults(func=cmd_barrido)

    p_memoria = sub.add_parser("memoria", parents=[base], help="Qué hay guardado.")
    p_memoria.set_defaults(func=cmd_memoria)

    p_agenda = sub.add_parser("agenda", parents=[comun_p, base],
                              help="Qué se juega hoy en las competiciones elegidas.")
    p_agenda.add_argument("--date", help="AAAA-MM-DD (por defecto, hoy).")
    p_agenda.add_argument("--grupos", help="Competiciones, separadas por comas.")
    p_agenda.set_defaults(func=cmd_agenda)

    p_estilo = sub.add_parser("estilo", parents=[comun_p, base],
                              help="Cómo juega un equipo, comparado con su liga.")
    p_estilo.add_argument("consulta", help="Nombre o id del equipo.")
    p_estilo.add_argument("--buscar", action="store_true",
                          help="Preguntar a la API si no está en la memoria.")
    p_estilo.add_argument("--evolucion", action="store_true",
                          help="Cómo juega ahora frente a cómo jugaba antes.")
    p_estilo.set_defaults(func=cmd_estilo)

    p_forma = sub.add_parser("forma", parents=[comun_p, base],
                             help="Cómo está un jugador y qué rachas lleva.")
    p_forma.add_argument("consulta", help="Nombre o id del jugador.")
    p_forma.add_argument("--buscar", action="store_true",
                         help="Preguntar a la API si no está en la memoria.")
    p_forma.set_defaults(func=cmd_forma)

    p_arbitro = sub.add_parser("arbitro", parents=[base],
                               help="Cómo pita alguien, según lo guardado.")
    p_arbitro.add_argument("nombre", help="Nombre del árbitro.")
    p_arbitro.set_defaults(func=cmd_arbitro)

    p_previa = sub.add_parser(
        "previa", parents=[comun_p, base],
        help="Todo lo que se sabe de un partido antes de jugarse.")
    p_previa.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_previa.add_argument("--jugadores", type=int, default=4,
                          help="Cuántos jugadores destacar por equipo.")
    p_previa.add_argument("--abastecer", action="store_true",
                          help="Traer antes todo lo que falte: los últimos partidos de "
                               "cada equipo, los que han jugado entre ellos y los del "
                               "árbitro. La primera vez tarda; las siguientes, no.")
    p_previa.add_argument("--plan", action="store_true",
                          help="Solo decir qué haría falta traer y cuánto costaría.")
    p_previa.add_argument("--contexto", type=int, default=10,
                          help="Partidos anteriores de cada equipo al abastecer (10).")
    p_previa.add_argument("--max", type=int, default=0,
                          help="Tope de peticiones al abastecer (0 = sin tope).")
    p_previa.set_defaults(func=cmd_previa)

    p_pronostico = sub.add_parser(
        "pronostico", parents=[comun_p, base],
        help="Marcador, córners y tarjetas de un partido, calculados.",
        description="Fuerzas de ataque y defensa medidas en xG sobre lo guardado, "
                    "una Poisson para el marcador y las líneas, y el árbitro para las "
                    "tarjetas. Los números salen de la aritmética, no de una "
                    "corazonada, y se comparan con la cuota: donde coinciden no hay "
                    "nada que ganar.")
    p_pronostico.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_pronostico.add_argument("--contexto", type=int, default=10,
                              help="Partidos de cada equipo a mirar (por defecto 10).")
    p_pronostico.add_argument("--abastecer", action="store_true",
                              help="Traer antes lo que falte de ese partido.")
    p_pronostico.set_defaults(func=cmd_pronostico)

    p_sistema = sub.add_parser(
        "sistema", parents=[comun_p, base],
        help="Con qué suele plantear un equipo: dibujo, presión y posesión.")
    p_sistema.add_argument("consulta", help="Nombre o id del equipo.")
    p_sistema.add_argument("--buscar", action="store_true",
                           help="Preguntar a la API si no está en la memoria.")
    p_sistema.set_defaults(func=cmd_sistema)

    p_contra = sub.add_parser(
        "contra", parents=[comun_p, base],
        help="Cómo rinde un jugador según el sistema del rival.",
        description="Agrupa sus partidos por cómo jugó el rival —medido partido "
                    "a partido, no supuesto— y compara cada grupo con la media "
                    "del propio jugador, contrastando la diferencia contra el azar.",
    )
    p_contra.add_argument("consulta", help="Nombre o id del jugador.")
    p_contra.add_argument("--eje", choices=["presion", "linea", "balon"],
                          default="presion", help="Por qué se agrupa (por defecto: presion).")
    p_contra.add_argument("--metricas",
                          help="Métricas a enseñar, separadas por comas.")
    p_contra.add_argument("--solo", choices=["favorito", "no_favorito"],
                          help="Solo los partidos en que su equipo era (o no) favorito.")
    p_contra.add_argument("--desglose", action="store_true",
                          help="El análisis dos veces, siendo favorito y sin serlo: "
                               "separa el sistema del contexto.")
    p_contra.add_argument("--buscar", action="store_true",
                          help="Preguntar a la API si no está en la memoria.")
    p_contra.set_defaults(func=cmd_contra)

    p_duelo = sub.add_parser(
        "duelo", parents=[comun_p, base],
        help="Un jugador contra lo que suele plantear un rival concreto.",
        description="La pregunta de la que sale todo esto: no cómo va el "
                    "jugador ni cómo juega el rival, sino qué ha hecho el uno "
                    "cuando le han puesto delante lo que el otro suele poner.",
    )
    p_duelo.add_argument("jugador", help="Nombre o id del jugador.")
    p_duelo.add_argument("rival", help="Nombre o id del equipo rival.")
    p_duelo.add_argument("--buscar", action="store_true",
                         help="Preguntar a la API si no está en la memoria.")
    p_duelo.set_defaults(func=cmd_duelo)

    p_briefing = sub.add_parser(
        "briefing", parents=[comun_p, base],
        help="El documento de la mañana: todos los partidos del día, analizados.",
        description="Agenda, cómo llega cada equipo, si ha cambiado, quién lleva "
                    "racha, qué le pasa a sus jugadores contra el sistema del rival, "
                    "el mercado y el árbitro. En Markdown y JSON, uno por día.",
    )
    p_briefing.add_argument("--date", help="AAAA-MM-DD (por defecto, hoy).")
    p_briefing.add_argument("--grupos", help="Competiciones, separadas por comas.")
    p_briefing.add_argument("--barrer", action="store_true",
                            help="Hacer el barrido antes, para que salga con datos frescos.")
    p_briefing.add_argument("--max", type=int, default=0,
                            help="Tope de peticiones del barrido previo.")
    p_briefing.add_argument("--jugadores", type=int, default=3,
                            help="Jugadores a seguir por equipo.")
    p_briefing.add_argument("--carpeta", default="datos/briefings",
                            help="Dónde guardarlo (por defecto: datos/briefings).")
    p_briefing.add_argument("--no-guardar", action="store_true", help="Solo por pantalla.")
    p_briefing.add_argument("--quiet", action="store_true", help="Sin volcarlo por pantalla.")
    p_briefing.set_defaults(func=cmd_briefing)

    p_mercados = sub.add_parser(
        "mercados", parents=[comun_p, base],
        help="Las casas contra nosotros, suceso a suceso y en marcador exacto.",
        description="Con un partido: lo que dice cada mercado al lado de nuestro "
                    "pronóstico, dónde discrepan y cómo se ha movido la cuota. Sin "
                    "partido: quién acierta más en marcador exacto, nosotros o el "
                    "mercado, sobre los partidos ya jugados. Con --traer, cuotas de "
                    "Betfair o de The Odds API (hacen falta sus claves en Ajustes).",
    )
    p_mercados.add_argument("consulta", nargs="?", help="El partido (opcional).")
    p_mercados.add_argument("--traer", choices=["betfair", "the-odds-api"],
                            help="Traer cuotas de otra fuente para los próximos días.")
    p_mercados.add_argument("--dias", type=int, default=2,
                            help="Cuántos días hacia delante con --traer.")
    p_mercados.add_argument("--marcadores", action="store_true",
                            help="Quién acierta más en marcador exacto.")
    p_mercados.add_argument("--refrescar", action="store_true",
                            help="Volver a pedir las cuotas aunque sean recientes.")
    p_mercados.add_argument("--json", action="store_true", help="Volcar el JSON.")
    p_mercados.set_defaults(func=cmd_mercados)

    p_picks = sub.add_parser(
        "picks", parents=[comun_p, base],
        help="Los picks del día: una regla fija, el precio y su historial.",
        description="No es «la apuesta segura del día», que no existe: es una regla "
                    "escrita antes, igual todos los días, apuntada con el precio al "
                    "que se da y medida después al precio tomado, con su intervalo y "
                    "su CLV. Los días en que nada pasa la regla, no hay pick.",
    )
    p_picks.add_argument("--fecha", help="Otro día (AAAA-MM-DD).")
    p_picks.add_argument("--apuntar", action="store_true",
                         help="Apuntarlos con el precio de ahora (no se puede deshacer).")
    p_picks.add_argument("--resolver", action="store_true",
                         help="Resolver los de partidos ya jugados.")
    p_picks.add_argument("--historial", action="store_true",
                         help="Cómo han ido, en cada nivel.")
    p_picks.add_argument("--json", action="store_true", help="Volcar el JSON.")
    p_picks.set_defaults(func=cmd_picks)

    p_historia = sub.add_parser(
        "historia", parents=[comun_p, base],
        help="Trae años de partidos de golpe, no seis por equipo.",
        description="La memoria se llenaba partido a partido, y así no se junta "
                    "muestra: para que un perfil de equipo signifique algo hacen "
                    "falta un par de temporadas. Esto recorre cada competición "
                    "temporada a temporada hacia atrás. Se puede cortar y seguir: "
                    "lo que ya está guardado no se vuelve a pedir, así que la "
                    "segunda vez cuesta mucho menos. Mira antes lo que va a costar "
                    "con --plan.",
    )
    p_historia.add_argument("--anos", "--años", type=int, dest="anos",
                            help="Cuántos años hacia atrás (por defecto, los ajustes).")
    p_historia.add_argument("--grupos", help="Competiciones, separadas por comas.")
    p_historia.add_argument("--secciones",
                            help="Qué pedir de cada partido, separado por comas. "
                                 "Cada una es una petición más por partido.")
    p_historia.add_argument("--max", type=int,
                            help="Tope de peticiones de esta tanda. 0 = sin tope.")
    p_historia.add_argument("--plan", action="store_true",
                            help="Solo dice lo que costaría, sin traer nada.")
    p_historia.set_defaults(func=cmd_historia)

    p_resultados = sub.add_parser(
        "resultados", parents=[comun_p, base],
        help="Qué tal acierta: calibración, Brier y contra el mercado.",
        description="El registro de predicciones: lo que se apuntó antes de cada "
                    "partido y cómo acabó. Primero la calibración —de las veces que "
                    "dijo 70 %, ¿pasó el 70 %?—, después el Brier contra el 0,25 de "
                    "quien no sabe nada, y el acierto el último, con su intervalo. "
                    "Sin unidades, sin ROI y sin consejos: esto mide el cálculo.",
    )
    p_resultados.add_argument("--desde", help="Solo partidos desde esta fecha.")
    p_resultados.add_argument("--hasta", help="Solo partidos hasta esta fecha.")
    p_resultados.add_argument("--mercado", help="Solo un mercado: 1x2, mas_2_5, "
                                                "ambos_marcan, corners, tarjetas, marcador.")
    p_resultados.add_argument("--resolver", action="store_true",
                              help="Puntuar antes las que ya tengan resultado.")
    p_resultados.add_argument("--anotar", metavar="PARTIDO",
                              help="Apuntar a mano la predicción de un partido.")
    p_resultados.add_argument("--autor", help="De quién: calculo (por defecto), "
                                              "mercado, el nombre de un agente, o "
                                              "«todos» para mezclarlos.")
    p_resultados.add_argument("--json", action="store_true", help="Volcar el JSON.")
    p_resultados.set_defaults(func=cmd_resultados)

    p_seguro = sub.add_parser(
        "seguro", parents=[comun_p, base],
        help="Lo que casi siempre pasa, con el número que lo sostiene.",
        description="Cuenta cada patrón sobre tu historial y publica la frecuencia, "
                    "el suelo de confianza y la elevación sobre su referencia. Nada "
                    "sale al 99 %: lo que sale es lo que tus datos aguantan.",
    )
    p_seguro.add_argument("--date", help="AAAA-MM-DD (por defecto, hoy).")
    p_seguro.add_argument("--grupos", help="Competiciones, separadas por comas.")
    p_seguro.add_argument("--calibrar", action="store_true",
                          help="La tabla entera de patrones medidos sobre el historial.")
    p_seguro.add_argument("--liga", help="Calibrar solo con una competición.")
    p_seguro.add_argument("--desde", help="Calibrar solo con partidos desde esta fecha.")
    p_seguro.add_argument("--umbral", type=float, default=0.65,
                          help="Suelo mínimo para avisar (por defecto 0.65).")
    p_seguro.set_defaults(func=cmd_seguro)
