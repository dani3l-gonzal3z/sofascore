"""Comandos de equipos, jugadores, competiciones y listados de partidos."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import LEAGUES, find_league
from ..endpoints import CATALOGS
from ..entities import build_player_report, build_team_report, build_tournament_report
from ..models import Event
from ..resolve import normalizar
from . import comun
from .comun import depuracion, imprimir


def _informe_entidad(args: argparse.Namespace, constructor, **extra) -> int:
    cliente = comun.construir_cliente(args)
    try:
        secciones = ["all"] if args.all else (args.sections.split(",") if args.sections else None)
        informe = constructor(cliente, args.consulta, sections=secciones, **extra)
        informe.meta["peticiones"] = cliente.stats.as_dict()
        if args.print_section:
            imprimir(json.dumps(informe.get(args.print_section), ensure_ascii=False,
                                 indent=2, default=str))
        elif args.stdout_json:
            imprimir(json.dumps(informe.to_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            imprimir(informe.summary())
        if args.json:
            Path(args.json).write_text(
                json.dumps(informe.to_dict(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            imprimir(f"\nJSON escrito en {args.json}")
        if informe.locked():
            imprimir(f"\n🔒 Requieren Sofascore Plus: {', '.join(informe.locked())}")
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_team(args: argparse.Namespace) -> int:
    return _informe_entidad(args, build_team_report)


def cmd_player(args: argparse.Namespace) -> int:
    return _informe_entidad(args, build_player_report)


def cmd_league(args: argparse.Namespace) -> int:
    return _informe_entidad(args, build_tournament_report, season_id=args.season)


def _filtrar_eventos(
    eventos: list[Event], texto: str | None = None, liga: str | None = None
) -> list[Event]:
    """Deja solo los partidos que interesan.

    ``liga`` se resuelve contra el catálogo de ligas conocidas y filtra por id de
    competición, que es exacto. Si el nombre no está en el catálogo se trata como
    texto libre, que también busca en los nombres de los equipos.
    """
    if liga:
        identificador = find_league(liga)
        if identificador:
            eventos = [e for e in eventos if e.unique_tournament_id == identificador]
        else:
            texto = texto or liga
    if texto:
        buscado = normalizar(texto)
        eventos = [
            e for e in eventos
            if buscado in normalizar(f"{e.home} {e.away} {e.tournament}")
        ]
    return eventos


def _listar_eventos(eventos: list[Event], limite: int, total: int | None = None) -> None:
    """Los agrupa por competición: 150 partidos en una lista plana no se leen."""
    if not eventos:
        if total:
            imprimir(f"Ninguno de los {total} partidos encaja con el filtro.")
        else:
            imprimir("No hay ningún partido ahora mismo.")
        return

    por_torneo: dict[str, list[Event]] = {}
    for evento in eventos:
        por_torneo.setdefault(evento.tournament or "Sin competición", []).append(evento)

    mostrados = 0
    for torneo in sorted(por_torneo):
        if mostrados >= limite:
            break
        imprimir(f"\n{torneo}")
        for evento in por_torneo[torneo]:
            if mostrados >= limite:
                break
            estado = evento.status_description or evento.status_type
            imprimir(f"  {evento.label.split(' (')[0]:<45} {estado:<12} id={evento.id}")
            mostrados += 1

    restantes = len(eventos) - mostrados
    resumen = f"\n{len(eventos)} partido(s) en {len(por_torneo)} competición(es)"
    if restantes > 0:
        resumen += f"; se enseñan {mostrados} (sube --limit o afina con --filter)"
    imprimir(resumen + ".")


def cmd_live(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        eventos = [Event.from_api(e) for e in cliente.live_events(args.sport)]
        elegidos = _filtrar_eventos(eventos, args.filtro, args.league)
        _listar_eventos(elegidos, args.limit, total=len(eventos))
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_today(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        fecha = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        eventos = [Event.from_api(e) for e in cliente.scheduled_events(fecha, args.sport)]
        imprimir(f"Partidos del {fecha}:")
        elegidos = _filtrar_eventos(eventos, args.filtro, args.league)
        _listar_eventos(elegidos, args.limit, total=len(eventos))
        depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_leagues(args: argparse.Namespace) -> int:
    filtro = (args.filtro or "").lower()
    encontradas = {k: v for k, v in LEAGUES.items() if filtro in k.lower()}
    imprimir(f"{'ID':>7}  LIGA")
    for nombre, identificador in sorted(encontradas.items()):
        imprimir(f"{identificador:>7}  {nombre}")
    imprimir(f"\n{len(encontradas)} liga(s). Úsalas con: cancha league \"<nombre>\"")
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    catalogo = CATALOGS[args.kind]
    imprimir(f"Secciones de '{args.kind}':\n")
    imprimir(f"{'SECCIÓN':<20} {'ÁMBITO':<8} {'POR DEFECTO':<12} DESCRIPCIÓN")
    for seccion in catalogo.values():
        marca = "sí" if seccion.default else "no"
        etiqueta = "plus" if seccion.requires_plus else "público"
        imprimir(f"{seccion.name:<20} {etiqueta:<8} {marca:<12} {seccion.description}")
    imprimir("\nUsa --sections a,b,c para elegir, o --all para pedirlas todas.")
    return 0


def registrar(sub, comun, informe, listado) -> None:
    """Añade los subcomandos de esta familia al parser."""
    p_team = sub.add_parser("team", parents=[comun, informe],
                            help="Informe de un equipo: plantilla, calendario, forma.")
    p_team.add_argument("consulta", help="Nombre o id del equipo.")
    p_team.set_defaults(func=cmd_team)

    p_player = sub.add_parser("player", parents=[comun, informe],
                              help="Informe de un jugador: ficha, atributos, temporadas.")
    p_player.add_argument("consulta", help="Nombre o id del jugador.")
    p_player.set_defaults(func=cmd_player)

    p_league = sub.add_parser("league", parents=[comun, informe],
                              help="Informe de una competición: tabla, jornadas, goleadores.")
    p_league.add_argument("consulta", help="Nombre, alias ('laliga') o id de la competición.")
    p_league.add_argument("--season", type=int,
                          help="Id de temporada (por defecto, la que está en curso).")
    p_league.set_defaults(func=cmd_league)

    p_live = sub.add_parser("live", parents=[comun, listado],
                            help="Partidos que se juegan ahora mismo.")
    p_live.set_defaults(func=cmd_live)

    p_today = sub.add_parser("today", parents=[comun, listado], help="Partidos de un día.")
    p_today.add_argument("--date", help="AAAA-MM-DD (por defecto, hoy).")
    p_today.set_defaults(func=cmd_today)

    p_leagues = sub.add_parser("leagues", help="Ligas conocidas con su id.")
    p_leagues.add_argument("filtro", nargs="?", help="Filtra por nombre.")
    p_leagues.set_defaults(func=cmd_leagues)

    p_sections = sub.add_parser("sections", help="Lista las secciones del catálogo.")
    p_sections.add_argument("--kind", default="match", choices=sorted(CATALOGS),
                            help="De qué catálogo (match, team, player, tournament).")
    p_sections.set_defaults(func=cmd_sections)
