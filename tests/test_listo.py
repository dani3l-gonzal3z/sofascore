"""`cancha listo`: que cada pieza diga lo que de verdad ha visto.

Nada de esto toca la red: cada servicio se sustituye por uno fabricado que
contesta lo que haría el de verdad en cada caso. Lo que importa es que un fallo
se diga como fallo —un modelo que no pide herramientas, un bot que no es
administrador— y que lo que no está configurado no cuente como roto.
"""

from __future__ import annotations

import pytest

from cancha import listo
from cancha.almacen import Almacen
from cancha.errors import SofascoreError
from cancha.telegrama import TelegramNoDisponible


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


# ------------------------------------------------------------------ Ollama

def _ollama(tool_calls=None, modelos=("hermes3:latest",), caido=False):
    pedidos = []

    def pedir(ruta, cuerpo=None):
        pedidos.append((ruta, cuerpo))
        if caido:
            from cancha.analista import OllamaNoDisponible
            raise OllamaNoDisponible("No hay nadie en 127.0.0.1:11434")
        if ruta == "/api/tags":
            return {"models": [{"name": m} for m in modelos]}
        return {"message": {"content": "Hay 30.000 partidos.", "tool_calls": tool_calls or []}}

    return pedir, pedidos


def test_un_modelo_que_pide_la_herramienta_esta_listo():
    pedir, pedidos = _ollama([{"function": {"name": "estado_de_la_memoria",
                                            "arguments": {}}}])
    piezas = listo.ollama({"modelo": "hermes3"}, pedir=pedir)
    assert [p["estado"] for p in piezas] == [listo.OK, listo.OK]
    # Se le ofrece la herramienta con su esquema de verdad, no uno vacío.
    cuerpo = pedidos[-1][1]
    esquema = cuerpo["tools"][0]["function"]["parameters"]
    assert esquema.get("type") == "object"


def test_un_modelo_que_contesta_sin_pedirla_es_un_fallo_y_se_dice_por_que():
    """Es el fallo más traicionero: la respuesta sale bien escrita e inventada."""
    pedir, _ = _ollama(tool_calls=[])
    piezas = listo.ollama({"modelo": "hermes3"}, pedir=pedir)
    assert piezas[-1]["estado"] == listo.MAL
    assert "inventándose" in piezas[-1]["detalle"]
    assert "hermes3" in piezas[-1]["arreglo"]


def test_sin_el_modelo_instalado_dice_cual_traer():
    pedir, _ = _ollama(modelos=("llama3.2:1b",))
    piezas = listo.ollama({"modelo": "hermes3"}, pedir=pedir)
    assert len(piezas) == 1 and piezas[0]["estado"] == listo.MAL
    assert "ollama pull hermes3" in piezas[0]["arreglo"]


def test_sin_ollama_dice_como_arrancarlo():
    pedir, _ = _ollama(caido=True)
    piezas = listo.ollama({"modelo": "hermes3"}, pedir=pedir)
    assert piezas[0]["estado"] == listo.MAL
    assert "ollama" in piezas[0]["arreglo"].lower()


# ------------------------------------------------------------------ Telegram

def _telegram(estado_en_canal="administrator", canal_roto=False):
    def pedir(metodo, cuerpo=None):
        if metodo == "getMe":
            return {"ok": True, "result": {"id": 7, "username": "cancha_bot"}}
        if metodo == "getChatMember":
            if canal_roto:
                raise TelegramNoDisponible("Telegram ha contestado 400: chat not found")
            return {"ok": True, "result": {"status": estado_en_canal}}
        raise AssertionError(metodo)

    return pedir


def test_sin_token_no_esta_roto_sino_sin_configurar():
    piezas = listo.telegram({"telegram": {"token": ""}})
    assert piezas[0]["estado"] == listo.APAGADO


def test_un_bot_que_no_es_administrador_del_canal_no_podra_publicar():
    ajustes = {"telegram": {"token": "1:A", "chats": [5], "canal_gratis": "@picks"}}
    piezas = listo.telegram(ajustes, pedir=_telegram("member"))
    canal = next(p for p in piezas if p["nombre"] == "Canal gratis")
    assert canal["estado"] == listo.MAL and "administrador" in canal["arreglo"]


def test_un_bot_administrador_y_con_chats_esta_listo():
    ajustes = {"telegram": {"token": "1:A", "chats": [5], "canal_premium": "-1001"}}
    piezas = listo.telegram(ajustes, pedir=_telegram("administrator"))
    assert [p["estado"] for p in piezas] == [listo.OK, listo.OK]
    assert "@cancha_bot" in piezas[0]["detalle"]


def test_un_canal_que_no_existe_dice_como_escribir_su_id():
    ajustes = {"telegram": {"token": "1:A", "chats": [5], "canal_gratis": "@nada"}}
    piezas = listo.telegram(ajustes, pedir=_telegram(canal_roto=True))
    assert piezas[-1]["estado"] == listo.MAL and "-100" in piezas[-1]["arreglo"]


def test_un_bot_sin_chats_avisa_de_que_no_contesta_a_nadie():
    piezas = listo.telegram({"telegram": {"token": "1:A"}}, pedir=_telegram())
    assert piezas[0]["estado"] == listo.AVISO


# ------------------------------------------------------------------ Sofascore

