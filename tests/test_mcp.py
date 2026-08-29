"""El servidor MCP: el protocolo por el que una IA local descubre y llama."""

from __future__ import annotations

import io
import json

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.mcp import PROTOCOL_VERSION, MCPServer
from sofascore.transport import FakeTransport


@pytest.fixture
def servidor():
    cliente = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()),
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    return MCPServer(cliente)


def conversar(servidor, peticiones: list[dict]) -> list[dict]:
    entrada = io.StringIO("\n".join(json.dumps(p) for p in peticiones) + "\n")
    salida = io.StringIO()
    servidor.servir(entrada, salida)
    return [json.loads(linea) for linea in salida.getvalue().strip().splitlines() if linea]


def test_el_apreton_de_manos(servidor):
    (respuesta,) = conversar(servidor, [{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])
    resultado = respuesta["result"]
    assert resultado["protocolVersion"] == PROTOCOL_VERSION
    assert resultado["serverInfo"]["name"] == "sofascore"
    assert "tools" in resultado["capabilities"]
    # Las instrucciones son lo que enseña al modelo por dónde empezar.
    assert "resumen_partido" in resultado["instructions"]


def test_lista_las_herramientas_con_el_nombre_que_espera_mcp(servidor):
    (respuesta,) = conversar(servidor, [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    herramientas = respuesta["result"]["tools"]
    assert len(herramientas) >= 14
    # MCP las quiere en inputSchema, no en input_schema.
    assert all("inputSchema" in h for h in herramientas)
    assert all(h["description"] for h in herramientas)


def test_llama_a_una_herramienta(servidor):
    (respuesta,) = conversar(servidor, [{
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "resumen_partido", "arguments": {"partido": str(EVENT_ID)}},
    }])
    contenido = respuesta["result"]["content"][0]
    assert contenido["type"] == "text"
    assert respuesta["result"]["isError"] is False
    assert json.loads(contenido["text"])["partido"]["home"]["name"] == "Real Madrid"


def test_un_fallo_de_la_herramienta_va_marcado_pero_no_rompe(servidor):
    (respuesta,) = conversar(servidor, [{
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "no_existe", "arguments": {}},
    }])
    assert respuesta["result"]["isError"] is True
    assert "error" in json.loads(respuesta["result"]["content"][0]["text"])


def test_las_notificaciones_no_llevan_respuesta(servidor):
    respuestas = conversar(servidor, [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 9, "method": "ping"},
    ])
    assert len(respuestas) == 1
    assert respuestas[0]["id"] == 9


def test_un_metodo_desconocido_da_el_error_del_protocolo(servidor):
    (respuesta,) = conversar(servidor, [{"jsonrpc": "2.0", "id": 5, "method": "vete/tu/saber"}])
    assert respuesta["error"]["code"] == -32601


def test_json_mal_formado_no_tumba_el_servidor(servidor):
    entrada = io.StringIO('esto no es json\n{"jsonrpc":"2.0","id":7,"method":"ping"}\n')
    salida = io.StringIO()
    servidor.servir(entrada, salida)
    respuestas = [json.loads(linea) for linea in salida.getvalue().strip().splitlines()]
    assert respuestas[0]["error"]["code"] == -32700
    assert respuestas[1]["id"] == 7          # sigue atendiendo


def test_las_lineas_en_blanco_se_ignoran(servidor):
    entrada = io.StringIO('\n\n{"jsonrpc":"2.0","id":8,"method":"ping"}\n\n')
    salida = io.StringIO()
    servidor.servir(entrada, salida)
    assert len(salida.getvalue().strip().splitlines()) == 1


def test_una_conversacion_entera_como_la_de_un_cliente(servidor):
    respuestas = conversar(servidor, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "catalogo", "arguments": {"que": "ligas"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "jugadores_partido",
                    "arguments": {"partido": str(EVENT_ID), "equipo": "Barcelona"}}},
    ])
    assert [r.get("id") for r in respuestas] == [1, 2, 3, 4]
    assert all("result" in r for r in respuestas)
