"""Abastecer un partido: traer su contexto entero y guardarlo.

Lo que se comprueba aquí, por orden de importancia:

1. Que **nunca** entre un partido posterior al que se analiza. Promediar «sus
   últimos diez» con un partido que aún no se había jugado es mirar el futuro,
   y es el error que más fácil se cuela y más difícil se ve.
2. Que la segunda vez no cueste: si costara lo mismo, la memoria no serviría
   de nada.
3. Que antes de pedir se pueda saber cuánto va a costar.
"""

from __future__ import annotations

import pytest

from cancha.abastecer import Plan, abastecer, planear
from cancha.almacen import Almacen
from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.models import Event
from cancha.transport import FakeTransport

#: El partido que se analiza y el instante en que se juega.
OBJETIVO = 500
AHORA = 1_730_000_000
DIA = 86_400
LOCAL, VISITANTE = 2829, 2817


def _evento(identificador: int, local: int, visitante: int, cuando: int,
            estado: str = "finished", arbitro: str = "El Árbitro") -> dict:
    return {
        "id": identificador,
        "customId": f"c{identificador}",
        "startTimestamp": cuando,
        "status": {"type": estado},
        "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
        "season": {"id": 61643},
        "referee": {"name": arbitro},
        "homeTeam": {"id": local, "name": f"Equipo {local}"},
        "awayTeam": {"id": visitante, "name": f"Equipo {visitante}"},
        "homeScore": {"current": 2},
        "awayScore": {"current": 1},
    }


def _secciones(identificador: int) -> dict:
    """Lo mínimo para que `build_report` de un partido no se quede vacío."""
    return {
        f"/event/{identificador}/statistics": {"statistics": [
            {"period": "ALL", "groups": [{"groupName": "G", "statisticsItems": [
                {"key": "expectedGoals", "name": "xG", "home": "1.5", "away": "0.9"}]}]}]},
        f"/event/{identificador}/lineups": {"home": {"players": []}, "away": {"players": []}},
        f"/event/{identificador}/incidents": {"incidents": []},
        f"/event/{identificador}/shotmap": {"shotmap": []},
        f"/event/{identificador}/odds/1/featured": {"featured": {}},
    }


def _mundo(anteriores_local: int = 10, anteriores_visitante: int = 10,
           posteriores: int = 3) -> dict:
    """Una liga de mentira: partidos antes y **después** del que se analiza."""
    rutas: dict = {}
    eventos_local, eventos_visitante = [], []

    for n in range(anteriores_local):
        identificador = 100 + n
        eventos_local.append(_evento(identificador, LOCAL, 3000 + n, AHORA - (n + 1) * DIA))
    for n in range(anteriores_visitante):
        identificador = 200 + n
        eventos_visitante.append(_evento(identificador, VISITANTE, 4000 + n,
                                         AHORA - (n + 1) * DIA))
    # Y unos cuantos posteriores, que es la trampa que hay que no morder.
    for n in range(posteriores):
        eventos_local.append(_evento(900 + n, LOCAL, 3100 + n, AHORA + (n + 1) * DIA))
        eventos_visitante.append(_evento(950 + n, VISITANTE, 4100 + n, AHORA + (n + 1) * DIA))

    objetivo = _evento(OBJETIVO, LOCAL, VISITANTE, AHORA, estado="notstarted")
    rutas[f"/event/{OBJETIVO}"] = objetivo
    rutas[f"/team/{LOCAL}/events/last/0"] = {"events": eventos_local}
    rutas[f"/team/{VISITANTE}/events/last/0"] = {"events": eventos_visitante}
    # Un enfrentamiento entre los dos, anterior.
    rutas[f"/event/c{OBJETIVO}/h2h/events"] = {
        "events": [_evento(300, LOCAL, VISITANTE, AHORA - 400 * DIA)]}
    for evento in eventos_local + eventos_visitante:
        rutas[f"/event/{evento['id']}"] = evento
        rutas.update(_secciones(evento["id"]))
    rutas["/event/300"] = _evento(300, LOCAL, VISITANTE, AHORA - 400 * DIA)
    rutas.update(_secciones(300))
    rutas.update(_secciones(OBJETIVO))
    return rutas


@pytest.fixture
def mundo():
    transporte = FakeTransport(_mundo())
    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, fallback_base_urls=()),
        transport=transporte, cache=MemoryCache(), sleep=lambda _s: None)
    with Almacen(":memory:") as base:
        yield cliente, base, transporte
    cliente.close()


# ------------------------------------------------------- no mirar el futuro

def test_nunca_entra_un_partido_posterior_al_que_se_analiza(mundo):
    """Es el error que más fácil se cuela: promediar con lo que aún no pasó."""
    cliente, base, _ = mundo
    plan = planear(cliente, base, OBJETIVO)
    for evento in plan.todos:
        assert (evento.start_timestamp or 0) < AHORA, (
            f"el partido {evento.id} es posterior al que se analiza")
    # Y los posteriores existían de verdad en la respuesta, no es que no hubiera.
    assert {900, 901, 902} & {e.id for e in plan.todos} == set()


