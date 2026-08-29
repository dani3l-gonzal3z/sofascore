"""Más allá del partido: equipos, jugadores y competiciones.

El framework nació para «dime un partido y te doy todo». Esto es lo mismo
aplicado a las otras tres cosas que Sofascore sabe describir, con la misma
mecánica de secciones y estados:

    from cancha import get_team, get_player, get_league

    madrid = get_team("Real Madrid")
    madrid.get("players")

    vini = get_player("Vinicius Junior")
    vini.get("attributes")

    liga = get_league("laliga")          # temporada en curso, si no dices otra
    liga.get("standings")

Los nombres se resuelven con el buscador de Sofascore igual que los partidos:
puedes pasar el nombre, el id numérico o —para las ligas— un alias conocido
(``"champions"``, ``"premier"``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import find_league
from .client import SofascoreClient
from .endpoints import (
    PLAYER_SECTIONS,
    TEAM_SECTIONS,
    TOURNAMENT_SECTIONS,
    Section,
    resolve_sections,
)
from .errors import MatchNotFound
from .report import UNAVAILABLE, BaseReport, SectionResult, run_all
from .resolve import parecido

#: Qué catálogo y qué hueco de ruta le toca a cada tipo de entidad.
TIPOS: dict[str, tuple[dict[str, Section], str, str]] = {
    "team": (TEAM_SECTIONS, "team_id", "team"),
    "player": (PLAYER_SECTIONS, "player_id", "player"),
    "tournament": (TOURNAMENT_SECTIONS, "tournament_id", "uniqueTournament"),
}


@dataclass
class EntityReport(BaseReport):
    """Informe de un equipo, un jugador o una competición."""

    kind: str = ""
    entity_id: int = 0
    name: str = ""

    @property
    def profile(self) -> dict:
        """La ficha (la sección ``profile``), o un diccionario vacío."""
        return self.get("profile") or {}

    def to_dict(self, include_data: bool = True) -> dict:
        return {
            "tipo": self.kind,
            "id": self.entity_id,
            "nombre": self.name,
            "meta": self.meta,
            "resumen": self.resumen_estados(),
            "secciones": {
                nombre: resultado.to_dict(include_data=include_data)
                for nombre, resultado in self.sections.items()
            },
        }

    #: Cómo se llama cada tipo cuando hay que enseñárselo a alguien.
    ETIQUETAS = {"team": "equipo", "player": "jugador", "tournament": "competición"}

    def summary(self) -> str:
        etiqueta = self.ETIQUETAS.get(self.kind, self.kind)
        cabecera = f"{etiqueta}: {self.name or self.entity_id} (id={self.entity_id})"
        return "\n".join([cabecera, "", *self.lineas_estado()])


def find_entity(
    cliente: SofascoreClient,
    consulta: str | int,
    kind: str,
    min_score: float = 0.4,
) -> dict:
    """Encuentra un equipo, jugador o competición por nombre o por id.

    Para las competiciones se prueba primero el catálogo de ligas conocidas
    (``"laliga"``, ``"champions"``...), que evita una búsqueda y siempre acierta.

    El buscador de Sofascore devuelve de todo y no siempre en el orden que
    esperas, así que los candidatos se puntúan por parecido con lo que has
    escrito y se queda el mejor. Si ninguno se parece lo suficiente, mejor
    decirlo que devolver el primero que pasaba por ahí.
    """
    if kind not in TIPOS:
        raise ValueError(f"Tipo desconocido: '{kind}'. Usa: {', '.join(TIPOS)}")
    texto = str(consulta).strip()
    if not texto:
        raise MatchNotFound("La consulta está vacía.")

    if texto.isdigit():
        return {"id": int(texto), "name": ""}

    if kind == "tournament":
        conocida = find_league(texto)
        if conocida:
            # Sin nombre: el informe pondrá el de verdad al traer la ficha.
            return {"id": conocida, "name": ""}

    _, _, tipo_api = TIPOS[kind]
    candidatos: list[tuple[float, dict]] = []
    for resultado in cliente.search(texto):
        if resultado.get("type") != tipo_api:
            continue
        entidad = resultado.get("entity") or {}
        if not entidad.get("id"):
            continue
        nombres = [entidad.get("name", ""), entidad.get("shortName", ""),
                   (entidad.get("slug") or "").replace("-", " ")]
        candidatos.append((max(parecido(n, texto) for n in nombres), entidad))

    candidatos.sort(key=lambda par: -par[0])
    if not candidatos or candidatos[0][0] < min_score:
        raise MatchNotFound(
            f"No he encontrado ningún {kind} para '{texto}'. "
            "Prueba con el nombre completo o pasa el id."
        )
    return candidatos[0][1]


def temporada_mas_reciente(indice: Any) -> dict[str, int]:
    """Del índice de temporadas de un jugador, la competición y temporada más recientes.

    La API devuelve el índice agrupado por competición, y dentro de cada una las
    temporadas de la más nueva a la más vieja. Se coge la primera de la primera,
    que es la temporada en curso en su liga principal.

    Se lee con cuidado: si la forma no es la esperada, se devuelve vacío y la
    sección queda como no disponible, que es mejor que reventar.
    """
    if isinstance(indice, dict):
        grupos = indice.get("uniqueTournamentSeasons") or indice.get("seasons") or []
    elif isinstance(indice, list):
        grupos = indice
    else:
        return {}

    for grupo in grupos:
        if not isinstance(grupo, dict):
            continue
        torneo = (grupo.get("uniqueTournament") or {}).get("id")
        temporadas = grupo.get("seasons") or []
        if not torneo or not temporadas:
            continue
        primera = temporadas[0] if isinstance(temporadas[0], dict) else {}
        if primera.get("id"):
            return {"tournament_id": int(torneo), "season_id": int(primera["id"])}
    return {}


def build_entity_report(
    cliente: SofascoreClient,
    kind: str,
    entity: dict | int,
    sections: list[str] | None = None,
    include_plus: bool = True,
    concurrency: int | None = None,
    derivar: Any = None,
    **contexto: Any,
) -> EntityReport:
    """Construye el informe de un equipo, jugador o competición.

    ``contexto`` aporta los ids extra que necesitan algunas secciones
    (``season_id``, ``tournament_id``). Las que los necesiten y no los tengan se
    marcan como no disponibles, con el motivo escrito: nunca revientan.

    ``derivar`` es la escapatoria a ese "no los tengan": una función que, con el
    informe ya montado, saca esos ids de lo que sí ha llegado. Sirve para pedir
    en una segunda tanda lo que en la primera no se podía.
    """
    catalogo, clave_id, _ = TIPOS[kind]
    ficha = entity if isinstance(entity, dict) else {"id": int(entity)}
    entity_id = int(ficha.get("id"))
    hilos = cliente.settings.concurrency if concurrency is None else concurrency

    elegidas = resolve_sections(
        sections, include_plus=include_plus, catalogo=catalogo, base="profile"
    )
    ids: dict[str, Any] = {clave_id: entity_id, **{k: v for k, v in contexto.items() if v}}

    informe = EntityReport(
        kind=kind,
        entity_id=entity_id,
        name=ficha.get("name", "") or ficha.get("shortName", ""),
        meta={
            "secciones_pedidas": [s.name for s in elegidas],
            "contexto": {k: v for k, v in ids.items() if k != clave_id},
            "credenciales_plus": cliente.has_plus,
        },
    )

    tareas = []
    for seccion in elegidas:
        faltan = [n for n in seccion.needs if not ids.get(n)]
        if faltan:
            informe.sections[seccion.name] = SectionResult(
                name=seccion.name,
                scope=seccion.scope,
                status=UNAVAILABLE,
                endpoint=seccion.path,
                description=seccion.description,
                error=f"Falta {', '.join(faltan)} para poder pedirla.",
            )
            continue
        tareas.append((seccion, lambda sec: cliente.entity_section(sec, **ids)))

    for resultado in run_all(tareas, hilos):
        informe.sections[resultado.name] = resultado

    # Segunda tanda: las que faltaban por no tener los ids, si ahora se pueden
    # deducir de lo que ha llegado.
    pendientes = [s for s in elegidas if informe.sections[s.name].status == UNAVAILABLE
                  and any(not ids.get(n) for n in s.needs)]
    if pendientes and derivar is not None:
        deducidos = derivar(informe) or {}
        if deducidos:
            ids.update(deducidos)
            informe.meta["contexto"] = {k: v for k, v in ids.items() if k != clave_id}
            segunda = [(s, lambda sec: cliente.entity_section(sec, **ids))
                       for s in pendientes if all(ids.get(n) for n in s.needs)]
            for resultado in run_all(segunda, hilos):
                informe.sections[resultado.name] = resultado

    informe.reordenar([s.name for s in elegidas])
    if not informe.name:
        informe.name = (informe.profile or {}).get("name", "") or str(entity_id)
    return informe


def build_team_report(cliente: SofascoreClient, consulta: str | int, **kwargs) -> EntityReport:
    """Informe de un equipo, resolviendo el nombre si hace falta."""
    return build_entity_report(cliente, "team", find_entity(cliente, consulta, "team"), **kwargs)


def build_player_report(cliente: SofascoreClient, consulta: str | int, **kwargs) -> EntityReport:
    """Informe de un jugador, resolviendo el nombre si hace falta.

    Sus estadísticas de temporada necesitan saber *de qué* liga y temporada, y
    eso no lo sabes de antemano. Como el propio informe trae el índice de
    temporadas del jugador, de ahí se saca la más reciente y se piden solas.
    """
    kwargs.setdefault("derivar", lambda informe: temporada_mas_reciente(
        informe.get("season_index")
    ))
    return build_entity_report(
        cliente, "player", find_entity(cliente, consulta, "player"), **kwargs
    )


def build_tournament_report(
    cliente: SofascoreClient,
    consulta: str | int,
    season_id: int | None = None,
    **kwargs,
) -> EntityReport:
    """Informe de una competición.

    Sin ``season_id`` se usa la temporada en curso, que es lo que quiere el 90%
    de las veces quien escribe ``sofascore league laliga``.
    """
    ficha = find_entity(cliente, consulta, "tournament")
    tournament_id = int(ficha["id"])
    if season_id is None:
        try:
            season_id = cliente.latest_season_id(tournament_id)
        except Exception:  # noqa: BLE001 - sin temporada el informe sigue, más corto
            season_id = None
    return build_entity_report(
        cliente, "tournament", ficha, season_id=season_id, **kwargs
    )
