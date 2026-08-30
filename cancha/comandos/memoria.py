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
from ..perfiles import estilo_de_equipo, forma_de_jugador, perfil_de_arbitro
from ..previa import previa, texto
from ..resolve import normalizar
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
    p_previa.set_defaults(func=cmd_previa)
