"""Catálogo de secciones de un partido.

Cada *sección* es un trozo de información (estadísticas, alineaciones, mapa de
tiros...) con la ruta de la API que lo sirve. El catálogo es declarativo a
propósito: añadir un dato nuevo es añadir una línea aquí, no tocar el cliente.

Sobre ``scope``:

* ``public``  — datos abiertos de la web de Sofascore.
* ``plus``    — lo que Sofascore suele reservar a su suscripción de pago. El
  framework NO salta el muro de pago: se limita a usar TUS credenciales si las
  configuras y, si no, marca la sección como ``plus_required`` y sigue.

El ``scope`` es una *pista*: qué está abierto y qué no cambia con el tiempo, el
deporte y la competición, así que la disponibilidad real se decide con la
respuesta de la API, no con esta tabla.
"""

from __future__ import annotations

from dataclasses import dataclass

PUBLIC = "public"
PLUS = "plus"


@dataclass(frozen=True)
class Section:
    """Una sección del informe de un partido."""

    name: str
    path: str
    description: str
    scope: str = PUBLIC
    #: Clave del JSON que contiene el dato útil (el resto es envoltorio).
    unwrap: str | None = None
    #: ¿Entra en el informe "completo" por defecto?
    default: bool = True
    #: Secciones que se construyen con lógica extra (no una simple llamada).
    derived: bool = False
    #: Endpoints menos estables: pueden no existir en todos los deportes.
    experimental: bool = False

    def url_path(self, event_id: int, **extra) -> str:
        return self.path.format(event_id=event_id, **extra)

    @property
    def requires_plus(self) -> bool:
        return self.scope == PLUS


SECTIONS: dict[str, Section] = {
    s.name: s
    for s in [
        # --- Núcleo público ---
        Section("event", "/event/{event_id}", "Datos del partido: marcador, estado, sede, árbitro.",
                unwrap="event"),
        Section("statistics", "/event/{event_id}/statistics",
                "Estadísticas por periodo: posesión, tiros, pases, duelos...",
                unwrap="statistics"),
        Section("lineups", "/event/{event_id}/lineups",
                "Alineaciones, dorsales, suplentes, formación y valoraciones."),
        Section("incidents", "/event/{event_id}/incidents",
                "Cronología: goles, tarjetas, cambios, VAR, penaltis.", unwrap="incidents"),
        Section("momentum", "/event/{event_id}/graph",
                "Gráfico de presión/momento de ataque minuto a minuto.",
                unwrap="graphPoints"),
        Section("best_players", "/event/{event_id}/best-players/summary",
                "Mejores jugadores del partido según Sofascore."),
        Section("managers", "/event/{event_id}/managers", "Entrenadores de ambos equipos."),
        Section("votes", "/event/{event_id}/votes", "Votos del público al resultado.",
                unwrap="vote", default=False),
        Section("h2h", "/event/{event_id}/h2h", "Balance histórico entre los dos equipos.",
                unwrap="teamDuel"),
        Section("h2h_events", "/event/{event_id}/h2h/events",
                "Partidos anteriores entre ambos.", unwrap="events", default=False),
        Section("pregame_form", "/event/{event_id}/pregame-form",
                "Forma y posición en la tabla antes del partido."),
        Section("team_streaks", "/event/{event_id}/team-streaks",
                "Rachas activas de cada equipo.", default=False),
        Section("odds", "/event/{event_id}/odds/1/all",
                "Cuotas de las casas de apuestas (según país).", unwrap="markets",
                default=False),
        Section("highlights", "/event/{event_id}/highlights",
                "Vídeos y resúmenes enlazados.", unwrap="highlights", default=False),
        Section("comments", "/event/{event_id}/comments",
                "Narración textual del partido.", unwrap="comments", default=False),
        Section("standings", "/event/{event_id}/standings",
                "Clasificación de la competición en esa jornada.",
                derived=True, default=False),

        # --- Habitualmente detrás de Sofascore Plus ---
        Section("shotmap", "/event/{event_id}/shotmap",
                "Mapa de tiros con xG por disparo.", scope=PLUS, unwrap="shotmap"),
        Section("average_positions", "/event/{event_id}/average-positions",
                "Posición media de cada jugador sobre el campo.", scope=PLUS),
        Section("player_statistics", "/event/{event_id}/player/{player_id}/statistics",
                "Estadísticas avanzadas jugador a jugador.", scope=PLUS,
                derived=True, default=False),
        Section("heatmaps", "/event/{event_id}/player/{player_id}/heatmap",
                "Mapa de calor de cada jugador.", scope=PLUS, derived=True, default=False),
        Section("win_probability", "/event/{event_id}/win-probability",
                "Probabilidad de victoria en vivo.", scope=PLUS, experimental=True,
                default=False),
    ]
}

#: Secciones incluidas cuando no se pide nada en concreto.
DEFAULT_SECTIONS = [s.name for s in SECTIONS.values() if s.default]

#: Todas las secciones, incluidas las caras de construir.
ALL_SECTIONS = list(SECTIONS)


def get_section(nombre: str) -> Section:
    """Devuelve una sección por nombre, con un error legible si no existe."""
    try:
        return SECTIONS[nombre]
    except KeyError:
        disponibles = ", ".join(sorted(SECTIONS))
        raise KeyError(f"Sección desconocida: '{nombre}'. Disponibles: {disponibles}") from None


def resolve_sections(nombres: list[str] | None, include_plus: bool = True) -> list[Section]:
    """Traduce una lista de nombres (o ``["all"]``) a objetos :class:`Section`."""
    if not nombres:
        elegidas = [SECTIONS[n] for n in DEFAULT_SECTIONS]
    elif len(nombres) == 1 and nombres[0] in {"all", "todas", "*"}:
        elegidas = list(SECTIONS.values())
    else:
        elegidas = [get_section(n.strip()) for n in nombres if n.strip()]
    if not include_plus:
        elegidas = [s for s in elegidas if not s.requires_plus]
    # "event" es la base de todo informe: siempre primero y siempre presente.
    base = SECTIONS["event"]
    resto = [s for s in elegidas if s.name != "event"]
    return [base, *resto]
