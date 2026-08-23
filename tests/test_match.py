"""Construcción del informe del partido."""

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.match import EMPTY, OK, PLUS_REQUIRED, UNAVAILABLE, build_report
from sofascore.transport import FakeTransport

from conftest import EVENT_ID, rutas_por_defecto


def _cliente(rutas, **extra):
    return SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=60, **extra),
        transport=FakeTransport(rutas),
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )


def test_informe_por_defecto(cliente):
    informe = build_report(cliente, EVENT_ID)
    assert informe.event.id == EVENT_ID
    assert "statistics" in informe.available()
    assert "lineups" in informe.available()
    assert informe["incidents"]


def test_una_seccion_que_falla_no_tumba_el_informe():
    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/lineups"] = 404
    informe = build_report(_cliente(rutas), EVENT_ID)
    assert informe.sections["lineups"].status == UNAVAILABLE
    assert "statistics" in informe.available()


def test_seccion_vacia_se_marca_como_empty():
    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/incidents"] = {"incidents": []}
    informe = build_report(_cliente(rutas), EVENT_ID)
    assert informe.sections["incidents"].status == EMPTY
    assert "incidents" in informe.empty()


def test_sin_credenciales_las_secciones_plus_quedan_bloqueadas():
    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/shotmap"] = 403
    informe = build_report(_cliente(rutas), EVENT_ID)
    assert informe.sections["shotmap"].status == PLUS_REQUIRED
    assert "shotmap" in informe.locked()
    assert "nota_plus" in informe.meta


def test_no_plus_ni_lo_intenta():
    espia = FakeTransport(rutas_por_defecto())
    cli = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=60), transport=espia,
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    informe = build_report(cli, EVENT_ID, include_plus=False)
    assert "shotmap" not in informe.sections
    assert not any("shotmap" in url for url in espia.calls)


def test_con_credenciales_la_seccion_plus_llega():
    cli = _cliente(rutas_por_defecto(), plus_cookie="sesion=mia")
    informe = build_report(cli, EVENT_ID, sections=["shotmap"])
    assert informe.sections["shotmap"].status == OK
    assert informe["shotmap"][0]["xg"] == 0.34
    assert informe.meta["credenciales_plus"] is True


def test_secciones_por_jugador_traen_las_alineaciones_antes():
    rutas = rutas_por_defecto()
    rutas["/player/"] = {"statistics": {"rating": 8.8}}
    cli = _cliente(rutas, plus_cookie="sesion=mia")
    informe = build_report(cli, EVENT_ID, sections=["player_statistics"], max_players=2)
    assert informe.sections["lineups"].status == OK
    datos = informe["player_statistics"]
    assert len(datos) == 2
    assert all("nombre" in v for v in datos.values())


def test_standings_necesita_competicion_y_temporada():
    rutas = rutas_por_defecto()
    rutas["/unique-tournament/8/season/52376/standings/total"] = {"standings": [{"rows": []}]}
    informe = build_report(_cliente(rutas), EVENT_ID, sections=["standings"])
    assert informe.sections["standings"].status == OK


def test_atajos_del_informe(cliente):
    informe = build_report(cliente, EVENT_ID)
    goles = informe.goals()
    assert len(goles) == 3
    assert goles[0]["time"] == 54
    assert [j.name for j in informe.players()][:1] == ["Thibaut Courtois"]
    assert informe.statistic("ballPossession")["home"] == "56%"
    assert informe.statistic("ballPossession", periodo="1ST")["home"] == "58%"
    assert informe.statistic("noExiste") is None
    assert informe.get("noExiste", "por defecto") == "por defecto"
    assert "statistics" in informe


def test_todas_las_secciones(cliente):
    informe = build_report(cliente, EVENT_ID, sections=["all"])
    assert len(informe.sections) > 10
    assert informe.to_dict()["resumen"]["disponibles"]


def test_resumen_legible(cliente):
    resumen = build_report(cliente, EVENT_ID).summary()
    assert "Real Madrid" in resumen
    assert "statistics" in resumen
