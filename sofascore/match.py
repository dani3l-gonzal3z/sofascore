"""El informe de un partido: pides un partido, te llevas todo lo que hay.

:func:`build_report` recorre el catálogo de secciones, pide cada una y anota
qué se ha podido traer y qué no. Una sección que falla **no** tumba el informe:
queda marcada (``plus_required``, ``unavailable``, ``error``) y el resto sigue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .client import SofascoreClient
from .endpoints import Section, get_section, resolve_sections
from .errors import HTTPError, NotFound, PlusRequired, SofascoreError
from .models import Event, Player

#: Estados posibles de una sección del informe.
OK = "ok"
EMPTY = "empty"
PLUS_REQUIRED = "plus_required"
UNAVAILABLE = "unavailable"
ERROR = "error"


@dataclass
class SectionResult:
    """Qué ha pasado con una sección concreta."""

    name: str
    scope: str
    status: str
    data: Any = None
    error: str = ""
    endpoint: str = ""
    description: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self, include_data: bool = True) -> dict:
        salida = {
            "seccion": self.name,
            "ambito": self.scope,
            "estado": self.status,
            "endpoint": self.endpoint,
            "descripcion": self.description,
        }
        if self.error:
            salida["error"] = self.error
        if include_data:
            salida["datos"] = self.data
        return salida


@dataclass
class MatchReport:
    """Todos los datos de un partido, sección a sección."""

    event: Event
    sections: dict[str, SectionResult] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # --- Acceso ---

    def __getitem__(self, nombre: str) -> Any:
        return self.sections[nombre].data

    def __contains__(self, nombre: str) -> bool:
        return nombre in self.sections and self.sections[nombre].ok

    def get(self, nombre: str, default: Any = None) -> Any:
        """Datos de una sección, o ``default`` si no está disponible."""
        resultado = self.sections.get(nombre)
        return resultado.data if resultado and resultado.ok else default

    def available(self) -> list[str]:
        """Secciones que sí traen datos."""
        return [n for n, r in self.sections.items() if r.ok]

    def empty(self) -> list[str]:
        """Secciones que existen pero no tienen contenido (partido sin jugar, etc.)."""
        return [n for n, r in self.sections.items() if r.status == EMPTY]

    def locked(self) -> list[str]:
        """Secciones que necesitan Sofascore Plus y no se han podido traer."""
        return [n for n, r in self.sections.items() if r.status == PLUS_REQUIRED]

    def failed(self) -> list[str]:
        """Secciones que han fallado por error o por no existir en este partido."""
        return [n for n, r in self.sections.items() if r.status in (ERROR, UNAVAILABLE)]

    # --- Datos derivados cómodos ---

    def players(self) -> list[Player]:
        """Jugadores de ambas alineaciones (titulares y suplentes)."""
        alineaciones = self.get("lineups") or {}
        jugadores: list[Player] = []
        for lado, equipo in (("home", self.event.home), ("away", self.event.away)):
            bloque = alineaciones.get(lado) or {}
            for entrada in bloque.get("players", []) or []:
                jugadores.append(Player.from_api(entrada, team_id=equipo.id))
        return jugadores

    def goals(self) -> list[dict]:
        """Incidencias de tipo gol, en orden cronológico."""
        incidencias = self.get("incidents") or []
        goles = [i for i in incidencias if i.get("incidentType") == "goal"]
        return sorted(goles, key=lambda i: (i.get("time") or 0, i.get("addedTime") or 0))

    def statistic(self, clave: str, periodo: str = "ALL") -> dict | None:
        """Busca una estadística concreta (``ballPossession``, ``expectedGoals``...)."""
        for bloque in self.get("statistics") or []:
            if bloque.get("period") != periodo:
                continue
            for grupo in bloque.get("groups", []) or []:
                for item in grupo.get("statisticsItems", []) or []:
                    if clave in (item.get("key"), item.get("name")):
                        return item
        return None

    # --- Serialización ---

    def to_dict(self, include_data: bool = True) -> dict:
        return {
            "partido": self.event.to_dict(),
            "meta": self.meta,
            "resumen": {
                "disponibles": self.available(),
                "vacias": self.empty(),
                "requieren_plus": self.locked(),
                "fallidas": self.failed(),
            },
            "secciones": {
                nombre: resultado.to_dict(include_data=include_data)
                for nombre, resultado in self.sections.items()
            },
        }

    def summary(self) -> str:
        """Resumen de una línea por sección, para imprimir en el terminal."""
        iconos = {OK: "✓", EMPTY: "·", PLUS_REQUIRED: "🔒", UNAVAILABLE: "–", ERROR: "✗"}
        lineas = [self.event.label, self.event.url, ""]
        for nombre, resultado in self.sections.items():
            icono = iconos.get(resultado.status, "?")
            detalle = f" — {resultado.error}" if resultado.error else ""
            lineas.append(f" {icono} {nombre:<20} {resultado.status}{detalle}")
        return "\n".join(lineas)


def _vacio(datos: Any) -> bool:
    return datos is None or (isinstance(datos, (list, dict, str)) and len(datos) == 0)


def _fetch_simple(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
    return cliente.section(seccion, evento.id, ttl=ttl)


def _fetch_standings(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
    if not (evento.unique_tournament_id and evento.season_id):
        raise NotFound(404, "standings", "El partido no trae competición/temporada.")
    return cliente.standings(evento.unique_tournament_id, evento.season_id)


def _fetch_por_jugador(
    metodo: Callable[[SofascoreClient, int, int], Any],
    jugadores: Iterable[Player],
    limite: int,
) -> Callable[[SofascoreClient, Section, Event, int], Any]:
    def interno(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
        salida: dict[str, Any] = {}
        errores = 0
        for jugador in list(jugadores)[:limite]:
            if not jugador.id:
                continue
            try:
                salida[str(jugador.id)] = {
                    "nombre": jugador.name,
                    "equipo_id": jugador.team_id,
                    "datos": metodo(cliente, evento.id, jugador.id),
                }
            except PlusRequired:
                raise
            except SofascoreError:
                errores += 1
                continue
        if not salida and errores:
            raise NotFound(404, seccion.name, "Ningún jugador tiene esos datos.")
        return salida

    return interno


def build_report(
    cliente: SofascoreClient,
    event_or_id: Event | int,
    sections: list[str] | None = None,
    include_plus: bool = True,
    max_players: int = 40,
) -> MatchReport:
    """Construye el informe completo de un partido.

    ``sections`` acepta nombres del catálogo o ``["all"]``. Con
    ``include_plus=False`` ni se intentan las secciones de pago.
    """
    evento = event_or_id if isinstance(event_or_id, Event) else cliente.event(int(event_or_id))
    elegidas = resolve_sections(sections, include_plus=include_plus)
    ttl = cliente.ttl_for_event(evento)

    informe = MatchReport(
        event=evento,
        meta={
            "secciones_pedidas": [s.name for s in elegidas],
            "credenciales_plus": cliente.has_plus,
            "deporte": cliente.settings.sport,
        },
    )
    informe.sections["event"] = SectionResult(
        name="event",
        scope="public",
        status=OK if evento.id else UNAVAILABLE,
        data=evento.raw,
        endpoint=f"/event/{evento.id}",
        description="Datos del partido: marcador, estado, sede, árbitro.",
    )

    # Las secciones por jugador necesitan las alineaciones: se piden antes.
    if any(s.name in {"player_statistics", "heatmaps"} for s in elegidas):
        elegidas = [s for s in elegidas if s.name != "lineups"]
        elegidas.insert(1, get_section("lineups"))

    for seccion in elegidas:
        if seccion.name == "event":
            continue

        if seccion.requires_plus and not include_plus:
            continue

        if seccion.name == "standings":
            traer = _fetch_standings
        elif seccion.name == "player_statistics":
            traer = _fetch_por_jugador(
                lambda c, e, p: c.player_statistics(e, p), informe.players(), max_players
            )
        elif seccion.name == "heatmaps":
            traer = _fetch_por_jugador(
                lambda c, e, p: c.player_heatmap(e, p), informe.players(), max_players
            )
        else:
            traer = _fetch_simple

        resultado = SectionResult(
            name=seccion.name,
            scope=seccion.scope,
            status=OK,
            endpoint=seccion.path,
            description=seccion.description,
        )
        try:
            datos = traer(cliente, seccion, evento, ttl)
            resultado.data = datos
            resultado.status = EMPTY if _vacio(datos) else OK
        except PlusRequired as exc:
            resultado.status = PLUS_REQUIRED
            resultado.error = str(exc)
        except NotFound as exc:
            resultado.status = UNAVAILABLE
            resultado.error = f"No disponible para este partido ({exc.status})."
        except HTTPError as exc:
            resultado.status = ERROR
            resultado.error = str(exc)
        except SofascoreError as exc:
            resultado.status = ERROR
            resultado.error = str(exc)

        informe.sections[seccion.name] = resultado

    if seccion_plus_bloqueada := informe.locked():
        informe.meta["nota_plus"] = (
            "Estas secciones son de Sofascore Plus: "
            + ", ".join(seccion_plus_bloqueada)
            + ". Configura SOFA_PLUS_COOKIE con tu propia sesión para incluirlas."
        )
    return informe
