"""Utilidades comunes a los tests: todo offline, con respuestas de ejemplo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from cancha.cache import MemoryCache  # noqa: E402
from cancha.client import SofascoreClient  # noqa: E402
from cancha.config import Settings  # noqa: E402
from cancha.transport import FakeTransport  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
EVENT_ID = 11352550


def cargar(nombre: str) -> dict:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def rutas_por_defecto() -> dict:
    """Mapa fragmento-de-URL → carga útil, con el partido de ejemplo."""
    return {
        f"/event/{EVENT_ID}/statistics": cargar("statistics"),
        f"/event/{EVENT_ID}/lineups": cargar("lineups"),
        f"/event/{EVENT_ID}/incidents": cargar("incidents"),
        f"/event/{EVENT_ID}/graph": cargar("graph"),
        f"/event/{EVENT_ID}/shotmap": cargar("shotmap"),
        f"/event/{EVENT_ID}/best-players/summary": {"bestHomeTeamPlayer": {"value": "6.4"}},
        f"/event/{EVENT_ID}/managers": {"homeManager": {"name": "Carlo Ancelotti"}},
        f"/event/{EVENT_ID}/h2h": {"teamDuel": {"homeWins": 5, "awayWins": 4, "draws": 1}},
        f"/event/{EVENT_ID}/pregame-form": {"homeTeam": {"position": 1, "form": ["W", "W", "D"]}},
        f"/event/{EVENT_ID}/average-positions": {"home": [], "away": []},
        "/event/OR/h2h/events": cargar("team_events"),
        f"/event/{EVENT_ID}": cargar("event"),
        "/search/all": cargar("search"),
        "/team/2829/events/last/0": cargar("team_events"),
        "/team/2829/events/next/0": {"events": []},
        # --- equipos, jugadores y competiciones ---
        "/team/2829": cargar("team"),
        "/team/2829/players": cargar("team_players"),
        "/team/2829/performance": {"events": [{"winner": 1}]},
        "/player/831993": cargar("player"),
        "/player/831993/attribute-overviews": cargar("player_attributes"),
        "/player/831993/statistics/seasons": cargar("player_seasons"),
        "/player/831993/unique-tournament/8/season/61643/statistics/overall": {
            "statistics": {"rating": 7.8, "goals": 24, "assists": 11, "appearances": 38}
        },
        "/player/831993/last-year-summary": {"summary": [{"rating": 7.9}]},
        "/player/831993/transfer-history": {"transferHistory": []},
        "/unique-tournament/8": {"uniqueTournament": {"id": 8, "name": "LaLiga"}},
        "/unique-tournament/8/seasons": cargar("seasons"),
        "/unique-tournament/8/season/61643/standings/total": cargar("standings"),
        # También la temporada anterior: sin esta, el transporte falso caía a
        # "/unique-tournament/8" y servía la ficha como si fuera la tabla.
        "/unique-tournament/8/season/52376/standings/total": cargar("standings"),
        "/unique-tournament/8/season/61643/rounds": {"rounds": [{"round": 12}]},
        "/unique-tournament/8/season/61643/top-players/overall": {"topPlayers": {}},
        "/unique-tournament/8/season/61643/events/last/0": cargar("team_events"),
        "/sport/football/events/live": cargar("team_events"),
        "/sport/football/scheduled-events/2024-10-26": cargar("team_events"),
    }


@pytest.fixture
def transporte() -> FakeTransport:
    return FakeTransport(rutas_por_defecto())


@pytest.fixture
def ajustes(tmp_path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", cache_ttl=60, rate_limit=0, retries=1)


@pytest.fixture
def cliente(transporte, ajustes) -> SofascoreClient:
    return SofascoreClient(
        ajustes, transport=transporte, cache=MemoryCache(), sleep=lambda _s: None
    )
