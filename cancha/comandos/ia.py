"""Comandos para enchufar el framework a una IA."""

from __future__ import annotations

import argparse
import json

from ..analista import MODELO_POR_DEFECTO, URL_OLLAMA
from . import comun
from .comun import depuracion, envolver, imprimir


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


def cmd_analista(args: argparse.Namespace) -> int:
    """Pregunta en castellano; el modelo local busca los datos y contesta."""
    from ..analista import Analista, OllamaNoDisponible, texto_de_paso
    from ..sesion import Sesion

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente, ruta_almacen=args.db or "datos/cancha.db")
    analista = Analista(sesion=sesion, modelo=args.modelo, url=args.url,
                        temperatura=args.temperatura, max_vueltas=args.vueltas)
    try:
        estado = analista.comprobar()
        if args.comprobar or not estado["disponible"] or not estado.get("instalado"):
            imprimir(f"Ollama: {args.url}")
            if not estado["disponible"]:
                imprimir(f"  ✗ {estado['nota']}\n")
                for linea in estado["como"].splitlines():
                    imprimir(f"  {linea}")
                return 1
            imprimir(f"  ✓ contesta · {len(estado['modelos'])} modelos instalados")
            for modelo in estado["modelos"][:12]:
                marca = "→" if modelo["nombre"] == args.modelo else " "
                imprimir(f"    {marca} {modelo['nombre']:<28} {modelo.get('parametros') or ''}")
            if estado.get("nota"):
                imprimir(f"\n  ⚠ {estado['nota']}")
            imprimir("")
            for linea in envolver(estado["aviso_herramientas"], 74):
                imprimir(f"  {linea}")
            return 0 if args.comprobar else 1

        preguntas = [" ".join(args.pregunta)] if args.pregunta else []
        if not preguntas:
            imprimir(f"Analista con {args.modelo}. Escribe una pregunta, o 'salir'.\n")
        historial = None
        while True:
            if preguntas:
                pregunta = preguntas.pop(0)
            else:
                try:
                    pregunta = input("› ").strip()
                except (EOFError, KeyboardInterrupt):
                    imprimir("")
                    return 0
                if pregunta.lower() in ("salir", "exit", "quit", ""):
                    return 0
            try:
                salida = analista.preguntar(
                    pregunta, historial=historial,
                    al_paso=None if args.quiet else
                    (lambda paso: (texto_de_paso(paso.as_dict())
                                   and imprimir(texto_de_paso(paso.as_dict())))))
            except OllamaNoDisponible as exc:
                imprimir(f"error: {exc}")
                return 1
            historial = salida["historial"]
            imprimir("")
            for linea in envolver(salida["respuesta"], 78) or [salida["respuesta"]]:
                imprimir(linea)
            imprimir("")
            if salida.get("agotado"):
                imprimir("  (se quedó sin vueltas: sube --vueltas si hace falta)\n")
            if args.pregunta and not preguntas:
                depuracion(args, cliente)
                return 0
    finally:
        sesion.close()


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

    p_analista = sub.add_parser(
        "analista", parents=[comun],
        help="Pregunta en castellano; un modelo local busca los datos y contesta.",
        description="Habla con Ollama y le da las herramientas de cancha. Cada paso "
                    "se ve: qué preguntó, qué le contestaron y qué concluye. Los "
                    "números salen de los datos o no se dicen.",
    )
    p_analista.add_argument("pregunta", nargs="*", help="Sin pregunta, abre una conversación.")
    p_analista.add_argument("--modelo", default=MODELO_POR_DEFECTO,
                            help=f"Modelo de Ollama (por defecto: {MODELO_POR_DEFECTO}).")
    p_analista.add_argument("--url", default=URL_OLLAMA, help="Dónde escucha Ollama.")
    p_analista.add_argument("--vueltas", type=int, default=8,
                            help="Máximo de llamadas a herramientas por pregunta.")
    p_analista.add_argument("--temperatura", type=float, default=0.2)
    p_analista.add_argument("--db", help="Fichero de la memoria.")
    p_analista.add_argument("--comprobar", action="store_true",
                            help="Solo mirar si Ollama y el modelo están listos.")
    p_analista.add_argument("--quiet", action="store_true", help="Sin enseñar los pasos.")
    p_analista.set_defaults(func=cmd_analista)
