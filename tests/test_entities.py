"""Informes de equipo, jugador y competición."""

from __future__ import annotations

import pytest
from conftest import rutas_por_defecto

from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.entities import (
    build_player_report,
    build_team_report,
    build_tournament_report,
    find_entity,
)
from cancha.errors import MatchNotFound
from cancha.report import UNAVAILABLE
from cancha.transport import FakeTransport


@pytest.fixture
def cliente(tmp_path):
    ajustes = Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0, concurrency=2)
    return SofascoreClient(
        ajustes,
        transport=FakeTransport(rutas_por_defecto()),
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )


def test_encuentra_equipo_por_nombre(cliente):
    assert find_entity(cliente, "Real Madrid", "team")["id"] == 2829


def test_encuentra_jugador_por_nombre(cliente):
    assert find_entity(cliente, "Vinicius", "player")["id"] == 831993


def test_un_id_no_necesita_buscador(cliente):
    assert find_entity(cliente, 2829, "team") == {"id": 2829, "name": ""}
    assert not cliente.stats.requests


def test_liga_conocida_sin_pasar_por_el_buscador(cliente):
    assert find_entity(cliente, "laliga", "tournament")["id"] == 8
    assert not cliente.stats.requests


def test_el_nombre_de_la_liga_sale_de_la_ficha_no_del_alias(cliente):
    """Escribes "laliga" y el informe dice "LaLiga": el nombre lo pone la API."""
    assert build_tournament_report(cliente, "laliga").name == "LaLiga"


def test_entidad_inexistente(cliente):
    with pytest.raises(MatchNotFound):
        find_entity(cliente, "equipo que no existe", "team")


def test_tipo_invalido(cliente):
    with pytest.raises(ValueError):
        find_entity(cliente, "algo", "arbitro")


def test_informe_de_equipo(cliente):
    informe = build_team_report(cliente, "Real Madrid")
    assert informe.kind == "team"
    assert informe.entity_id == 2829
    assert informe.profile["name"] == "Real Madrid"
    assert "players" in informe.available()
    assert "equipo: Real Madrid" in informe.summary()


def test_informe_de_jugador(cliente):
    informe = build_player_report(cliente, "Vinicius")
    assert informe.profile["name"] == "Vinicius Junior"
    assert informe.get("attributes")["averageAttributeOverviews"][0]["attacking"] == 92


def test_informe_de_liga_usa_la_temporada_en_curso(cliente):
    informe = build_tournament_report(cliente, "laliga")
    assert informe.meta["contexto"]["season_id"] == 61643
    tabla = informe.get("standings")
    assert tabla[0]["rows"][0]["team"]["name"] == "Barcelona"


def test_liga_con_temporada_explicita(cliente):
    informe = build_tournament_report(cliente, 8, season_id=61643, sections=["standings"])
    assert informe.get("standings")


def test_seccion_sin_temporada_se_marca_no_disponible(cliente):
    # Sin temporada, la clasificación no se puede ni pedir: se dice, no se rompe.
    informe = build_tournament_report(cliente, 8, season_id=0, sections=["profile", "standings"])
    assert informe.sections["standings"].status == UNAVAILABLE
    assert "season_id" in informe.sections["standings"].error
    assert "profile" in informe.available()


def test_informe_de_equipo_se_serializa(cliente):
    datos = build_team_report(cliente, 2829).to_dict()
    assert datos["tipo"] == "team"
    assert datos["resumen"]["disponibles"]


# ---------------- estadísticas de temporada: los ids salen del propio informe

def test_las_estadisticas_de_temporada_se_piden_solas(cliente):
    """No sabes de antemano la liga ni la temporada: se sacan del índice."""
    informe = build_player_report(cliente, "Vinicius", sections=["all"])
    assert informe.sections["season_statistics"].status == "ok"
    assert informe.get("season_statistics")["statistics"]["goals"] == 24
    assert informe.meta["contexto"]["tournament_id"] == 8
    assert informe.meta["contexto"]["season_id"] == 61643