def test_el_propio_partido_no_se_cuenta_como_su_contexto(mundo):
    cliente, base, _ = mundo
    plan = planear(cliente, base, OBJETIVO)
    assert OBJETIVO not in {e.id for e in plan.todos}


def test_un_partido_que_sale_por_dos_sitios_se_cuenta_una_vez():
    """El h2h y el calendario de cada equipo se solapan; contar doble engaña."""
    uno = Event.from_api(_evento(1, LOCAL, VISITANTE, AHORA - DIA))
    otro = Event.from_api(_evento(2, LOCAL, 9, AHORA - 2 * DIA))
    plan = Plan(locales=[uno, otro], visitantes=[uno], entre_ellos=[uno])
    assert sorted(e.id for e in plan.todos) == [1, 2]


# ------------------------------------------------------------- qué va a costar

def test_se_puede_saber_lo_que_costaria_antes_de_pedirlo(mundo):
    cliente, base, transporte = mundo
    peticiones_antes = len(transporte.calls)
    cuentas = planear(cliente, base, OBJETIVO).cuentas(base)
    assert cuentas["en_total"] == cuentas["hay_que_pedir"], "la memoria está vacía"
    assert cuentas["ya_estaban"] == 0
    assert cuentas["peticiones_estimadas"] == cuentas["hay_que_pedir"] * 6
    assert cuentas["de_cada_uno"] == {"local": 10, "visitante": 10}
    assert cuentas["entre_ellos"] == 1
    # Planear cuesta poco: los calendarios, no el detalle de cada partido.
    assert len(transporte.calls) - peticiones_antes < cuentas["peticiones_estimadas"]


# --------------------------------------------------------------- traerlo

def test_abastecer_guarda_el_contexto_entero(mundo):
    cliente, base, _ = mundo
    resumen = abastecer(cliente, base, OBJETIVO)
    assert resumen["guardados"] == resumen["en_total"]
    assert resumen["completo"] is True
    assert resumen["fallos"] == 0
    # Y ahora la previa tiene con qué: los dos equipos están medidos.
    guardados = base.consulta("SELECT COUNT(*) n FROM partidos")[0]["n"]
    assert guardados >= resumen["en_total"]
    con_estadisticas = base.consulta(
        "SELECT COUNT(DISTINCT partido_id) n FROM estadisticas")[0]["n"]
    assert con_estadisticas == resumen["en_total"]


def test_la_segunda_vez_no_cuesta(mundo):
    """Si costara lo mismo, la memoria no serviría para nada."""
    cliente, base, _ = mundo
    primera = abastecer(cliente, base, OBJETIVO)
    segunda = abastecer(cliente, base, OBJETIVO)
    assert primera["peticiones"] > 50
    assert segunda["guardados"] == 0
    assert segunda["ya_estaban"] == primera["en_total"]
    assert segunda["peticiones"] < primera["peticiones"] / 5


def test_el_tope_corta_y_se_reanuda(mundo):
    """Cortar por la mitad no rompe nada: lo guardado queda guardado."""
    cliente, base, _ = mundo
    a_medias = abastecer(cliente, base, OBJETIVO, maximo_peticiones=20)
    assert a_medias["completo"] is False
    assert 0 < a_medias["guardados"] < a_medias["en_total"]
    entero = abastecer(cliente, base, OBJETIVO)
    assert entero["completo"] is True
    assert entero["ya_estaban"] == a_medias["guardados"]


def test_sin_arbitro_designado_no_se_rompe(mundo):
    """Un partido de dentro de una semana no tiene árbitro todavía."""
    cliente, base, transporte = mundo
    transporte.add(f"/event/{OBJETIVO}",
                   {**_evento(OBJETIVO, LOCAL, VISITANTE, AHORA, estado="notstarted"),
                    "referee": None})
    cuentas = planear(cliente, base, OBJETIVO).cuentas(base)
    assert cuentas["arbitro"] is None
    assert cuentas["del_arbitro"] == 0
    assert cuentas["en_total"] > 0


def test_los_partidos_del_arbitro_salen_de_la_memoria(mundo):
    """Sofascore no publica «partidos de este árbitro»; se usa lo guardado."""
    cliente, base, _ = mundo
    abastecer(cliente, base, OBJETIVO)          # llena la memoria, con árbitro
    cuentas = planear(cliente, base, OBJETIVO).cuentas(base)
    assert cuentas["arbitro"] == "El Árbitro"
    assert cuentas["del_arbitro"] > 0


def test_la_herramienta_puede_solo_planear(mundo):
    """Para que la IA pueda decir el precio antes de gastarlo."""
    from cancha.herramientas import ejecutar
    from cancha.sesion import Sesion

    cliente, base, transporte = mundo
    sesion = Sesion(cliente=cliente)
    sesion._almacen = base
    salida = ejecutar("abastecer_partido",
                      {"partido": str(OBJETIVO), "solo_plan": True}, sesion=sesion)
    assert salida["hay_que_pedir"] > 0
    assert "peticiones_estimadas" in salida
    # No ha traído el detalle de ningún partido: solo los calendarios.
    assert not any("/statistics" in url for url in transporte.calls)
