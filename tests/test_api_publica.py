"""La API de una línea: get_match / search_matches."""

from conftest import EVENT_ID

import cancha


def test_get_match_con_cliente_inyectado(cliente):
    informe = cancha.get_match("Real Madrid vs Barcelona", date="2024-10-26", client=cliente)
    assert informe.event.id == EVENT_ID
    assert informe.meta["resolucion"]["consulta"] == "Real Madrid vs Barcelona"
    assert informe.meta["peticiones"]["peticiones"] > 0
    assert informe.statistic("expectedGoals")["away"] == "2.87"


def test_get_match_con_seccion_concreta(cliente):
    informe = cancha.get_match(EVENT_ID, sections=["incidents"], client=cliente)
    assert set(informe.sections) == {"event", "incidents"}
    assert len(informe.goals()) == 3


def test_search_matches(cliente):
    candidatos = cancha.search_matches("Real Madrid vs Barcelona", client=cliente)
    assert candidatos[0].event.id == EVENT_ID
    assert "Real Madrid" in str(candidatos[0])


def test_el_cliente_inyectado_no_se_cierra(cliente):
    cancha.get_match(EVENT_ID, client=cliente)
    assert cliente.event(EVENT_ID).id == EVENT_ID  # sigue vivo


def test_exportaciones_del_paquete():
    for nombre in cancha.__all__:
        assert hasattr(cancha, nombre), nombre


def test_la_version_del_paquete_y_la_del_pyproject_no_se_separan():
    """Es fácil subir una y olvidar la otra; que lo diga un test."""
    import re
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    declarada = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert cancha.__version__ == declarada


def test_el_nombre_viejo_sigue_funcionando():
    """Renombrar el paquete no puede romperle los imports a quien ya lo usaba."""
    import sofascore.tools
    from sofascore.sources import ClubElo  # noqa: F401

    import sofascore
    from sofascore import get_match  # noqa: F401

    assert sofascore is cancha
    assert sofascore.tools.TOOLS is cancha.tools.TOOLS
