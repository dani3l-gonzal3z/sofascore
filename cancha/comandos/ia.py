"""Comandos para enchufar el framework a una IA."""

from __future__ import annotations

import argparse
import json

from . import comun
from .comun import imprimir


def cmd_mcp(args: argparse.Namespace) -> int:
    """Arranca el servidor MCP para que lo use una IA local."""
    from ..mcp import MCPServer

    cliente = comun.construir_cliente(args)
    # Nada de prints aquí: stdout es el canal del protocolo.
    return MCPServer(cliente).servir()


def cmd_tools(args: argparse.Namespace) -> int:
    """Las herramientas que ve la IA, para engancharlas a cualquier framework."""
    from ..tools import TOOLS, esquemas

    if args.json:
        imprimir(json.dumps(esquemas(), ensure_ascii=False, indent=2))
        return 0
    imprimir(f"{len(TOOLS)} herramientas para la IA:\n")
    for herramienta in TOOLS.values():
        obligatorios = herramienta.parameters.get("required", [])
        parametros = ", ".join(
            f"{n}*" if n in obligatorios else n
            for n in herramienta.parameters.get("properties", {})
        )
        imprimir(f"  {herramienta.name}({parametros})")
        primera = herramienta.description.split(". ")[0]
        imprimir(f"      {primera}.")
    imprimir("\n(* = obligatorio).  --json vuelca los esquemas completos.")
    imprimir("Arranca el servidor MCP con: cancha mcp")
    return 0


def registrar(sub, comun, informe, listado) -> None:
    """Añade los subcomandos de esta familia al parser."""
    p_mcp = sub.add_parser(
        "mcp", parents=[comun],
        help="Servidor MCP: enchufa el framework a una IA local.",
        description="Habla el Model Context Protocol por stdin/stdout. Configura "
                    "tu cliente (Claude Desktop, LM Studio, Continue...) para que "
                    "ejecute este comando.",
    )
    p_mcp.set_defaults(func=cmd_mcp)

    p_tools = sub.add_parser(
        "tools", help="Lista las herramientas que ve la IA.",
        description="Útil para engancharlas a cualquier framework de agentes, "
                    "no solo por MCP.",
    )
    p_tools.add_argument("--json", action="store_true", help="Vuelca los esquemas completos.")
    p_tools.set_defaults(func=cmd_tools)
