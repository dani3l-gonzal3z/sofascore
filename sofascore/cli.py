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
from pathlib import Path

from . import __version__
from .cache import DiskCache, NullCache
from .client import SofascoreClient
from .config import Settings
from .endpoints import SECTIONS
from .errors import SofascoreError
from .export import to_csv_dir, to_json, to_markdown
from .match import build_report
from .resolve import resolve_event


# --------------------------------------------------------------------- utilidades

def _construir_cliente(args: argparse.Namespace) -> SofascoreClient:
    ajustes = Settings.from_env(
        language=getattr(args, "lang", None),
        sport=getattr(args, "sport", None),
        rate_limit=getattr(args, "rate", None),
        timeout=getattr(args, "timeout", None),
        offline=True if getattr(args, "offline", False) else None,
        cache_dir=Path(args.cache_dir) if getattr(args, "cache_dir", None) else None,
    )
    cache = NullCache() if getattr(args, "no_cache", False) else None
    return SofascoreClient(ajustes, cache=cache)


def _imprimir(texto: str = "") -> None:
    print(texto, flush=True)


# ------------------------------------------------------------------------ comandos

def cmd_match(args: argparse.Namespace) -> int:
    cliente = _construir_cliente(args)
    try:
        resolucion = resolve_event(cliente, args.consulta, date=args.date, strict=args.strict)
        if not args.quiet:
            _imprimir(f"Partido: {resolucion.event.label}")
            _imprimir(f"         id={resolucion.event.id} · {resolucion.event.url}")
            if len(resolucion.candidates) > 1 and not args.date:
                _imprimir(f"         (otros {len(resolucion.candidates) - 1} candidatos; "
                          f"usa --date para afinar)")
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

        if args.debug:
            _imprimir(f"\nPeticiones: {cliente.stats.as_dict()}")
            _imprimir(f"Ajustes: {cliente.settings.redacted()}")
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


def cmd_sections(args: argparse.Namespace) -> int:
    _imprimir(f"{'SECCIÓN':<20} {'ÁMBITO':<8} {'POR DEFECTO':<12} DESCRIPCIÓN")
    for seccion in SECTIONS.values():
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
        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        informe = build_report(cliente, resolucion.event, sections=["shotmap"], include_plus=True)
        estado = informe.sections["shotmap"].status
        if estado == "ok":
            _imprimir("✓ Las credenciales funcionan: se han recibido datos de pago.")
            return 0
        if estado == "plus_required":
            _imprimir("🔒 Sofascore no ha aceptado las credenciales (faltan o han caducado).")
            return 1
        _imprimir(f"· Sin conclusión: la sección de prueba está '{estado}' en este partido.")
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

    sub = parser.add_subparsers(dest="comando", required=True)

    p_match = sub.add_parser("match", parents=[comun], help="Informe completo de un partido.")
    p_match.add_argument("consulta", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_match.add_argument("--date", help="Fecha del partido (AAAA-MM-DD) para desempatar.")
    p_match.add_argument("--sections", help="Secciones separadas por comas.")
    p_match.add_argument("--all", action="store_true", help="Pide todas las secciones.")
    p_match.add_argument("--no-plus", action="store_true", help="No intentes las de pago.")
    p_match.add_argument("--players", type=int, default=40,
                         help="Máximo de jugadores para las secciones por jugador.")
    p_match.add_argument("--json", help="Guarda el informe completo en este fichero.")
    p_match.add_argument("--markdown", help="Guarda un informe legible en este fichero.")
    p_match.add_argument("--csv", help="Escribe los CSV en esta carpeta.")
    p_match.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON por pantalla.")
    p_match.add_argument("--print", dest="print_section", help="Imprime solo esa sección.")
    p_match.add_argument("--strict", action="store_true",
                         help="Falla si la consulta es ambigua en vez de elegir.")
    p_match.add_argument("--quiet", action="store_true", help="Sin adornos por pantalla.")
    p_match.add_argument("--debug", action="store_true", help="Muestra contadores y ajustes.")
    p_match.set_defaults(func=cmd_match)

    p_search = sub.add_parser("search", parents=[comun], help="Busca partidos candidatos.")
    p_search.add_argument("consulta")
    p_search.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_sections = sub.add_parser("sections", help="Lista las secciones del catálogo.")
    p_sections.set_defaults(func=cmd_sections)

    p_login = sub.add_parser("login", parents=[comun],
                             help="Comprueba tus credenciales de Sofascore Plus.")
    p_login.add_argument("consulta", nargs="?", help="Partido con el que probarlas.")
    p_login.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_login.set_defaults(func=cmd_login)

    p_raw = sub.add_parser("raw", parents=[comun], help="Pide una ruta cualquiera de la API.")
    p_raw.add_argument("ruta", help="P. ej. /event/11352550/statistics")
    p_raw.set_defaults(func=cmd_raw)

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
