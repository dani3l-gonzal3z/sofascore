"""Modelos y catálogo de secciones."""

import pytest

from sofascore.endpoints import (
    ALL_SECTIONS,
    DEFAULT_SECTIONS,
    SECTIONS,
    get_section,
    resolve_sections,
)
from sofascore.models import Event, Player, Score, Team

from conftest import cargar


def test_evento_completo():
    evento = Event.from_api(cargar("event"))
    assert evento.id == 11352550
    assert evento.tournament == "LaLiga"
    assert evento.unique_tournament_id == 8
    assert evento.season_id == 52376
    assert evento.round == 11
    assert evento.venue == "Estadio Santiago Bernabéu"
    assert evento.referee == "César Soto Grado"
    assert evento.date == "2024-10-26"
    assert evento.scoreline == "0 - 4"
    assert evento.winner() == "away"
    assert evento.is_finished and not evento.is_live
    assert str(evento.id) in evento.url


def test_evento_vacio_no_revienta():
    evento = Event.from_api({})
    assert evento.id == 0
    assert evento.kickoff is None
    assert evento.date == ""
    assert evento.winner() == ""
    assert "equipo#None" in evento.label


def test_equipo_y_marcador():
    equipo = Team.from_api({"id": 1, "name": "Betis", "country": {"name": "Spain"}})
    assert equipo.country == "Spain"
    assert str(equipo) == "Betis"
    assert str(Score.from_api({"current": 2})) == "2"
    assert str(Score.from_api(None)) == "-"


def test_jugador_desde_alineacion():
    entrada = cargar("lineups")["home"]["players"][1]
    jugador = Player.from_api(entrada, team_id=2829)
    assert jugador.name == "Vinícius Júnior"
    assert jugador.shirt_number == 7
    assert jugador.team_id == 2829
    assert not jugador.substitute


def test_jugador_con_dorsal_raro():
    assert Player.from_api({"player": {"id": 1, "jerseyNumber": "-"}}).shirt_number is None


def test_to_dict_del_evento():
    datos = Event.from_api(cargar("event")).to_dict()
    assert datos["away"]["score"] == 4
    assert datos["kickoff_utc"].startswith("2024-10-26")


def test_catalogo_coherente():
    assert set(DEFAULT_SECTIONS) <= set(ALL_SECTIONS)
    assert "event" in SECTIONS
    for seccion in SECTIONS.values():
        assert seccion.description
        assert seccion.path.startswith("/")
        assert seccion.scope in {"public", "plus"}


def test_get_section_desconocida():
    with pytest.raises(KeyError) as error:
        get_section("inventada")
    assert "Disponibles" in str(error.value)


def test_resolve_sections_siempre_incluye_event():
    for eleccion in (None, ["statistics"], ["all"]):
        assert resolve_sections(eleccion)[0].name == "event"


def test_resolve_sections_sin_plus():
    elegidas = resolve_sections(["all"], include_plus=False)
    assert not any(s.requires_plus for s in elegidas)


def test_url_de_la_seccion():
    seccion = get_section("statistics")
    assert seccion.url_path(42) == "/event/42/statistics"
    assert get_section("heatmaps").url_path(42, player_id=7) == "/event/42/player/7/heatmap"
