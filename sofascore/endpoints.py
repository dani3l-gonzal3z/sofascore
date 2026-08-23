"""Catálogo de secciones: qué se puede pedir y de qué ruta sale.

Cada *sección* es un trozo de información (estadísticas, alineaciones, mapa de
tiros...) con la ruta de la API que lo sirve. El catálogo es declarativo a
propósito: añadir un dato nuevo es añadir una línea aquí, no tocar el cliente.

Hay cuatro catálogos, uno por tipo de cosa que se puede pedir:
:data:`SECTIONS` (partidos), :data:`TEAM_SECTIONS`, :data:`PLAYER_SECTIONS` y
:data:`TOURNAMENT_SECTIONS`.

Sobre ``scope``:

* ``public``  — datos abiertos de la web de Sofascore.
* ``plus``    — lo que Sofascore suele reservar a su suscripción de pago. El
  framework NO salta el muro de pago: se limita a usar TUS credenciales si las
  configuras y, si no, marca la sección como ``plus_required`` y sigue.

El ``scope`` es una *pista*: qué está abierto y qué no cambia con el tiempo, el
deporte y la competición, así que la disponibilidad real se decide con la
respuesta de la API, no con esta tabla.

Sobre las rutas: están contrastadas una a una con las librerías públicas que ya
hablan con esta API (``ScraperFC``, ``soccerdata``, ``sofascore-wrapper``,
``sofascrape``, ``pysofascore``). Cuando una ruta aparece en varias de ellas,
es la que llevan usando años contra el servicio real.
"""

from __future__ import annotations

from dataclasses import dataclass

PUBLIC = "public"
PLUS = "plus"


@dataclass(frozen=True)
class Section:
    """Una sección de un informe."""

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
    #: Deportes en los que tiene sentido. ``None`` = todos.
    sports: tuple[str, ...] | None = None
    #: Parámetros de la ruta que no son el id principal (los rellena el cliente).
    needs: tuple[str, ...] = ()

    def url_path(self, event_id: int | None = None, **extra) -> str:
        contexto = dict(extra)
        if event_id is not None:
            contexto.setdefault("event_id", event_id)
        return self.path.format(**contexto)

    @property
    def requires_plus(self) -> bool:
        return self.scope == PLUS

    def applies_to(self, sport: str | None) -> bool:
        """¿Tiene sentido esta sección para ese deporte?"""
        if not self.sports:
            return True
        if not sport:
            return True  # sin saber el deporte, mejor intentarlo que descartarlo
        return sport in self.sports


def _catalogo(secciones: list[Section]) -> dict[str, Section]:
    return {s.name: s for s in secciones}


# --------------------------------------------------------------------- partidos