CUOTAS = {"markets": [
    {"marketName": "Full time", "sourceId": 1, "choices": [
        {"name": "1", "fractionalValue": "5/4"}, {"name": "X", "fractionalValue": "12/5"},
        {"name": "2", "fractionalValue": "11/5"}]},
    {"marketName": "Correct score", "sourceId": 1, "choices": [
        {"name": "1:0", "fractionalValue": "6/1"}, {"name": "0:0", "fractionalValue": "8/1"},
        {"name": "Any other", "fractionalValue": "5/2"}]},
]}


class Cliente:
    def __init__(self, cuotas=CUOTAS, caido=False, temporadas=True):
        self.cuotas, self.caido, self.temporadas = cuotas, caido, temporadas

    def scheduled_events(self, fecha):
        if self.caido:
            raise SofascoreError("403")
        return [{"id": 1, "status": {"type": "notstarted"}},
                {"id": 2, "status": {"type": "finished"}}]

    def section(self, seccion, event_id, ttl=None):
        if seccion != "odds":
            raise SofascoreError("404")
        return self.cuotas

    def seasons(self, liga_id):
        if not self.temporadas:
            raise SofascoreError("404 en /seasons")
        return [{"id": 99, "year": "25/26"}]

    def season_events(self, liga_id, temporada, pagina):
        return [{"id": n} for n in range(30)]


def test_sofascore_dice_que_mercados_trae_y_si_hay_marcador_exacto(base):
    piezas = listo.sofascore(Cliente(), base)
    cuotas = next(p for p in piezas if p["nombre"] == "Cuotas de Sofascore")
    assert cuotas["estado"] == listo.OK
    assert "marcador" in cuotas["mercados"] and "1x2" in cuotas["mercados"]
    temporadas = next(p for p in piezas if p["nombre"].startswith("Temporadas"))
    assert temporadas["estado"] == listo.OK and "30 partidos" in temporadas["detalle"]


def test_sin_marcador_exacto_en_sofascore_manda_a_betfair(base):
    solo_1x2 = {"markets": CUOTAS["markets"][:1]}
    piezas = listo.sofascore(Cliente(cuotas=solo_1x2), base)
    cuotas = next(p for p in piezas if p["nombre"] == "Cuotas de Sofascore")
    assert cuotas["estado"] == listo.AVISO and "Betfair" in cuotas["arreglo"]


def test_sofascore_caido_para_ahi_y_dice_a_donde_mirar(base):
    piezas = listo.sofascore(Cliente(caido=True), base)
    assert len(piezas) == 1 and piezas[0]["estado"] == listo.MAL
    assert "doctor" in piezas[0]["arreglo"]


def test_sin_el_recorrido_de_temporadas_historia_no_puede_funcionar(base):
    piezas = listo.sofascore(Cliente(temporadas=False), base)
    temporadas = next(p for p in piezas if p["nombre"].startswith("Temporadas"))
    assert temporadas["estado"] == listo.MAL


# ------------------------------------------------------------ casas y resto

def test_sin_claves_las_casas_estan_sin_configurar_no_rotas():
    piezas = listo.casas({"cuotas": {}})
    assert {p["estado"] for p in piezas} == {listo.APAGADO}
    assert listo.nube({})["estado"] == listo.APAGADO


def test_sin_backtest_se_avisa_de_que_los_picks_no_estan_validados(base):
    piezas = listo.estado(base)
    backtest = next(p for p in piezas if p["nombre"] == "Backtest")
    assert backtest["estado"] == listo.AVISO and "sin validar" in backtest["detalle"]


def test_con_un_backtest_que_no_aporta_se_dice_que_no_hay_picks(base):
    import json

    base.anotar("mezcla", json.dumps({"peso": 0.0, "veredicto": "no se distingue",
                                      "partidos": 400}))
    backtest = next(p for p in listo.estado(base) if p["nombre"] == "Backtest")
    assert backtest["estado"] == listo.AVISO and "no hay picks" in backtest["arreglo"]


def test_sin_red_no_se_toca_nada_de_fuera_y_se_dice(base):
    datos = listo.comprobar(base, None, {}, con_red=False)
    nombres = [p["nombre"] for p in datos["piezas"]]
    assert nombres == ["Memoria", "Guardia", "Backtest"]
    assert datos["listo"] and "--sin-red" in listo.texto(datos)[-1]


def test_una_pieza_que_revienta_no_para_las_demas(base, monkeypatch):
    monkeypatch.setattr(listo, "sofascore", lambda *a: 1 / 0)
    monkeypatch.setattr(listo, "ollama", lambda *a: [])
    monkeypatch.setattr(listo, "telegram", lambda *a: [])
    monkeypatch.setattr(listo, "casas", lambda *a: [])
    datos = listo.comprobar(base, None, {}, con_red=True)
    assert not datos["listo"] and datos["malas"] == 1
    assert datos["piezas"][-1]["nombre"] == "Backtest"


def test_el_resumen_no_dice_todo_listo_si_hay_avisos(base):
    """«Todo listo» con la memoria vacía y sin backtest era mentira."""
    datos = listo.comprobar(base, None, {}, con_red=False)
    assert "Todo listo" not in listo.texto(datos)[-1]
    assert "avisos" in listo.texto(datos)[-1]
