"""Sofascore Framework — le dices un partido y te da todos sus datos.

Uso mínimo::

    from sofascore import get_match

    partido = get_match("Real Madrid vs Barcelona", date="2024-10-26")
    print(partido.event.label)
    print(partido.statistic("ballPossession"))
    print(partido.available())   # secciones con datos
    print(partido.locked())      # secciones que requieren Sofascore Plus

Si tienes Sofascore Plus, pon tus propias credenciales en ``.env``
(``SOFA_PLUS_COOKIE``) y esas secciones dejarán de salir bloqueadas. El
framework no rompe ningún muro de pago: reutiliza *tu* sesión.
"""

from __future__ import annotations

from .auth import Credentials
from .cache import DiskCache, MemoryCache, NullCache
from .catalog import (
    KNOWN_STAT_KEYS,
    LEAGUES,
    MATCH_STAT_KEYS,
    PLAYER_STAT_KEYS,
    find_league,
    status_label,
    suggest_stat,
)
from .client import SofascoreClient
from .config import Settings
from .endpoints import (
    ALL_SECTIONS,
    DEFAULT_SECTIONS,
    PLAYER_SECTIONS,
    SECTIONS,
    TEAM_SECTIONS,
    TOURNAMENT_SECTIONS,
    Section,
)
from .entities import (
    EntityReport,
    build_entity_report,
    build_player_report,
    build_team_report,
    build_tournament_report,
    find_entity,
)
from .errors import (
    AmbiguousMatch,
    HTTPError,
    MatchNotFound,
    NotFound,
    OfflineError,
    PlusRequired,
    RateLimited,
    SofascoreError,
    TransportError,
)
from .frames import flatten, to_frames, to_tables
from .match import MatchReport, build_report
from .models import Event, Player, Score, Team
from .report import SectionResult
from .resolve import Candidate, Resolution, resolve_event
from .transport import FakeTransport, HttpxTransport, UrllibTransport

__version__ = "0.1.0"


def build_client(settings: Settings | None = None, **overrides) -> SofascoreClient:
    """Crea un cliente con la configuración del entorno más los overrides dados."""
    ajustes = settings or Settings.from_env(**overrides)
    return SofascoreClient(ajustes)


def get_match(
    query: str | int,
    date: str | None = None,
    sections: list[str] | None = None,
    include_plus: bool = True,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    max_players: int = 40,
    strict: bool = False,
    **overrides,
) -> MatchReport:
    """Resuelve el partido y devuelve su informe completo.

    ``query`` puede ser un id, una URL de Sofascore o ``"Equipo A vs Equipo B"``.
    """
    propio = client is None
    cliente = client or build_client(settings, **overrides)
    try:
        resolucion = resolve_event(cliente, query, date=date, strict=strict)
        informe = build_report(
            cliente,
            resolucion.event,
            sections=sections,
            include_plus=include_plus,
            max_players=max_players,
        )
        informe.meta["resolucion"] = {
            "consulta": str(query),
            "origen": resolucion.source,
            "alternativas": [str(c) for c in resolucion.candidates[1:6]],
        }
        informe.meta["peticiones"] = cliente.stats.as_dict()
        return informe
    finally:
        if propio:
            cliente.close()


def search_matches(
    query: str,
    date: str | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> list[Candidate]:
    """Devuelve los partidos candidatos para una consulta, ordenados por encaje."""
    propio = client is None
    cliente = client or build_client(settings, **overrides)
    try:
        return resolve_event(cliente, query, date=date).candidates
    finally:
        if propio:
            cliente.close()


def _con_cliente(client, settings, overrides, trabajo):
    """Ejecuta ``trabajo(cliente)`` creando y cerrando el cliente si hace falta."""
    propio = client is None
    cliente = client or build_client(settings, **overrides)
    try:
        return trabajo(cliente)
    finally:
        if propio:
            cliente.close()


def get_team(
    query: str | int,
    sections: list[str] | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> EntityReport:
    """Informe de un equipo: plantilla, calendario, forma, traspasos..."""
    return _con_cliente(
        client, settings, overrides,
        lambda c: build_team_report(c, query, sections=sections),
    )


def get_player(
    query: str | int,
    sections: list[str] | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> EntityReport:
    """Informe de un jugador: ficha, atributos, temporadas, traspasos..."""
    return _con_cliente(
        client, settings, overrides,
        lambda c: build_player_report(c, query, sections=sections),
    )


def get_league(
    query: str | int,
    season_id: int | None = None,
    sections: list[str] | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> EntityReport:
    """Informe de una competición: clasificación, jornadas, goleadores...

    Sin ``season_id`` se usa la temporada en curso.
    """
    return _con_cliente(
        client, settings, overrides,
        lambda c: build_tournament_report(c, query, season_id=season_id, sections=sections),
    )


def live_matches(
    sport: str | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> list[Event]:
    """Los partidos que se están jugando ahora mismo."""
    return _con_cliente(
        client, settings, overrides,
        lambda c: [Event.from_api(e) for e in c.live_events(sport)],
    )


def matches_on(
    date: str,
    sport: str | None = None,
    client: SofascoreClient | None = None,
    settings: Settings | None = None,
    **overrides,
) -> list[Event]:
    """Todos los partidos de un día (``AAAA-MM-DD``)."""
    return _con_cliente(
        client, settings, overrides,
        lambda c: [Event.from_api(e) for e in c.scheduled_events(date, sport)],
    )


__all__ = [
    "__version__",
    "get_match",
    "get_team",
    "get_player",
    "get_league",
    "live_matches",
    "matches_on",
    "search_matches",
    "build_client",
    "SofascoreClient",
    "Settings",
    "Credentials",
    "MatchReport",
    "SectionResult",
    "build_report",
    "Event",
    "Team",
    "Player",
    "Score",
    "Candidate",
    "Resolution",
    "resolve_event",
    "EntityReport",
    "build_entity_report",
    "build_team_report",
    "build_player_report",
    "build_tournament_report",
    "find_entity",
    "Section",
    "SECTIONS",
    "TEAM_SECTIONS",
    "PLAYER_SECTIONS",
    "TOURNAMENT_SECTIONS",
    "DEFAULT_SECTIONS",
    "ALL_SECTIONS",
    "LEAGUES",
    "find_league",
    "status_label",
    "suggest_stat",
    "KNOWN_STAT_KEYS",
    "MATCH_STAT_KEYS",
    "PLAYER_STAT_KEYS",
    "to_frames",
    "to_tables",
    "flatten",
    "DiskCache",
    "MemoryCache",
    "NullCache",
    "FakeTransport",
    "UrllibTransport",
    "HttpxTransport",
    "SofascoreError",
    "HTTPError",
    "NotFound",
    "RateLimited",
    "PlusRequired",
    "MatchNotFound",
    "AmbiguousMatch",
    "OfflineError",
    "TransportError",
]