SECTIONS: dict[str, Section] = _catalogo([
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
    Section("odds_featured", "/event/{event_id}/odds/1/featured",
            "Cuotas destacadas (el mercado principal).", default=False),
    Section("winning_odds", "/event/{event_id}/provider/1/winning-odds",
            "Cuota ganadora una vez cerrado el partido.", default=False,
            experimental=True),
    Section("highlights", "/event/{event_id}/highlights",
            "Vídeos y resúmenes enlazados.", unwrap="highlights", default=False),
    Section("comments", "/event/{event_id}/comments",
            "Narración textual del partido.", unwrap="comments", default=False),
    Section("tv_channels", "/tv/event/{event_id}/country-channels",
            "Dónde se emite el partido, por país.", default=False),
    Section("standings", "/event/{event_id}/standings",
            "Clasificación de la competición en esa jornada.",
            derived=True, default=False),

    # --- Habitualmente detrás de Sofascore Plus ---
    Section("shotmap", "/event/{event_id}/shotmap",
            "Mapa de tiros con xG por disparo.", scope=PLUS, unwrap="shotmap"),
    Section("average_positions", "/event/{event_id}/average-positions",
            "Posición media de cada jugador sobre el campo.", scope=PLUS),
    Section("team_heatmap", "/event/{event_id}/heatmap/{team_id}",
            "Mapa de calor de todo el equipo (uno por equipo).", scope=PLUS,
            derived=True, default=False),
    Section("player_statistics", "/event/{event_id}/player/{player_id}/statistics",
            "Estadísticas avanzadas jugador a jugador.", scope=PLUS,
            derived=True, default=False),
    Section("heatmaps", "/event/{event_id}/player/{player_id}/heatmap",
            "Mapa de calor de cada jugador.", scope=PLUS, derived=True, default=False),
    Section("win_probability", "/event/{event_id}/graph/win-probability",
            "Probabilidad de victoria minuto a minuto.", scope=PLUS,
            unwrap="graphPoints", experimental=True, default=False),
    Section("ai_insights", "/event/{event_id}/ai-insights/{language}",
            "Lecturas del partido generadas por Sofascore.", scope=PLUS,
            experimental=True, default=False, needs=("language",)),

    # --- Específicas de un deporte ---
    Section("point_by_point", "/event/{event_id}/point-by-point",
            "Punto a punto del partido (tenis).", unwrap="pointByPoint",
            default=False, sports=("tennis",)),
    Section("tennis_power", "/event/{event_id}/tennis-power",
            "Dominio por juego (tenis).", default=False, sports=("tennis",)),
    Section("innings", "/event/{event_id}/innings",
            "Entradas del partido (críquet).", default=False, sports=("cricket",)),
    Section("esports_games", "/event/{event_id}/esports-games",
            "Mapas/partidas de la serie (esports).", default=False, sports=("esports",)),
])

#: Secciones incluidas cuando no se pide nada en concreto.
DEFAULT_SECTIONS = [s.name for s in SECTIONS.values() if s.default]

#: Todas las secciones, incluidas las caras de construir.
ALL_SECTIONS = list(SECTIONS)


# ----------------------------------------------------------------------- equipos

TEAM_SECTIONS: dict[str, Section] = _catalogo([
    Section("profile", "/team/{team_id}", "Ficha del equipo: estadio, país, entrenador, valor.",
            unwrap="team"),
    Section("players", "/team/{team_id}/players", "Plantilla actual.", unwrap="players"),
    Section("last_events", "/team/{team_id}/events/last/0", "Últimos partidos jugados.",
            unwrap="events"),
    Section("next_events", "/team/{team_id}/events/next/0", "Próximos partidos.",
            unwrap="events"),
    Section("performance", "/team/{team_id}/performance", "Racha de resultados reciente."),
    Section("transfers", "/team/{team_id}/transfers", "Altas y bajas.", default=False),
    Section("statistics_seasons", "/team/{team_id}/team-statistics/seasons",
            "Temporadas con estadísticas disponibles.", default=False),
    Section("standings_seasons", "/team/{team_id}/standings/seasons",
            "Temporadas con clasificación disponible.", default=False),
    Section("near_events", "/team/{team_id}/near-events",
            "El partido anterior y el siguiente.", default=False),
    Section("media", "/team/{team_id}/media", "Vídeos y contenido del equipo.", default=False),
])


# ---------------------------------------------------------------------- jugadores

PLAYER_SECTIONS: dict[str, Section] = _catalogo([
    Section("profile", "/player/{player_id}",
            "Ficha: edad, posición, dorsal, valor de mercado, contrato.", unwrap="player"),
    Section("attributes", "/player/{player_id}/attribute-overviews",
            "El radar de atributos (ataque, técnica, defensa...)."),
    Section("season_index", "/player/{player_id}/statistics/seasons",
            "Temporadas y competiciones con estadísticas disponibles."),
    Section("last_year", "/player/{player_id}/last-year-summary",
            "Resumen del último año: valoraciones partido a partido."),
    Section("transfers", "/player/{player_id}/transfer-history", "Historial de traspasos."),
    Section("national_team", "/player/{player_id}/national-team-statistics",
            "Estadísticas con su selección.", default=False),
    Section("tournaments", "/player/{player_id}/unique-tournaments",
            "Competiciones en las que ha jugado.", default=False),
    Section("last_events", "/player/{player_id}/events/last/0",
            "Últimos partidos disputados.", unwrap="events", default=False),
    Section("season_statistics",
            "/player/{player_id}/unique-tournament/{tournament_id}/season/{season_id}"
            "/statistics/overall",
            "Estadísticas completas en una liga y temporada concretas.",
            derived=True, default=False, needs=("tournament_id", "season_id")),
])


