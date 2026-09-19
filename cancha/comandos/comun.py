"""Lo que comparten todos los comandos: cliente, impresión y opciones.

Cada familia de comandos vive en su módulo y aporta sus subcomandos con una
función ``registrar``. Aquí están las piezas que usan todas, para no repetirlas
ni hacerlas circular entre módulos.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from ..cache import NullCache
from ..client import SofascoreClient
from ..config import Settings


def construir_cliente(args: argparse.Namespace) -> SofascoreClient:
    """Un cliente con lo que se haya pedido por línea de comandos."""
    ajustes = Settings.from_env(
        language=getattr(args, "lang", None),
        sport=getattr(args, "sport", None),
        rate_limit=getattr(args, "rate", None),
        timeout=getattr(args, "timeout", None),
        offline=True if getattr(args, "offline", False) else None,
        concurrency=getattr(args, "parallel", None),
        transport=getattr(args, "transport", None),
        grabar_en=getattr(args, "record", None),
        reproducir_de=getattr(args, "replay", None),
        cache_dir=Path(args.cache_dir) if getattr(args, "cache_dir", None) else None,
    )
    cache = NullCache() if getattr(args, "no_cache", False) else None
    return SofascoreClient(ajustes, cache=cache)


def imprimir(texto: str = "") -> None:
    print(texto, flush=True)


def envolver(texto: str, ancho: int) -> list[str]:
    """Parte un texto en líneas de como mucho ``ancho`` caracteres."""
    return textwrap.wrap(texto, ancho)


def depuracion(args: argparse.Namespace, cliente: SofascoreClient, extra: str = "") -> None:
    """El bloque de ``--debug``, igual en todos los comandos."""
    if not getattr(args, "debug", False):
        return
    if extra:
        imprimir(f"\n{extra}")
    imprimir(f"Peticiones: {cliente.stats.as_dict()}")
    imprimir(f"Transporte: {type(cliente.transport).__name__}")
    imprimir(f"Ajustes: {cliente.settings.redacted()}")


def parsers_padre() -> tuple[argparse.ArgumentParser, ...]:
    """Los tres juegos de opciones que comparten unos comandos con otros.

    Devuelve ``(comun, informe, listado)``: las de red y depuración, las de los
    informes por secciones y las de los listados de partidos.
    """
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
    comun.add_argument("--record", metavar="CARPETA",
                       help="Guarda lo que responda la API en esa carpeta.")
    comun.add_argument("--replay", metavar="CARPETA",
                       help="Sirve las respuestas de esa carpeta, sin tocar la red.")

    # Opciones comunes a los informes por secciones (partido, equipo, jugador, liga).
    informe = argparse.ArgumentParser(add_help=False)
    informe.add_argument("--sections", help="Secciones separadas por comas.")
    informe.add_argument("--all", action="store_true", help="Pide todas las secciones.")
    informe.add_argument("--json", help="Guarda el informe completo en este fichero.")
    informe.add_argument("--stdout-json", action="store_true", help="Vuelca el JSON por pantalla.")
    informe.add_argument("--print", dest="print_section", help="Imprime solo esa sección.")

    # Filtros de los listados: sin ellos, "live" son 150 partidos entre
    # amistosos y categorías juveniles y no encuentras el que buscas.
    listado = argparse.ArgumentParser(add_help=False)
    listado.add_argument("--league", help="Solo esta competición ('laliga', 'premier'...).")
    listado.add_argument("--filter", dest="filtro",
                         help="Solo los que mencionen este texto (equipo o competición).")
    listado.add_argument("--limit", type=int, default=30, help="Cuántos enseñar.")

    return comun, informe, listado


__all__ = ["construir_cliente", "imprimir", "envolver", "depuracion", "parsers_padre"]
