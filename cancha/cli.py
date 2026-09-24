"""Línea de comandos del framework.

    cancha match "Real Madrid vs Barcelona" --date 2024-10-26
    cancha analisis 12437616
    cancha contexto 12437616
    cancha team "Real Madrid" --all
    cancha live --league laliga
    cancha grabar 12437616
    cancha mcp

Aquí solo está el armazón: qué comandos hay lo dicen los módulos de
:mod:`cancha.comandos`, cada uno con su ``registrar``. Sin argumentos de red no
hace nada raro: todo sale por pantalla y solo escribe ficheros si se lo pides.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .comandos import FAMILIAS, parsers_padre
from .errors import SofascoreError


def build_parser() -> argparse.ArgumentParser:
    """Monta el parser pidiéndole sus comandos a cada familia."""
    parser = argparse.ArgumentParser(
        prog="cancha",
        description="Le dices un partido y te da todos sus datos, de Sofascore y "
                    "de otras fuentes, listos para analizar.",
    )
    parser.add_argument("--version", action="version", version=f"cancha {__version__}")

    comun, informe, listado = parsers_padre()
    sub = parser.add_subparsers(dest="comando", required=True)
    for familia in FAMILIAS:
        familia.registrar(sub, comun, informe, listado)
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