def test_se_coge_la_temporada_mas_reciente_de_la_liga_principal(cliente):
    from conftest import cargar

    from cancha.entities import temporada_mas_reciente

    assert temporada_mas_reciente(cargar("player_seasons")) == {
        "tournament_id": 8, "season_id": 61643,
    }


@pytest.mark.parametrize("indice", [None, {}, [], "vaya", {"uniqueTournamentSeasons": []},
                                    {"uniqueTournamentSeasons": [{"seasons": []}]},
                                    {"uniqueTournamentSeasons": [{"uniqueTournament": {}}]}])
def test_un_indice_con_otra_forma_no_revienta(indice):
    from cancha.entities import temporada_mas_reciente

    assert temporada_mas_reciente(indice) == {}


def test_sin_indice_la_seccion_sigue_quedando_no_disponible(tmp_path):
    from conftest import rutas_por_defecto

    rutas = rutas_por_defecto()
    rutas["/player/831993/statistics/seasons"] = {"uniqueTournamentSeasons": []}
    cli = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas), cache=MemoryCache(), sleep=lambda _s: None,
    )
    informe = build_player_report(cli, 831993, sections=["all"])
    assert informe.sections["season_statistics"].status == UNAVAILABLE


def test_la_segunda_tanda_no_se_lanza_si_no_hace_falta(cliente):
    """Sin pedir season_statistics, no se deduce nada ni se pide de más."""
    informe = build_player_report(cliente, "Vinicius", sections=["profile"])
    assert "season_statistics" not in informe.sections
    assert not any("statistics/overall" in url for url in cliente.transport.calls)


# ------------------------------------------------- fechas que rompen en Windows

def _con_momento(momento):
    from cancha.models import Event

    return Event.from_api({"id": 1, "startTimestamp": momento, "homeTeam": {},
                           "awayTeam": {}, "homeScore": {}, "awayScore": {},
                           "status": {}})


def test_un_partido_anterior_a_1970_tiene_fecha():
    """`datetime.fromtimestamp` revienta en Windows con fechas negativas.

    Y no es un caso raro: el historial entre dos equipos trae partidos de los
    años veinte, así que abrir un clásico tumbaba la petición entera en
    Windows mientras en Linux funcionaba. Por eso se suma desde la época a
    mano: aritmética pura, igual en todas partes.
    """
    assert _con_momento(-1_293_840_000).date == "1929-01-01"
    assert _con_momento(-1).date == "1969-12-31"


def test_una_fecha_absurda_no_revienta_devuelve_nada():
    """Un partido sin fecha legible es eso, no una excepción a media página."""
    assert _con_momento(99_999_999_999_999).date == ""
    assert _con_momento(99_999_999_999_999).kickoff is None
    # En milisegundos, que alguna fuente los manda así.
    assert _con_momento(1_729_972_800_000).kickoff is None


def test_sin_momento_no_hay_fecha():
    assert _con_momento(None).kickoff is None
    assert _con_momento(0).date == ""


def test_una_fecha_normal_sigue_saliendo_bien():
    momento = _con_momento(1_729_972_800).kickoff
    assert momento is not None
    assert momento.year == 2024 and momento.month == 10 and momento.day == 26
    assert momento.tzinfo is not None, "tiene que llevar zona horaria"


def test_no_se_llama_a_fromtimestamp_en_ninguna_parte():
    """Es la llamada que depende del sistema operativo; que no vuelva a colarse.

    Busca la llamada, no la palabra: en `models.py` se menciona a propósito,
    en el comentario que explica por qué no se usa.
    """
    import re
    from pathlib import Path

    llamada = re.compile(r"\.fromtimestamp\s*\(")
    raiz = Path(__file__).resolve().parents[1] / "cancha"
    culpables = [f.name for f in raiz.rglob("*.py")
                 if llamada.search(f.read_text(encoding="utf-8"))]
    assert culpables == [], f"vuelve a llamarse a fromtimestamp en: {culpables}"
