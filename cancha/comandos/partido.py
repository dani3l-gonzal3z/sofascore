"""Comandos sobre un partido: el informe, la búsqueda, el análisis y el cruce."""

from __future__ import annotations

import argparse
import json

from ..export import to_csv_dir, to_json, to_markdown
from ..match import build_report
from ..resolve import resolve_event
from . import comun
from .comun import depuracion, envolver, imprimir


def cmd_match(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date, strict=args.strict)
        if not args.quiet:
            imprimir(f"Partido: {resolucion.event.label}")
            imprimir(f"         id={resolucion.event.id} · {resolucion.event.url}")
            if resolucion.warning:
                imprimir(f"    ⚠    {resolucion.warning}")
            otros = resolucion.candidates[1:]
            if otros:
                # Con --date puesto, decir "usa --date" no ayuda a nadie: se
                # enseñan los otros candidatos, que es lo que deja elegir.
                plural = "otro candidato" if len(otros) == 1 else f"otros {len(otros)} candidatos"
                imprimir(f"         ({plural}:)")
                for candidato in otros[:3]:
                    imprimir(f"           · {candidato.event.label} "
                              f"id={candidato.event.id}")
                if len(otros) > 3:
                    imprimir(f"           · ...y {len(otros) - 3} más "
                              f"(`cancha search` los lista todos)")
            imprimir()

        secciones = ["all"] if args.all else (args.sections.split(",") if args.sections else None)
        informe = build_report(
            cliente,
            resolucion.event,
            sections=secciones,
            include_plus=not args.no_plus,
            max_players=args.players,
        )
        informe.meta["peticiones"] = cliente.stats.as_dict()

        if args.print_section:
            datos = informe.get(args.print_section)
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        elif args.stdout_json:
            imprimir(to_json(informe))
        elif not args.quiet:
            imprimir(informe.summary())

        if args.json:
            to_json(informe, args.json)
            imprimir(f"\nJSON escrito en {args.json}")
        if args.markdown:
            to_markdown(informe, args.markdown)
            imprimir(f"Markdown escrito en {args.markdown}")
        if args.csv:
            creados = to_csv_dir(informe, args.csv)
            imprimir(f"CSV escritos: {', '.join(str(c) for c in creados) or 'ninguno'}")

        procedencia = (
            resolucion.sources if resolucion.sources
            else f"no hizo falta buscar ({resolucion.source})"
        )
        depuracion(args, cliente, f"Candidatos por fuente: {procedencia}")
        if informe.locked() and not args.quiet:
            imprimir(f"\n🔒 Requieren Sofascore Plus: {', '.join(informe.locked())}")
            imprimir("   Configura SOFA_PLUS_COOKIE con tu propia sesión para incluirlas.")
        return 0
    finally:
        cliente.close()


