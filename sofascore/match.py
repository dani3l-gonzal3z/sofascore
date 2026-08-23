"""El informe de un partido: pides un partido, te llevas todo lo que hay.

:func:`build_report` recorre el catálogo de secciones, pide cada una y anota
qué se ha podido traer y qué no. Una sección que falla **no** tumba el informe:
queda marcada (``plus_required``, ``unavailable``, ``error``) y el resto sigue.

Las secciones se piden en paralelo (``Settings.concurrency``), salvo las que
dependen de otra: el mapa de calor por jugador necesita antes las alineaciones,
así que va en una segunda tanda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .catalog import suggest_stat
from .client import SofascoreClient
from .endpoints import Section, get_section, resolve_sections
from .errors import NotFound, PlusRequired, SofascoreError
from .models import Event, Player
#: Los estados viven en :mod:`sofascore.report`; se reexportan aquí porque es
#: donde los busca todo el mundo (``from sofascore.match import OK``).
from .report import (
    EMPTY,
    ERROR,
    OK,
    PLUS_REQUIRED,
    UNAVAILABLE,
    BaseReport,
    SectionResult,
    run_all,
)


@dataclass
class MatchReport(BaseReport):
    """Todos los datos de un partido, sección a sección."""

    event: Event = field(default_factory=lambda: Event(id=0))

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

    def incidents(self, tipo: str | None = None) -> list[dict]:
        """Cronología del partido, opcionalmente filtrada por tipo de incidencia."""
        incidencias = [i for i in (self.get("incidents") or []) if isinstance(i, dict)]
        if tipo:
            incidencias = [i for i in incidencias if i.get("incidentType") == tipo]
        return sorted(incidencias, key=lambda i: (i.get("time") or 0, i.get("addedTime") or 0))

    def goals(self) -> list[dict]:
        """Incidencias de tipo gol, en orden cronológico."""
        return self.incidents("goal")

    def cards(self) -> list[dict]:
        """Tarjetas mostradas, en orden cronológico."""
        return self.incidents("card")

    def substitutions(self) -> list[dict]:
        """Cambios, en orden cronológico."""
        return self.incidents("substitution")

    def shots(self) -> list[dict]:
        """Disparos del mapa de tiros (requiere que ``shotmap`` esté disponible)."""
        return [s for s in (self.get("shotmap") or []) if isinstance(s, dict)]

    def ratings(self) -> list[dict]:
        """Valoración de Sofascore por jugador, de mayor a menor."""
        salida = []
        for jugador in self.players():
            nota = (jugador.raw.get("statistics") or {}).get("rating")
            if nota is None:
                continue
            salida.append({
                "jugador": jugador.name,
                "jugador_id": jugador.id,
                "equipo_id": jugador.team_id,
                "posicion": jugador.position,
                "suplente": jugador.substitute,
                "rating": float(nota),
            })
        return sorted(salida, key=lambda f: -f["rating"])

    def statistic(self, clave: str, periodo: str = "ALL") -> dict | None:
        """Busca una estadística concreta (``ballPossession``, ``expectedGoals``...).

        Devuelve ``None`` si no está. Para saber *por qué* no está —error de
        dedo o dato que este partido no trae— usa :meth:`statistic_keys` o
        :meth:`suggest`.
        """
        for bloque in self.get("statistics") or []:
            if periodo and bloque.get("period") != periodo:
                continue
            for grupo in bloque.get("groups", []) or []:
                for item in grupo.get("statisticsItems", []) or []:
                    if clave in (item.get("key"), item.get("name")):
                        return item
        return None

    def statistic_keys(self, periodo: str = "ALL") -> list[str]:
        """Todas las claves de estadística que este partido sí trae."""
        claves = []
        for bloque in self.get("statistics") or []:
            if periodo and bloque.get("period") != periodo:
                continue
            for grupo in bloque.get("groups", []) or []:
                for item in grupo.get("statisticsItems", []) or []:
                    if item.get("key"):
                        claves.append(item["key"])
        return sorted(set(claves))

    def suggest(self, clave: str) -> list[str]:
        """Claves parecidas a la que has escrito, mirando primero este partido."""
        presentes = self.statistic_keys()
        from difflib import get_close_matches

        cercanas = get_close_matches(clave, presentes, n=3, cutoff=0.6)
        return cercanas or suggest_stat(clave)

    def statistics_table(self, periodo: str = "ALL") -> list[dict]:
        """Las estadísticas en filas planas: grupo, clave, local, visitante."""
        filas = []
        for bloque in self.get("statistics") or []:
            if periodo and bloque.get("period") != periodo:
                continue
            for grupo in bloque.get("groups", []) or []:
                for item in grupo.get("statisticsItems", []) or []:
                    filas.append({
                        "periodo": bloque.get("period"),
                        "grupo": grupo.get("groupName"),
                        "clave": item.get("key"),
                        "nombre": item.get("name"),
                        "local": item.get("home"),
                        "visitante": item.get("away"),
                    })
        return filas

    # --- Serialización ---

    def to_dict(self, include_data: bool = True) -> dict:
        return {
            "partido": self.event.to_dict(),
            "meta": self.meta,
            "resumen": self.resumen_estados(),
            "secciones": {
                nombre: resultado.to_dict(include_data=include_data)
                for nombre, resultado in self.sections.items()
            },
        }

    def frames(self):
        """Las tablas del partido como ``DataFrame`` (necesita ``pandas``)."""
        from .frames import to_frames

        return to_frames(self)

    def tables(self) -> dict[str, list[dict]]:
        """Lo mismo que :meth:`frames`, pero en listas de diccionarios."""
        from .frames import to_tables

        return to_tables(self)

    def summary(self) -> str:
        """Resumen de una línea por sección, para imprimir en el terminal."""
        return "\n".join([self.event.label, self.event.url, "", *self.lineas_estado()])


def _fetch_simple(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
    extra = {}
    if "language" in seccion.needs:
        extra["language"] = cliente.settings.language
    return cliente.section(seccion, evento.id, ttl=ttl, **extra)


def _fetch_standings(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
    if not (evento.unique_tournament_id and evento.season_id):
        raise NotFound(404, "standings", "El partido no trae competición/temporada.")
    return cliente.standings(evento.unique_tournament_id, evento.season_id)


def _fetch_por_equipo(cliente: SofascoreClient, seccion: Section, evento: Event, ttl: int) -> Any:
    """Secciones que se piden una vez por equipo (mapa de calor del equipo)."""
    salida: dict[str, Any] = {}
    errores = 0
    for lado, equipo in (("home", evento.home), ("away", evento.away)):
        if not equipo.id:
            continue
        try:
            salida[lado] = {
                "equipo": equipo.name,
                "equipo_id": equipo.id,
                "datos": cliente.section(seccion, evento.id, ttl=ttl, team_id=equipo.id),
            }
        except PlusRequired:
            raise
        except SofascoreError:
            errores += 1
    if not salida and errores:
        raise NotFound(404, seccion.name, "Ningún equipo tiene esos datos.")
    return salida


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


def _en_paralelo(tareas: list[tuple[Section, Callable]], cliente, evento, ttl, hilos: int):
    """Adapta las funciones de este módulo a la firma que espera ``run_all``."""
    adaptadas = [(s, lambda sec, f=f: f(cliente, sec, evento, ttl)) for s, f in tareas]
    return run_all(adaptadas, hilos)


def build_report(
    cliente: SofascoreClient,
    event_or_id: Event | int,
    sections: list[str] | None = None,
    include_plus: bool = True,
    max_players: int = 40,
    concurrency: int | None = None,
) -> MatchReport:
    """Construye el informe completo de un partido.

    ``sections`` acepta nombres del catálogo o ``["all"]``. Con
    ``include_plus=False`` ni se intentan las secciones de pago.
    ``concurrency`` cuántas secciones se piden a la vez (por defecto, la de los
    ajustes; ``1`` las pide de una en una).
    """
    evento = event_or_id if isinstance(event_or_id, Event) else cliente.event(int(event_or_id))
    elegidas = resolve_sections(sections, include_plus=include_plus, sport=evento.sport)
    ttl = cliente.ttl_for_event(evento)
    hilos = cliente.settings.concurrency if concurrency is None else concurrency

    informe = MatchReport(
        event=evento,
        meta={
            "secciones_pedidas": [s.name for s in elegidas],
            "credenciales_plus": cliente.has_plus,
            "deporte": evento.sport or cliente.settings.sport,
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

    #: Secciones que necesitan las alineaciones ya traídas.
    POR_JUGADOR = {"player_statistics", "heatmaps"}
    pendientes = [s for s in elegidas if s.name != "event"]
    if any(s.name in POR_JUGADOR for s in pendientes):
        # Las alineaciones dejan de ser una sección más: son un requisito previo.
        pendientes = [s for s in pendientes if s.name != "lineups"]
        primera_tanda = [get_section("lineups")] + [
            s for s in pendientes if s.name not in POR_JUGADOR
        ]
    else:
        primera_tanda = [s for s in pendientes if s.name not in POR_JUGADOR]

    def resolver(seccion: Section) -> Callable:
        if seccion.name == "standings":
            return _fetch_standings
        if seccion.name == "team_heatmap":
            return _fetch_por_equipo
        return _fetch_simple

    tareas = [(s, resolver(s)) for s in primera_tanda]
    for resultado in _en_paralelo(tareas, cliente, evento, ttl, hilos):
        informe.sections[resultado.name] = resultado

    # Segunda tanda: lo que depende de las alineaciones.
    segunda = [s for s in pendientes if s.name in POR_JUGADOR]
    if segunda:
        jugadores = informe.players()
        metodos = {
            "player_statistics": lambda c, e, p: c.player_statistics(e, p),
            "heatmaps": lambda c, e, p: c.player_heatmap(e, p),
        }
        tareas = [
            (s, _fetch_por_jugador(metodos[s.name], jugadores, max_players)) for s in segunda
        ]
        for resultado in _en_paralelo(tareas, cliente, evento, ttl, hilos):
            informe.sections[resultado.name] = resultado

    # El paralelismo desordena: se recolocan como se pidieron.
    informe.reordenar([s.name for s in elegidas])

    if bloqueadas := informe.locked():
        informe.meta["nota_plus"] = (
            "Estas secciones son de Sofascore Plus: "
            + ", ".join(bloqueadas)
            + ". Configura SOFA_PLUS_COOKIE con tu propia sesión para incluirlas."
        )
    return informe


__all__ = [
    "OK",
    "EMPTY",
    "PLUS_REQUIRED",
    "UNAVAILABLE",
    "ERROR",
    "SectionResult",
    "MatchReport",
    "build_report",
]
