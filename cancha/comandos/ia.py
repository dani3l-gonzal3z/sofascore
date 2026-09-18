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


def cmd_web(args: argparse.Namespace) -> int:
    """La interfaz: un servidor local y una página que se instala como app."""
    from ..sesion import Sesion
    from ..web import Servidor, arrancar

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente, ruta_almacen=args.db or "datos/cancha.db")
    app = Servidor(sesion=sesion, clave=args.clave or "",
                   carpeta_briefings=args.briefings or "datos/briefings")
    host = "0.0.0.0" if args.lan else (args.host or "127.0.0.1")
    return arrancar(app, host=host, puerto=args.port, abrir=args.abrir, avisar=imprimir)


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

    p_web = sub.add_parser(
        "web", parents=[comun],
        help="La interfaz: un servidor local y una página que se instala como app.",
        description="Sirve la página en tu ordenador. Con --lan también desde el "
                    "móvil en la misma wifi; en iOS, Safari → Compartir → «Añadir a "
                    "pantalla de inicio». Sin dependencias: es la biblioteca estándar.",
    )
    p_web.add_argument("--port", type=int, default=8765, help="Puerto (por defecto 8765).")
    p_web.add_argument("--host", help="Interfaz de red (por defecto solo este ordenador).")
    p_web.add_argument("--lan", action="store_true",
                       help="Escuchar en toda la red local, para abrirla desde el móvil.")
    p_web.add_argument("--abrir", action="store_true", help="Abrir el navegador al arrancar.")
    p_web.add_argument("--clave", help="Pedir esta clave a quien use la API (para --lan).")
    p_web.add_argument("--db", help="Fichero de la memoria (por defecto: datos/cancha.db).")
    p_web.add_argument("--briefings", help="Carpeta de los briefings guardados.")
    p_web.set_defaults(func=cmd_web)