def cmd_search(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        imprimir(f"{len(resolucion.candidates)} candidato(s) para '{args.consulta}':\n")
        for candidato in resolucion.candidates[: args.limit]:
            evento = candidato.event
            imprimir(f"  {candidato.score:5.2f}  {evento.label}")
            imprimir(f"         id={evento.id} · {candidato.reason}")
        return 0
    finally:
        cliente.close()


def cmd_analisis(args: argparse.Namespace) -> int:
    """Las métricas calculadas de un partido."""
    from ..analisis import analisis_completo

    cliente = comun.construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        informe = build_report(
            cliente, resolucion.event,
            sections=["statistics", "shotmap", "incidents", "lineups"],
        )
        datos = analisis_completo(informe, cada=args.cada)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0

        imprimir(f"{datos['partido']['titulo']}  "
                  f"({datos['partido']['competicion']}, {datos['partido']['fecha']})")

        puntos = datos["puntos_esperados"]
        if puntos.get("disponible"):
            imprimir("\n¿Ganó el que mereció?")
            for resultado, probabilidad in puntos["probabilidades"].items():
                imprimir(f"  {resultado:<28} {probabilidad:6.1%}")
            imprimir("  puntos esperados: " + " · ".join(
                f"{equipo} {valor}" for equipo, valor in puntos["puntos_esperados"].items()))
            for linea in envolver(puntos["lectura"], 72):
                imprimir(f"  {linea}")
        else:
            imprimir(f"\n¿Ganó el que mereció? — {puntos.get('nota')}")

        calidad = datos["calidad_de_tiro"]
        if calidad.get("disponible"):
            imprimir("\nCalidad de las ocasiones")
            for equipo, bloque in calidad["por_equipo"].items():
                if not bloque.get("tiros"):
                    continue
                imprimir(f"  {equipo}")
                imprimir(f"    {bloque['tiros']} tiros · xG {bloque['xg_total']} "
                          f"({bloque['xg_por_tiro']} por tiro) · "
                          f"{bloque['ocasiones_claras']} claras · "
                          f"{bloque['tiros_lejanos']} lejanos")
                for linea in envolver(bloque["lectura"], 68):
                    imprimir(f"    {linea}")

        carrera = datos["carrera_xg"]
        if carrera.get("disponible") and carrera.get("manda_en_xg"):
            imprimir(f"\nManda en xG: {carrera['manda_en_xg']}"
                      + (f", desde el minuto {carrera['desde_el_minuto']}"
                         if carrera.get("desde_el_minuto") else ""))

        aportacion = datos["aportacion"]
        if aportacion.get("disponible"):
            imprimir("\nQuién generó el peligro")
            for jugador in aportacion["jugadores"][:6]:
                imprimir(f"  {jugador['jugador']:<24} xG {jugador['xg']:<6} "
                          f"{jugador['goles']}g {jugador['asistencias']}a  "
                          f"({jugador['equipo']})")
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_contexto(args: argparse.Namespace) -> int:
    """Un partido visto por todas las fuentes a la vez."""
    from ..sources import contexto_partido

    cliente = comun.construir_cliente(args)
    try:
        datos = contexto_partido(cliente, args.consulta, fecha=args.date)
        if args.stdout_json:
            imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
            return 0

        partido = datos["partido"]
        imprimir(f"{partido['local']} {partido['marcador']} {partido['visitante']}  "
                  f"({partido['competicion']}, {partido['fecha']})\n")

        xg = datos["sofascore"].get("xg")
        if xg:
            imprimir(f"  xG Sofascore      {xg.get('local')} - {xg.get('visitante')}")

        understat = datos["fuentes"].get("understat") or {}
        if understat.get("estado") == "ok" and understat.get("xg"):
            u = understat["xg"]
            imprimir(f"  xG Understat      {u.get('local')} - {u.get('visitante')}")
        else:
            imprimir(f"  xG Understat      – {understat.get('nota', 'no disponible')}")

        contraste = datos.get("contraste_xg") or {}
        if contraste.get("posible"):
            imprimir(f"\n  Discrepancia máxima entre modelos: {contraste['discrepancia_maxima']}")
            for linea in envolver(contraste["lectura"], 74):
                imprimir(f"  {linea}")

        elo = datos["fuentes"].get("clubelo") or {}
        if elo.get("estado") == "ok":
            imprimir(f"\n  Elo  {elo['local']['equipo']} {elo['local']['elo']} "
                      f"(#{elo['local']['puesto']})  vs  "
                      f"{elo['visitante']['equipo']} {elo['visitante']['elo']} "
                      f"(#{elo['visitante']['puesto']})")
            imprimir(f"       Probabilidad del local según Elo: "
                      f"{elo['probabilidad_local']:.0%}")
        else:
            imprimir("\n  Elo               – no disponible")
            for linea in envolver(elo.get("nota", ""), 70):
                imprimir(f"    {linea}")
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def registrar(sub, comun, informe, listado) -> None:
    """Añade los subcomandos de esta familia al parser."""
    p_match = sub.add_parser("match", parents=[comun, informe],
                             help="Informe completo de un partido.")
    p_match.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_match.add_argument("--date", help="Fecha del partido (AAAA-MM-DD) para desempatar.")
    p_match.add_argument("--no-plus", action="store_true", help="No intentes las de pago.")
    p_match.add_argument("--players", type=int, default=40,
                         help="Máximo de jugadores para las secciones por jugador.")
    p_match.add_argument("--markdown", help="Guarda un informe legible en este fichero.")
    p_match.add_argument("--csv", help="Escribe los CSV en esta carpeta.")
    p_match.add_argument("--strict", action="store_true",
                         help="Falla si la consulta es ambigua en vez de elegir.")
    p_match.add_argument("--quiet", action="store_true", help="Sin adornos por pantalla.")
    p_match.set_defaults(func=cmd_match)

    p_search = sub.add_parser("search", parents=[comun], help="Busca partidos candidatos.")
    p_search.add_argument("consulta")
    p_search.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_analisis = sub.add_parser(
        "analisis", parents=[comun],
        help="Las cuentas hechas: puntos esperados, calidad de tiro, carrera de xG.",
    )
    p_analisis.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_analisis.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_analisis.add_argument("--cada", type=int, default=15,
                            help="Minutos por tramo en la carrera de xG.")
    p_analisis.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON.")
    p_analisis.set_defaults(func=cmd_analisis)

    p_contexto = sub.add_parser(
        "contexto", parents=[comun],
        help="Un partido visto por todas las fuentes: xG de dos modelos y Elo.",
    )
    p_contexto.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_contexto.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_contexto.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON.")
    p_contexto.set_defaults(func=cmd_contexto)
