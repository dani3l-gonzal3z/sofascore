"""Resolución de la consulta a un partido concreto."""

import pytest
from conftest import EVENT_ID

from sofascore.errors import MatchNotFound
from sofascore.resolve import normalizar, parecido, parse_event_id, resolve_event, split_teams


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("11352550", 11352550),
        ("https://www.sofascore.com/football/match/real-madrid-barcelona/OR#id:11352550", 11352550),
        ("https://www.sofascore.com/es/football/partido/x/OR,id:11352550", 11352550),
        ("/event/11352550/statistics", 11352550),
        ("Real Madrid vs Barcelona", None),
        ("", None),
    ],
)
def test_parse_event_id(texto, esperado):
    assert parse_event_id(texto) == esperado


@pytest.mark.parametrize(
    "consulta, esperado",
    [
        ("Real Madrid vs Barcelona", ("Real Madrid", "Barcelona")),
        ("Betis - Sevilla", ("Betis", "Sevilla")),
        ("Atlético x Getafe", ("Atlético", "Getafe")),
        ("Girona contra Osasuna", ("Girona", "Osasuna")),
        ("Barcelona", None),
    ],
)
def test_split_teams(consulta, esperado):
    assert split_teams(consulta) == esperado


def test_normalizar_quita_acentos_y_puntuacion():
    assert normalizar("Atlético de Madrid!") == "atletico de madrid"


def test_parecido_tolera_variantes():
    assert parecido("FC Barcelona", "Barcelona") > 0.8
    assert parecido("Real Madrid", "Barcelona") < 0.5


def test_resuelve_por_id(cliente):
    resolucion = resolve_event(cliente, EVENT_ID)
    assert resolucion.event_id == EVENT_ID
    assert resolucion.source == "id"


def test_resuelve_por_url(cliente):
    url = f"https://www.sofascore.com/football/match/real-madrid-barcelona/OR#id:{EVENT_ID}"
    assert resolve_event(cliente, url).event_id == EVENT_ID


def test_resuelve_por_nombres(cliente):
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona")
    assert resolucion.event_id == EVENT_ID
    assert resolucion.candidates[0].score >= 0.9


def test_resuelve_con_los_equipos_al_reves(cliente):
    resolucion = resolve_event(cliente, "Barcelona vs Real Madrid")
    assert resolucion.event_id == EVENT_ID


def test_la_fecha_correcta_puntua_mas(cliente):
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona", date="2024-10-26")
    assert resolucion.event_id == EVENT_ID
    assert resolucion.candidates[0].score > 1.0


def test_fecha_equivocada_descarta(cliente):
    with pytest.raises(MatchNotFound):
        resolve_event(cliente, "Real Madrid vs Barcelona", date="1999-01-01", min_score=1.0)


def test_sin_resultados_lanza_matchnotfound(transporte, ajustes):
    from sofascore.cache import MemoryCache
    from sofascore.client import SofascoreClient
    from sofascore.transport import FakeTransport

    vacio = SofascoreClient(
        ajustes,
        transport=FakeTransport({"/search/all": {"results": []}}),
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    with pytest.raises(MatchNotFound):
        resolve_event(vacio, "Equipo Inventado vs Otro Inventado")


def test_consulta_vacia(cliente):
    with pytest.raises(MatchNotFound):
        resolve_event(cliente, "   ")
