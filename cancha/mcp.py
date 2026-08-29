"""Servidor MCP: enchufa el framework a una IA local.

MCP (*Model Context Protocol*) es el estándar por el que un modelo descubre
herramientas y las llama. Lo hablan Claude Desktop, LM Studio, Continue,
Cline y cada vez más clientes locales.

Aquí está implementado a mano sobre JSON-RPC y ``stdin``/``stdout``, sin
dependencias: el framework sigue funcionando nada más descargarlo. Se arranca
con::

    sofascore mcp

y el cliente se configura apuntando a ese comando. En Claude Desktop, dentro de
``claude_desktop_config.json``::

    {
      "mcpServers": {
        "sofascore": {
          "command": "python",
          "args": ["-m", "sofascore", "mcp"]
        }
      }
    }

A partir de ahí el modelo ve las 14 herramientas de :mod:`cancha.tools` y
puede ir tirando del hilo él solo.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .client import SofascoreClient
from .config import Settings
from .sesion import Sesion
from .tools import TOOLS, ejecutar

#: Versión del protocolo que hablamos.
PROTOCOL_VERSION = "2024-11-05"

INSTRUCCIONES = (
    "Datos de fútbol (y otros deportes) de Sofascore: partidos, equipos, "
    "jugadores y competiciones.\n\n"
    "Para analizar un partido, empieza siempre por `resumen_partido`: te da lo "
    "esencial y, sobre todo, qué secciones de datos existen para ese partido. "
    "Desde ahí tira del hilo con `estadisticas_partido`, `jugadores_partido`, "
    "`tiros_partido` (xG por disparo), `cronologia_partido` o `momento_partido`.\n\n"
    "Si no sabes qué pedir o qué nombre usar, llama a `catalogo`. Si dudas de "
    "qué partido se habla, `buscar_partido` primero.\n\n"
    "Las respuestas vienen recortadas para no llenarte el contexto: cuando veas "
    "`recortado: true`, afina la consulta (por equipo, por jugador, por periodo)."
)


def _respuesta(id_: Any, resultado: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": resultado}


def _error(id_: Any, codigo: int, mensaje: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": codigo, "message": mensaje}}


class MCPServer:
    """El servidor. Lee peticiones de una línea y contesta en otra."""

    def __init__(self, cliente: SofascoreClient | None = None,
                 sesion: Sesion | None = None) -> None:
        self.cliente = cliente or SofascoreClient(Settings.from_env())
        # Una sola sesión para toda la conversación: el modelo pregunta ocho
        # cosas del mismo partido y cada sección se pide una vez.
        self.sesion = sesion or Sesion(cliente=self.cliente)

    # --- métodos del protocolo ---

    def initialize(self, _params: dict) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sofascore", "version": _version()},
            "instructions": INSTRUCCIONES,
        }

    def tools_list(self, _params: dict) -> dict:
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.parameters,
                }
                for t in TOOLS.values()
            ]
        }

    def tools_call(self, params: dict) -> dict:
        nombre = params.get("name", "")
        argumentos = params.get("arguments") or {}
        resultado = ejecutar(nombre, argumentos, sesion=self.sesion)
        es_error = isinstance(resultado, dict) and "error" in resultado
        return {
            "content": [
                {"type": "text",
                 "text": json.dumps(resultado, ensure_ascii=False, indent=1, default=str)}
            ],
            "isError": es_error,
        }

    # --- bucle ---

    def manejar(self, peticion: dict) -> dict | None:
        """Atiende una petición. Devuelve ``None`` si es una notificación."""
        metodo = peticion.get("method", "")
        id_ = peticion.get("id")
        params = peticion.get("params") or {}

        # Las notificaciones (sin id) no llevan respuesta.
        if id_ is None:
            return None

        rutas = {
            "initialize": self.initialize,
            "tools/list": self.tools_list,
            "tools/call": self.tools_call,
            "ping": lambda _p: {},
        }
        if metodo not in rutas:
            return _error(id_, -32601, f"Método no soportado: {metodo}")
        try:
            return _respuesta(id_, rutas[metodo](params))
        except Exception as exc:  # noqa: BLE001 - el servidor no se cae por una petición
            return _error(id_, -32603, f"Error interno: {exc}")

    def servir(self, entrada: TextIO | None = None, salida: TextIO | None = None) -> int:
        """Bucle principal: una petición JSON por línea, una respuesta por línea."""
        entrada = entrada or sys.stdin
        salida = salida or sys.stdout
        try:
            for linea in entrada:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    peticion = json.loads(linea)
                except json.JSONDecodeError:
                    respuesta = _error(None, -32700, "JSON mal formado")
                else:
                    respuesta = self.manejar(peticion)
                if respuesta is not None:
                    salida.write(json.dumps(respuesta, ensure_ascii=False, default=str) + "\n")
                    salida.flush()
        except (KeyboardInterrupt, BrokenPipeError):
            pass
        finally:
            self.sesion.close()
            self.cliente.close()
        return 0


def _version() -> str:
    from . import __version__

    return __version__


def servir(cliente: SofascoreClient | None = None) -> int:
    """Arranca el servidor sobre stdin/stdout."""
    return MCPServer(cliente).servir()


__all__ = ["MCPServer", "servir", "PROTOCOL_VERSION", "INSTRUCCIONES"]
