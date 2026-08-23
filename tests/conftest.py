"""Utilidades comunes a los tests: todo offline, con respuestas de ejemplo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from sofascore.cache import MemoryCache  # noqa: E402
from sofascore.client import SofascoreClient  # noqa: E402
from sofascore.config import Settings  # noqa: E402
from sofascore.transport import FakeTransport  # noqa: E402

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
        f"/event/{EVENT_ID}": cargar("event"),
        "/search/all": cargar("search"),
        "/team/2829/events/last/0": cargar("team_events"),
        "/team/2829/events/next/0": {"events": []},
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
