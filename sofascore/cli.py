"""Línea de comandos del framework.

    sofascore match "Real Madrid vs Barcelona" --date 2024-10-26
    sofascore match https://www.sofascore.com/.../#id:11352550 --all --json partido.json
    sofascore search "Betis Sevilla"
    sofascore sections
    sofascore login
    sofascore raw /event/11352550/statistics

Sin argumentos de red no hace nada raro: todo sale por pantalla y solo escribe
ficheros si se lo pides con ``--json``, ``--markdown`` o ``--csv``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .cache import DiskCache, NullCache
from .catalog import LEAGUES, find_league
from .client import SofascoreClient
from .config import Settings
from .endpoints import CATALOGS, SECTIONS
from .entities import build_player_report, build_team_report, build_tournament_report
from .errors import SofascoreError
from .export import to_csv_dir, to_json, to_markdown
from .match import build_report
from .models import Event
from .resolve import normalizar, resolve_event


# --------------------------------------------------------------------- utilidades

def _construir_cliente(args: argparse.Namespace) -> SofascoreClient:
    ajustes = Settings.from_env(
        language=getattr(args, "lang", None),
        sport=getattr(args, "sport", None),
        rate_limit=getattr(args, "rate", None),
        timeout=getattr(args, "timeout", None),
        offline=True if getattr(args, "offline", False) else None,
        concurrency=getattr(args, "parallel", None),
        transport=getattr(args, "transport", None),
        cache_dir=Path(args.cache_dir) if getattr(args, "cache_dir", None) else None,
    )
    cache = NullCache() if getattr(args, "no_cache", False) else None
    return SofascoreClient(ajustes, cache=cache)


def _imprimir(texto: str = "") -> None:
    print(texto, flush=True)


def _depuracion(args: argparse.Namespace, cliente: SofascoreClient, extra: str = "") -> None:
    """El bloque de --debug, igual en todos los comandos."""
    if not getattr(args, "debug", False):
        return
    if extra:
        _imprimir(f"\n{extra}")
    _imprimir(f"Peticiones: {cliente.stats.as_dict()}")
    _imprimir(f"Transporte: {type(cliente.transport).__name__}")
    _imprimir(f"Ajustes: {cliente.settings.redacted()}")


# ------------------------------------------------------------------------ comandos

def cmd_match(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date, strict=args.strict)
        if not args.quiet:
            _imprimir(f"Partido: {resolucion.event.label}")
            _imprimir(f"         id={resolucion.event.id} · {resolucion.event.url}")
            if resolucion.warning:
                _imprimir(f"    ⚠    {resolucion.warning}")
            otros = resolucion.candidates[1:]
            if otros:
                # Con --date puesto, decir "usa --date" no ayuda a nadie: se
                # enseñan los otros candidatos, que es lo que deja elegir.
                plural = "otro candidato" if len(otros) == 1 else f"otros {len(otros)} candidatos"
                _imprimir(f"         ({plural}:)")
                for candidato in otros[:3]:
                    _imprimir(f"           · {candidato.event.label} "
                              f"id={candidato.event.id}")
                if len(otros) > 3:
                    _imprimir(f"           · ...y {len(otros) - 3} más "
                              f"(`sofascore search` los lista todos)")
            _imprimir()

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
            _imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        elif args.stdout_json:
            _imprimir(to_json(informe))
        elif not args.quiet:
            _imprimir(informe.summary())

        if args.json:
            to_json(informe, args.json)
            _imprimir(f"\nJSON escrito en {args.json}")
        if args.markdown:
            to_markdown(informe, args.markdown)
            _imprimir(f"Markdown escrito en {args.markdown}")
        if args.csv:
            creados = to_csv_dir(informe, args.csv)
            _imprimir(f"CSV escritos: {', '.join(str(c) for c in creados) or 'ninguno'}")

        procedencia = (
            resolucion.sources if resolucion.sources
            else f"no hizo falta buscar ({resolucion.source})"
        )
        _depuracion(args, cliente, f"Candidatos por fuente: {procedencia}")
        if informe.locked() and not args.quiet:
            _imprimir(f"\n🔒 Requieren Sofascore Plus: {', '.join(informe.locked())}")
            _imprimir("   Configura SOFA_PLUS_COOKIE con tu propia sesión para incluirlas.")
        return 0
    finally:
        cliente.close()


def cmd_search(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        _imprimir(f"{len(resolucion.candidates)} candidato(s) para '{args.consulta}':\n")
        for candidato in resolucion.candidates[: args.limit]:
            evento = candidato.event
            _imprimir(f"  {candidato.score:5.2f}  {evento.label}")
            _imprimir(f"         id={evento.id} · {candidato.reason}")
        return 0
    finally:
        cliente.close()


def _informe_entidad(args: argparse.Namespace, constructor, **extra) -> int:
    cliente = _construir_cliente(args)
    try:
        secciones = ["all"] if args.all else (args.sections.split(",") if args.sections else None)
        informe = constructor(cliente, args.consulta, sections=secciones, **extra)
        informe.meta["peticiones"] = cliente.stats.as_dict()
        if args.print_section:
            _imprimir(json.dumps(informe.get(args.print_section), ensure_ascii=False,
                                 indent=2, default=str))
        elif args.stdout_json:
            _imprimir(json.dumps(informe.to_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            _imprimir(informe.summary())
        if args.json:
            Path(args.json).write_text(
                json.dumps(informe.to_dict(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            _imprimir(f"\nJSON escrito en {args.json}")
        if informe.locked():
            _imprimir(f"\n🔒 Requieren Sofascore Plus: {', '.join(informe.locked())}")
        _depuracion(args, cliente)
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
            _imprimir(f"Ninguno de los {total} partidos encaja con el filtro.")
        else:
            _imprimir("No hay ningún partido ahora mismo.")
        return

    por_torneo: dict[str, list[Event]] = {}
    for evento in eventos:
        por_torneo.setdefault(evento.tournament or "Sin competición", []).append(evento)

    mostrados = 0
    for torneo in sorted(por_torneo):
        if mostrados >= limite:
            break
        _imprimir(f"\n{torneo}")
        for evento in por_torneo[torneo]:
            if mostrados >= limite:
                break
            estado = evento.status_description or evento.status_type
            _imprimir(f"  {evento.label.split(' (')[0]:<45} {estado:<12} id={evento.id}")
            mostrados += 1

    restantes = len(eventos) - mostrados
    resumen = f"\n{len(eventos)} partido(s) en {len(por_torneo)} competición(es)"
    if restantes > 0:
        resumen += f"; se enseñan {mostrados} (sube --limit o afina con --filter)"
    _imprimir(resumen + ".")


def cmd_live(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        eventos = [Event.from_api(e) for e in cliente.live_events(args.sport)]
        elegidos = _filtrar_eventos(eventos, args.filtro, args.league)
        _listar_eventos(elegidos, args.limit, total=len(eventos))
        _depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_today(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        fecha = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        eventos = [Event.from_api(e) for e in cliente.scheduled_events(fecha, args.sport)]
        _imprimir(f"Partidos del {fecha}:")
        elegidos = _filtrar_eventos(eventos, args.filtro, args.league)
        _listar_eventos(elegidos, args.limit, total=len(eventos))
        _depuracion(args, cliente)
        return 0
    finally:
        cliente.close()


def cmd_leagues(args: argparse.Namespace) -> int:
    filtro = (args.filtro or "").lower()
    encontradas = {k: v for k, v in LEAGUES.items() if filtro in k.lower()}
    _imprimir(f"{'ID':>7}  LIGA")
    for nombre, identificador in sorted(encontradas.items()):
        _imprimir(f"{identificador:>7}  {nombre}")
    _imprimir(f"\n{len(encontradas)} liga(s). Úsalas con: sofascore league \"<nombre>\"")
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    catalogo = CATALOGS[args.kind]
    _imprimir(f"Secciones de '{args.kind}':\n")
    _imprimir(f"{'SECCIÓN':<20} {'ÁMBITO':<8} {'POR DEFECTO':<12} DESCRIPCIÓN")
    for seccion in catalogo.values():
        marca = "sí" if seccion.default else "no"
        etiqueta = "plus" if seccion.requires_plus else "público"
        _imprimir(f"{seccion.name:<20} {etiqueta:<8} {marca:<12} {seccion.description}")
    _imprimir("\nUsa --sections a,b,c para elegir, o --all para pedirlas todas.")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        _imprimir(f"Credenciales: {cliente.credentials.describe()}")
        if not args.consulta:
            _imprimir("Pasa un partido (`sofascore login <id|URL|equipos>`) para comprobarlas "
                      "de verdad contra una sección de pago.")
            return 0
        # La sonda tiene que ser una sección que de verdad requiera suscripción.
        # El mapa de tiros no sirve: la API lo da abierto, así que saldría "ok"
        # tengas cuenta o no, y no diría nada de tus credenciales.
        sondas = [n for n, s in SECTIONS.items() if s.requires_plus]
        if not sondas:
            _imprimir("No hay ninguna sección de pago en el catálogo con la que probar.")
            return 0

        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        _imprimir(f"Partido de prueba: {resolucion.event.label}\n")

        # Se prueban todas hasta que una responda algo concluyente: varias de
        # ellas no existen en todos los partidos, y un 404 no dice nada de tus
        # credenciales.
        sin_conclusion = []
        for sonda in sondas:
            informe = build_report(
                cliente, resolucion.event, sections=[sonda], include_plus=True
            )
            estado = informe.sections[sonda].status
            if estado == "ok":
                _imprimir(f"✓ Las credenciales funcionan: '{sonda}' ha traído datos de pago.")
                return 0
            if estado == "plus_required":
                _imprimir(f"🔒 Sofascore ha rechazado las credenciales en '{sonda}' "
                          "(faltan o han caducado).")
                return 1
            sin_conclusion.append(f"{sonda} ({estado})")

        _imprimir("· Sin conclusión: ninguna sección de pago existe en este partido — "
                  + ", ".join(sin_conclusion) + ".")
        _imprimir("  Prueba con un partido reciente o en juego: `sofascore live` te da ids.")
        return 0
    finally:
        cliente.close()


def cmd_raw(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        datos = cliente.raw(args.ruta)
        _imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        cliente.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    """Dice con qué está pidiendo y si Sofascore le contesta."""
    from .transport import AUTO_ORDER, transport_disponible

    _imprimir("Transportes disponibles:")
    for nombre in AUTO_ORDER:
        marca = "✓" if transport_disponible(nombre) else "·"
        extra = {
            "curl": "curl_cffi — imita el TLS de Chrome, atraviesa el anti-bot",
            "httpx": "httpx — HTTP/2 y conexiones reutilizadas",
            "urllib": "biblioteca estándar, siempre está",
        }[nombre]
        _imprimir(f"  {marca} {nombre:<8} {extra}")

    cliente = _construir_cliente(args)
    try:
        elegido = type(cliente.transport).__name__
        _imprimir(f"\nEn uso: {elegido}")
        if elegido == "UrllibTransport":
            _imprimir("  ⚠  Sofascore suele responder 403 a urllib. `pip install curl_cffi`")
        _imprimir(f"Credenciales Plus: {cliente.credentials.describe()}")

        _imprimir("\nProbando contra la API...")
        for base in cliente.settings.base_urls():
            try:
                respuesta = cliente.transport.request(
                    "GET", f"{base}/sport/football/events/live", cliente._headers()
                )
                estado = f"HTTP {respuesta.status}"
                icono = "✓" if respuesta.ok else ("🚫" if respuesta.status in (401, 403) else "✗")
            except SofascoreError as exc:
                estado, icono = str(exc), "✗"
            _imprimir(f"  {icono} {base} — {estado}")
        return 0
    finally:
        cliente.close()


def cmd_cache(args: argparse.Namespace) -> int:
    ajustes = Settings.from_env(cache_dir=Path(args.cache_dir) if args.cache_dir else None)
    cache = DiskCache(ajustes.cache_dir)
    if args.clear:
        _imprimir(f"Borrados {cache.clear()} ficheros de {ajustes.cache_dir}")
    else:
        ficheros = list(Path(ajustes.cache_dir).rglob("*.json")) if ajustes.cache_dir else []
        tamano = sum(f.stat().st_size for f in ficheros) / 1024
        _imprimir(f"{len(ficheros)} respuestas en caché ({tamano:.1f} KiB) en {ajustes.cache_dir}")
    return 0


# -------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sofascore",
        description="Framework para sacar todos los datos de un partido de Sofascore.",
    )
    parser.add_argument("--version", action="version", version=f"sofascore-framework {__version__}")

    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--lang", help="Idioma preferido (por defecto: es).")
    comun.add_argument("--sport", help="Deporte para las búsquedas (por defecto: football).")
    comun.add_argument("--rate", type=float, help="Máximo de peticiones por segundo.")
    comun.add_argument("--timeout", type=float, help="Timeout por petición, en segundos.")
    comun.add_argument("--cache-dir", help="Carpeta de la caché.")
    comun.add_argument("--no-cache", action="store_true", help="Ignora la caché.")
    comun.add_argument("--offline", action="store_true", help="Solo caché, sin red.")
    comun.add_argument("--parallel", type=int,
                       help="Secciones que se piden a la vez (1 = de una en una).")
    comun.add_argument("--transport", choices=["auto", "curl", "httpx", "urllib"],
                       help="Cómo se hacen las peticiones (por defecto: auto).")
    comun.add_argument("--debug", action="store_true",
                       help="Muestra contadores de peticiones y ajustes en uso.")

    # Opciones comunes a los informes por secciones (partido, equipo, jugador, liga).
    informe = argparse.ArgumentParser(add_help=False)
    informe.add_argument("--sections", help="Secciones separadas por comas.")
    informe.add_argument("--all", action="store_true", help="Pide todas las secciones.")
    informe.add_argument("--json", help="Guarda el informe completo en este fichero.")
    informe.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON por pantalla.")
    informe.add_argument("--print", dest="print_section", help="Imprime solo esa sección.")

    sub = parser.add_subparsers(dest="comando", required=True)

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

    # Filtros comunes a los listados: sin ellos, "live" son 150 partidos de
    # amistosos y ligas juveniles y no encuentras el que buscas.
    listado = argparse.ArgumentParser(add_help=False)
    listado.add_argument("--league", help="Solo esta competición ('laliga', 'premier'...).")
    listado.add_argument("--filter", dest="filtro",
                         help="Solo los que mencionen este texto (equipo o competición).")
    listado.add_argument("--limit", type=int, default=30, help="Cuántos enseñar.")

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

    p_login = sub.add_parser("login", parents=[comun],
                             help="Comprueba tus credenciales de Sofascore Plus.")
    p_login.add_argument("consulta", nargs="?", help="Partido con el que probarlas.")
    p_login.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_login.set_defaults(func=cmd_login)

    p_raw = sub.add_parser("raw", parents=[comun], help="Pide una ruta cualquiera de la API.")
    p_raw.add_argument("ruta", help="P. ej. /event/11352550/statistics")
    p_raw.set_defaults(func=cmd_raw)

    p_doctor = sub.add_parser("doctor", parents=[comun],
                              help="Comprueba el transporte y si la API contesta.")
    p_doctor.set_defaults(func=cmd_doctor)

    p_cache = sub.add_parser("cache", help="Estado de la caché.")
    p_cache.add_argument("--clear", action="store_true", help="Vacía la caché.")
    p_cache.add_argument("--cache-dir", help="Carpeta de la caché.")
    p_cache.set_defaults(func=cmd_cache)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SofascoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ncancelado", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