# ------------------------------------------------------------------ competiciones

TOURNAMENT_SECTIONS: dict[str, Section] = _catalogo([
    Section("profile", "/unique-tournament/{tournament_id}",
            "Ficha de la competición.", unwrap="uniqueTournament"),
    Section("seasons", "/unique-tournament/{tournament_id}/seasons",
            "Todas las temporadas con su id.", unwrap="seasons"),
    Section("standings", "/unique-tournament/{tournament_id}/season/{season_id}/standings/total",
            "Clasificación de la temporada.", unwrap="standings", needs=("season_id",)),
    Section("rounds", "/unique-tournament/{tournament_id}/season/{season_id}/rounds",
            "Jornadas o rondas de la temporada.", needs=("season_id",)),
    Section("top_players", "/unique-tournament/{tournament_id}/season/{season_id}"
            "/top-players/overall",
            "Máximos goleadores, asistentes, mejor valorados...", needs=("season_id",)),
    Section("top_teams", "/unique-tournament/{tournament_id}/season/{season_id}"
            "/top-teams/overall",
            "Los mejores equipos por cada métrica.", needs=("season_id",), default=False),
    Section("last_events", "/unique-tournament/{tournament_id}/season/{season_id}/events/last/0",
            "Últimos partidos disputados.", unwrap="events", needs=("season_id",)),
    Section("next_events", "/unique-tournament/{tournament_id}/season/{season_id}/events/next/0",
            "Próximos partidos.", unwrap="events", needs=("season_id",), default=False),
    Section("cuptree", "/unique-tournament/{tournament_id}/season/{season_id}/cuptrees",
            "Cuadro de eliminatorias.", needs=("season_id",), default=False),
])


#: Todos los catálogos, por si quieres recorrerlos.
CATALOGS: dict[str, dict[str, Section]] = {
    "match": SECTIONS,
    "team": TEAM_SECTIONS,
    "player": PLAYER_SECTIONS,
    "tournament": TOURNAMENT_SECTIONS,
}


def get_section(nombre: str, catalogo: dict[str, Section] | None = None) -> Section:
    """Devuelve una sección por nombre, con un error legible si no existe."""
    tabla = SECTIONS if catalogo is None else catalogo
    try:
        return tabla[nombre]
    except KeyError:
        disponibles = ", ".join(sorted(tabla))
        raise KeyError(f"Sección desconocida: '{nombre}'. Disponibles: {disponibles}") from None


def resolve_sections(
    nombres: list[str] | None,
    include_plus: bool = True,
    catalogo: dict[str, Section] | None = None,
    base: str | None = "event",
    sport: str | None = None,
) -> list[Section]:
    """Traduce una lista de nombres (o ``["all"]``) a objetos :class:`Section`.

    ``base`` es la sección que siempre va primero y nunca falta (para un partido
    es ``event``). ``sport`` descarta las secciones de otros deportes cuando se
    piden todas; si las nombras a mano, se respetan.
    """
    tabla = SECTIONS if catalogo is None else catalogo
    por_defecto = [s for s in tabla.values() if s.default]
    pedidas_todas = bool(nombres) and len(nombres) == 1 and nombres[0] in {"all", "todas", "*"}

    if not nombres:
        elegidas = por_defecto
    elif pedidas_todas:
        elegidas = list(tabla.values())
    else:
        elegidas = [get_section(n.strip(), tabla) for n in nombres if n.strip()]

    if not nombres or pedidas_todas:
        elegidas = [s for s in elegidas if s.applies_to(sport)]
    if not include_plus:
        elegidas = [s for s in elegidas if not s.requires_plus]

    if base and base in tabla:
        cabecera = tabla[base]
        return [cabecera, *[s for s in elegidas if s.name != base]]
    return list(elegidas)
