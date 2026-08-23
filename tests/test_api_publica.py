"""La API de una línea: get_match / search_matches."""

import sofascore

from conftest import EVENT_ID


def test_get_match_con_cliente_inyectado(cliente):
    informe = sofascore.get_match("Real Madrid vs Barcelona", date="2024-10-26", client=cliente)
    assert informe.event.id == EVENT_ID
    assert informe.meta["resolucion"]["consulta"] == "Real Madrid vs Barcelona"
    assert informe.meta["peticiones"]["peticiones"] > 0
    assert informe.statistic("expectedGoals")["away"] == "2.87"


def test_get_match_con_seccion_concreta(cliente):
    informe = sofascore.get_match(EVENT_ID, sections=["incidents"], client=cliente)
    assert set(informe.sections) == {"event", "incidents"}
    assert len(informe.goals()) == 3


def test_search_matches(cliente):
    candidatos = sofascore.search_matches("Real Madrid vs Barcelona", client=cliente)
    assert candidatos[0].event.id == EVENT_ID
    assert "Real Madrid" in str(candidatos[0])


def test_el_cliente_inyectado_no_se_cierra(cliente):
    sofascore.get_match(EVENT_ID, client=cliente)
    assert cliente.event(EVENT_ID).id == EVENT_ID  # sigue vivo


def test_exportaciones_del_paquete():
    for nombre in sofascore.__all__:
        assert hasattr(sofascore, nombre), nombre
