"""Cuotas de fuera: Betfair y The Odds API, emparejadas con nuestros partidos.

Sin red: las respuestas se fabrican con la forma que documentan las dos APIs. Lo
que más se mira es el emparejado, porque es donde esto puede hacer daño de
verdad: pegarle a un partido las cuotas de otro envenenaría el registro sin que
nadie se enterase.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cancha.almacen import Almacen
from cancha.sources.casas import (
    Betfair,
    CasaNoDisponible,
    TheOddsApi,
    emparejar,
    guardar_partidos,
    parecido,
    precio_justo,
)

SAQUE = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        for pid, local, visitante in ((1, "Girona FC", "CA Osasuna"),
                                      (2, "Real Madrid", "Getafe CF"),
                                      (3, "Atlético de Madrid", "Sevilla FC")):
            almacen._conexion.execute(
                "INSERT INTO partidos (id, local, visitante, momento) VALUES (?,?,?,?)",
                (pid, local, visitante, SAQUE))
        almacen._conexion.commit()
        yield almacen


# ------------------------------------------------------------------ nombres

@pytest.mark.parametrize("uno,otro", [
    ("Girona FC", "Girona"), ("CA Osasuna", "Osasuna"),
    ("Athletic Club", "Athletic Bilbao"), ("Atlético de Madrid", "Atletico Madrid"),
])
def test_el_mismo_equipo_escrito_distinto_se_reconoce(uno, otro):
    assert parecido(uno, otro) >= 0.72


def test_real_madrid_y_atletico_no_son_el_mismo_equipo():
    """Quitando «real» y «atlético» como si fueran ruido, los dos eran «madrid»."""
    assert parecido("Real Madrid", "Atlético de Madrid") < 0.72


def test_se_empareja_el_partido_de_los_dos_equipos(base):
    assert emparejar(base, "Girona", "Osasuna", SAQUE + 600) == 1
    assert emparejar(base, "Atletico Madrid", "Sevilla", SAQUE) == 3


def test_a_la_misma_hora_no_se_confunden_dos_partidos(base):
    """Real Madrid - Getafe y Atlético - Sevilla a la vez: los dos tienen «Madrid»."""
    assert emparejar(base, "Real Madrid", "Getafe", SAQUE) == 2


def test_si_no_se_parece_a_nada_no_se_empareja(base):
    """Mejor sin cuotas que con las de otro partido."""
    assert emparejar(base, "Girona", "Barcelona", SAQUE) is None
    assert emparejar(base, "Girona", "Osasuna", SAQUE + 10 * 3600) is None, "otra hora"


# --------------------------------------------------------------- el precio

def test_el_precio_justo_es_el_punto_medio_de_la_bolsa():
    runner = {"ex": {"availableToBack": [{"price": 7.0}],
                     "availableToLay": [{"price": 7.4}]}}
    assert precio_justo(runner) == 7.2


def test_con_la_bolsa_muy_abierta_se_usa_el_ultimo_cruzado():
    """Entre 7 y 15 el medio no significa nada: no hay dinero ahí."""
    runner = {"lastPriceTraded": 8.2,
              "ex": {"availableToBack": [{"price": 7.0}],
                     "availableToLay": [{"price": 15.0}]}}
    assert precio_justo(runner) == 8.2


# ------------------------------------------------------------------ Betfair

class FalsoBetfair:
    """Contesta como Betfair: login, catálogo y libro de precios."""

    def __init__(self):
        self.llamadas = []

    def __call__(self, url, cuerpo=None, cabeceras=None, formulario=False):
        self.llamadas.append(url)
        if url.endswith("/api/login"):
            return {"token": "sesion-1", "status": "SUCCESS", "error": ""}
        metodo = cuerpo["method"].rsplit("/", 1)[-1]
        if metodo == "listMarketCatalogue":
            return {"result": [
                {"marketId": "1.1", "marketStartTime": "2026-09-26T19:00:00.000Z",
                 "description": {"marketType": "CORRECT_SCORE"},
                 "event": {"id": "E1", "name": "Girona v Osasuna"},
                 "runners": [{"selectionId": 10, "runnerName": "1 - 0"},
                             {"selectionId": 11, "runnerName": "1 - 1"},
                             {"selectionId": 12, "runnerName": "0 - 0"},
                             {"selectionId": 13, "runnerName": "Any Other Home Win"}]},
                {"marketId": "1.2", "marketStartTime": "2026-09-26T19:00:00.000Z",
                 "description": {"marketType": "MATCH_ODDS"},
                 "event": {"id": "E1", "name": "Girona v Osasuna"},
                 "runners": [{"selectionId": 20, "runnerName": "Girona"},
                             {"selectionId": 21, "runnerName": "Osasuna"},
                             {"selectionId": 22, "runnerName": "The Draw"}]}]}
        if metodo == "listMarketBook":
            def r(sid, back, lay):
                return {"selectionId": sid, "status": "ACTIVE",
                        "ex": {"availableToBack": [{"price": back}],
                               "availableToLay": [{"price": lay}]}}
            return {"result": [
                {"marketId": "1.1", "status": "OPEN", "runners": [
                    r(10, 7.0, 7.2), r(11, 6.2, 6.4), r(12, 9.0, 9.4), r(13, 3.5, 3.6)]},
                {"marketId": "1.2", "status": "OPEN", "runners": [
                    r(20, 2.1, 2.12), r(21, 3.8, 3.85), r(22, 3.4, 3.45)]}]}
        raise AssertionError(metodo)


def test_sin_claves_betfair_dice_que_hace_falta():
    with pytest.raises(CasaNoDisponible, match="developer.betfair.com"):
        Betfair("", "", "")


def test_betfair_trae_el_marcador_exacto_y_el_1x2():
    casa = Betfair("app", "yo", "clave", pedir=FalsoBetfair())
    partidos = casa.partidos(datetime(2026, 9, 26, tzinfo=timezone.utc),
                             datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert len(partidos) == 1
    uno = partidos[0]
    assert (uno["local"], uno["visitante"]) == ("Girona", "Osasuna")
    selecciones = {(f["mercado"], f["seleccion"]) for f in uno["filas"]}
    assert ("marcador", "1-0") in selecciones
    assert ("marcador", "otro_local") in selecciones, "«Any Other Home Win»"
    assert {("1x2", "local"), ("1x2", "visitante"), ("1x2", "empate")} <= selecciones
    assert all(f["casa"] == "betfair-exchange" for f in uno["filas"])


def test_una_cuenta_espanola_entra_por_su_dominio():
    """Con una cuenta .es por el .com, el acceso falla sin más explicación."""
    falso = FalsoBetfair()
    Betfair("app", "yo", "clave", jurisdiccion="es", pedir=falso).entrar()
    assert falso.llamadas[0].startswith("https://identitysso.betfair.es")


def test_un_login_rechazado_se_explica():
    def no(url, *a, **k):
        return {"status": "FAIL", "error": "INVALID_USERNAME_OR_PASSWORD"}

    with pytest.raises(CasaNoDisponible, match="INVALID_USERNAME"):
        Betfair("app", "yo", "mal", pedir=no).entrar()


def test_betfair_llega_al_registro_con_su_marcador_exacto(base):
    from cancha.registro import precios_del_mercado

    casa = Betfair("app", "yo", "clave", pedir=FalsoBetfair())
    partidos = casa.partidos(datetime(2026, 9, 26, tzinfo=timezone.utc),
                             datetime(2026, 9, 27, tzinfo=timezone.utc))
    salida = guardar_partidos(base, "betfair", partidos)
    assert salida["emparejados"] == 1
    precios = precios_del_mercado(base, 1)
    assert ("marcador_exacto", "1-0") in precios
    assert ("marcador_exacto", "otro") in precios, "los tres «any other» juntos"


# ------------------------------------------------------------- The Odds API

EVENTO_ODDS_API = {
    "home_team": "Girona", "away_team": "Osasuna", "commence_time": SAQUE,
    "bookmakers": [
        {"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Girona", "price": 2.05},
                                        {"name": "Osasuna", "price": 3.7},
                                        {"name": "Draw", "price": 3.4}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5},
                                           {"name": "Under", "price": 1.95, "point": 2.5}]}]},
        {"key": "pinnacle", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Girona", "price": 2.12},
                                        {"name": "Osasuna", "price": 3.85},
                                        {"name": "Draw", "price": 3.5}]}]}]}


def test_the_odds_api_separa_cada_casa():
    uno = TheOddsApi._uno(EVENTO_ODDS_API)
    casas = {f["casa"] for f in uno["filas"]}
    assert casas == {"bet365", "pinnacle"}
    goles = [f for f in uno["filas"] if f["mercado"] == "goles"]
    assert {f["linea"] for f in goles} == {"2.5"}


def test_de_varias_casas_el_registro_coge_la_que_menos_cobra(base):
    """La que menos cobra es la más difícil de batir: coger otra sería hacerse
    trampas poniéndose el listón bajo."""
    from cancha.registro import precios_del_mercado

    guardar_partidos(base, "the-odds-api", [TheOddsApi._uno(EVENTO_ODDS_API)])
    filas = base.mercados_de(1, mercado="1x2")
    margenes = {f["casa"]: f["margen"] for f in filas}
    assert margenes["pinnacle"] < margenes["bet365"]
    precios = precios_del_mercado(base, 1)
    pinnacle = next(f["prob"] for f in filas
                    if f["casa"] == "pinnacle" and f["seleccion"] == "local")
    assert precios[("1x2", "local")] == pytest.approx(pinnacle, abs=1e-4)


def test_sin_clave_the_odds_api_dice_que_hace_falta():
    with pytest.raises(CasaNoDisponible, match="the-odds-api.com"):
        TheOddsApi("")


def test_lo_que_no_se_empareja_se_cuenta_y_se_ensena(base):
    otro = dict(EVENTO_ODDS_API, home_team="Leeds", away_team="Burnley")
    salida = guardar_partidos(base, "the-odds-api", [TheOddsApi._uno(otro)])
    assert salida["emparejados"] == 0
    assert salida["sin_pareja"] == ["Leeds - Burnley"]


# ------------------------------------------------------------------ ajustes

def test_las_claves_de_las_casas_no_salen_en_la_pagina():
    from cancha.ajustes import POR_DEFECTO, sin_secretos

    ajustes = {**POR_DEFECTO, "cuotas": {
        "betfair": {"clave_app": "abcdefgh1234", "usuario": "yo",
                    "contrasena": "secreta99", "jurisdiccion": "es"},
        "the_odds_api": {"clave": "k" * 32, "regiones": "eu", "casas": ""}}}
    visibles = sin_secretos(ajustes)["cuotas"]
    assert "secreta" not in str(visibles)
    assert "abcdefgh" not in str(visibles)
    assert visibles["betfair"]["contrasena_puesto"] is True
