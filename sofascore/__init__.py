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
from .client import SofascoreClient
from .config import Settings
from .endpoints import ALL_SECTIONS, DEFAULT_SECTIONS, SECTIONS, Section
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
from .match import MatchReport, SectionResult, build_report
from .models import Event, Player, Score, Team
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


__all__ = [
    "__version__",
    "get_match",
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
    "Section",
    "SECTIONS",
    "DEFAULT_SECTIONS",
    "ALL_SECTIONS",
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
