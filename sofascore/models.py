"""Modelos ligeros sobre el JSON de la API.

Filosofía: dar objetos cómodos para lo habitual (``event.label``,
``event.is_finished``) sin esconder nada. Cada modelo conserva el JSON original
en ``.raw``, así que si la API devuelve un campo que aquí no se ha modelado,
sigue estando a mano.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .catalog import status_label


def _get(dato: Any, *claves: str, default: Any = None) -> Any:
    """Acceso anidado tolerante: ``_get(d, "venue", "stadium", "name")``."""
    actual = dato
    for clave in claves:
        if not isinstance(actual, dict):
            return default
        actual = actual.get(clave)
        if actual is None:
            return default
    return actual


@dataclass
class Team:
    id: int | None = None
    name: str = ""
    short_name: str = ""
    code: str = ""
    slug: str = ""
    country: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, datos: dict | None) -> Team:
        datos = datos or {}
        return cls(
            id=datos.get("id"),
            name=datos.get("name", ""),
            short_name=datos.get("shortName", "") or datos.get("name", ""),
            code=datos.get("nameCode", ""),
            slug=datos.get("slug", ""),
            country=_get(datos, "country", "name", default="") or "",
            raw=datos,
        )

    def __str__(self) -> str:
        return self.name or self.short_name or f"equipo#{self.id}"


@dataclass
class Score:
    """Marcador con desglose por periodos (los que traiga el deporte)."""

    current: int | None = None
    period1: int | None = None
    period2: int | None = None
    normaltime: int | None = None
    extra: int | None = None
    penalties: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, datos: dict | None) -> Score:
        datos = datos or {}
        return cls(
            current=datos.get("current"),
            period1=datos.get("period1"),
            period2=datos.get("period2"),
            normaltime=datos.get("normaltime"),
            extra=datos.get("extra"),
            penalties=datos.get("penalties"),
            raw=datos,
        )

    def __str__(self) -> str:
        return "-" if self.current is None else str(self.current)


@dataclass
class Player:
    id: int | None = None
    name: str = ""
    short_name: str = ""
    position: str = ""
    shirt_number: int | None = None
    team_id: int | None = None
    substitute: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, datos: dict | None, team_id: int | None = None,
                 substitute: bool = False) -> Player:
        datos = datos or {}
        jugador = datos.get("player", datos)
        dorsal = datos.get("shirtNumber") or jugador.get("jerseyNumber")
        try:
            dorsal = int(dorsal) if dorsal not in (None, "") else None
        except (TypeError, ValueError):
            dorsal = None
        return cls(
            id=jugador.get("id"),
            name=jugador.get("name", ""),
            short_name=jugador.get("shortName", "") or jugador.get("name", ""),
            position=datos.get("position") or jugador.get("position", "") or "",
            shirt_number=dorsal,
            team_id=team_id,
            substitute=bool(datos.get("substitute", substitute)),
            raw=datos,
        )

    def __str__(self) -> str:
        return self.name or f"jugador#{self.id}"


@dataclass
class Event:
    """Un partido."""

    id: int
    slug: str = ""
    #: Código corto del partido (``xNbsDNb``). Algunas rutas lo piden en vez del id.
    custom_id: str = ""
    home: Team = field(default_factory=Team)
    away: Team = field(default_factory=Team)
    home_score: Score = field(default_factory=Score)
    away_score: Score = field(default_factory=Score)
    status_type: str = ""
    status_description: str = ""
    status_code: int | None = None
    sport: str = ""
    start_timestamp: int | None = None
    tournament: str = ""
    unique_tournament_id: int | None = None
    season_id: int | None = None
    season_name: str = ""
    round: Any = None
    venue: str = ""
    city: str = ""
    referee: str = ""
    attendance: int | None = None
    winner_code: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, datos: dict) -> Event:
        datos = datos.get("event", datos) if isinstance(datos, dict) else {}
        return cls(
            id=int(datos.get("id", 0)),
            slug=datos.get("slug", ""),
            custom_id=datos.get("customId", "") or "",
            home=Team.from_api(datos.get("homeTeam")),
            away=Team.from_api(datos.get("awayTeam")),
            home_score=Score.from_api(datos.get("homeScore")),
            away_score=Score.from_api(datos.get("awayScore")),
            status_type=_get(datos, "status", "type", default="") or "",
            status_description=(
                _get(datos, "status", "description", default="")
                or status_label(_get(datos, "status", "code"))
            ),
            status_code=_get(datos, "status", "code"),
            sport=_get(datos, "tournament", "category", "sport", "slug", default="") or "",
            start_timestamp=datos.get("startTimestamp"),
            tournament=_get(datos, "tournament", "name", default="") or "",
            unique_tournament_id=_get(datos, "tournament", "uniqueTournament", "id"),
            season_id=_get(datos, "season", "id"),
            season_name=_get(datos, "season", "name", default="") or "",
            round=_get(datos, "roundInfo", "round"),
            venue=_get(datos, "venue", "stadium", "name", default="") or "",
            city=_get(datos, "venue", "city", "name", default="") or "",
            referee=_get(datos, "referee", "name", default="") or "",
            attendance=datos.get("attendance"),
            winner_code=datos.get("winnerCode"),
            raw=datos,
        )

    # --- Comodidades ---

    @property
    def kickoff(self) -> datetime | None:
        """Hora de inicio en UTC."""
        if not self.start_timestamp:
            return None
        return datetime.fromtimestamp(int(self.start_timestamp), tz=timezone.utc)

    @property
    def date(self) -> str:
        """Fecha del partido en ``AAAA-MM-DD`` (UTC)."""
        momento = self.kickoff
        return momento.strftime("%Y-%m-%d") if momento else ""

    @property
    def is_finished(self) -> bool:
        return self.status_type == "finished"

    @property
    def is_scheduled(self) -> bool:
        return self.status_type == "notstarted"

    @property
    def is_live(self) -> bool:
        return self.status_type == "inprogress"

    @property
    def scoreline(self) -> str:
        """``2 - 1`` si se ha jugado; ``vs`` si todavía no hay marcador."""
        if self.home_score.current is None and self.away_score.current is None:
            return "vs"
        return f"{self.home_score} - {self.away_score}"

    @property
    def label(self) -> str:
        """``Real Madrid 2 - 1 Barcelona (LaLiga, 2024-10-26)``."""
        cabecera = f"{self.home} {self.scoreline} {self.away}"
        detalles = ", ".join(p for p in (self.tournament, self.date) if p)
        return f"{cabecera} ({detalles})" if detalles else cabecera

    @property
    def url(self) -> str:
        """Enlace a la ficha del partido en la web."""
        slug = self.slug or "match"
        return f"https://www.sofascore.com/match/{slug}/#id:{self.id}"

    def winner(self) -> str:
        """``home``, ``away``, ``draw`` o ``""`` si aún no hay resultado."""
        return {1: "home", 2: "away", 3: "draw"}.get(self.winner_code or 0, "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "tournament": self.tournament,
            "season": self.season_name,
            "round": self.round,
            "date": self.date,
            "kickoff_utc": self.kickoff.isoformat() if self.kickoff else None,
            "sport": self.sport,
            "status": self.status_description or self.status_type,
            "status_code": self.status_code,
            "home": {"id": self.home.id, "name": self.home.name, "score": self.home_score.current},
            "away": {"id": self.away.id, "name": self.away.name, "score": self.away_score.current},
            "winner": self.winner(),
            "venue": self.venue,
            "city": self.city,
            "referee": self.referee,
            "attendance": self.attendance,
        }

    def __str__(self) -> str:
        return self.label
