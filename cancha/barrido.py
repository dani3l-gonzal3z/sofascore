"""El barrido: llenar la memoria sin volver a pedir lo que ya está.

Para saber cómo juega un equipo hay que haber visto sus últimos partidos. Para
saber si un jugador lleva una mala racha, también. Y para eso no vale pedir las
cosas de una en una cuando hacen falta: hay que **tenerlas antes**.

Esto es lo que las trae. Dos movimientos:

1. **La agenda** — qué se juega hoy (o el día que digas) en las ligas que te
   importen. Una petición.
2. **El relleno** — de cada equipo que juega, sus últimos partidos con el
   detalle completo, saltándose los que ya estén guardados.

El primer barrido es caro: un par de miles de peticiones para las ligas
grandes. Los siguientes casi no cuestan, porque solo entra lo nuevo. Y se puede
cortar por donde sea: al reanudar sigue donde lo dejó, porque lo que decide qué
pedir es lo que hay en la base, no un contador.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .almacen import Almacen
from .catalog import LEAGUES
from .client import SofascoreClient
from .errors import SofascoreError
from .match import build_report
from .models import Event

#: Lo que hace falta guardar de un partido para poder analizarlo después.
#: El mapa de tiros y las alineaciones son los caros; sin ellos no hay ni xG ni
#: rendimiento por jugador, que es justo lo que se quiere mirar.
SECCIONES = ["statistics", "lineups", "incidents", "shotmap"]

#: Grupos de competiciones, para no tener que escribir ids.
GRUPOS: dict[str, tuple[str, ...]] = {
    "grandes": (
        "Spain La Liga", "England Premier League", "Italy Serie A",
        "Germany Bundesliga", "France Ligue 1",
    ),
    "uefa": (
        "UEFA Champions League", "UEFA Europa League", "UEFA Conference League",
    ),
    "europeas": (
        "Netherlands Eredivisie", "Portugal Primeira Liga", "Turkiye Super Lig",
        "England EFL Championship", "Spain La Liga 2", "Italy Serie B",
        "Germany 2.Bundesliga", "France Ligue 2", "Ukraine Premier League",
        "Bulgaria Parva Liga",
    ),
    "americas": (
        "USA MLS", "Mexico Liga MX Apertura", "Mexico Liga MX Clausura",
        "Argentina Liga Profesional", "CONMEBOL Copa Libertadores", "Peru Liga 1",
    ),
    "arabia": ("Saudi Arabia Pro League",),
}

#: Lo que se barre si no dices otra cosa: lo que pediste tú.
POR_DEFECTO = ("grandes", "uefa", "americas", "arabia", "europeas")


def ligas_de(grupos: tuple[str, ...] | list[str] | None = None) -> dict[int, str]:
    """Los ids de competición de unos grupos. Sin grupos, los de por defecto."""
    elegidos = tuple(grupos) if grupos else POR_DEFECTO
    salida: dict[int, str] = {}
    for grupo in elegidos:
        nombres = GRUPOS.get(grupo)
        if nombres is None:
            # Puede ser el nombre de una liga suelta, o su id.
            if str(grupo).isdigit():
                salida[int(grupo)] = str(grupo)
                continue
            from .catalog import find_league

            identificador = find_league(grupo)
            if identificador:
                salida[identificador] = grupo
            continue
        for nombre in nombres:
            if nombre in LEAGUES:
                salida[LEAGUES[nombre]] = nombre
    return salida


@dataclass
class Progreso:
    """Lo que va pasando durante un barrido, para poder enseñarlo y pararlo."""

    partidos_vistos: int = 0
    partidos_guardados: int = 0
    ya_estaban: int = 0
    fallos: int = 0
    peticiones: int = 0
    detalle: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "partidos_vistos": self.partidos_vistos,
            "guardados": self.partidos_guardados,
            "ya_estaban": self.ya_estaban,
            "fallos": self.fallos,
            "peticiones": self.peticiones,
        }


def agenda(
    cliente: SofascoreClient,
    fecha: str | None = None,
    grupos: tuple[str, ...] | list[str] | None = None,
) -> list[Event]:
    """Qué se juega ese día en las competiciones elegidas.

    Hay dos caminos y se usan en este orden:

    1. **El calendario global** del día: una sola petición para todo el fútbol
       del mundo y el filtro se hace aquí. Es lo barato.
    2. **Liga por liga**, si el primero no contesta. Cuesta un par de
       peticiones por competición, pero funciona.

    El segundo existe porque el primero devolvió 404 en una ejecución real
    —y llevaba tiempo fallando en silencio, que es peor—. Cuando una ruta que
    no controlamos se cae, tener otra por la que ir vale más que tener la
    barata.
    """
    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ligas = ligas_de(grupos)

    try:
        eventos = [Event.from_api(e) for e in cliente.scheduled_events(dia)]
        if eventos:
            return [e for e in eventos if e.unique_tournament_id in ligas]
    except SofascoreError:
        pass
    return agenda_por_liga(cliente, dia, ligas)


def agenda_por_liga(
    cliente: SofascoreClient,
    fecha: str,
    ligas: dict[int, str],
) -> list[Event]:
    """La agenda preguntando a cada competición por sus próximos partidos.

    Más caro que el calendario global, pero se apoya en rutas que sí sabemos
    que responden. Los partidos ya jugados de ese día se piden también, para
    que un barrido de un día pasado no salga vacío.
    """
    salida: list[Event] = []
    for liga_id in ligas:
        try:
            temporada = cliente.latest_season_id(liga_id)
        except SofascoreError:
            continue
        if not temporada:
            continue
        for cuando in ("next", "last"):
            try:
                datos = cliente.get(
                    f"/unique-tournament/{liga_id}/season/{temporada}/events/{cuando}/0",
                    ttl=1800,
                )
            except SofascoreError:
                continue
            for crudo in (datos or {}).get("events", []) or []:
                evento = Event.from_api(crudo)
                if evento.date == fecha:
                    salida.append(evento)
    # Un partido puede salir por las dos vías: se queda uno.
    unicos = {e.id: e for e in salida}
    return sorted(unicos.values(), key=lambda e: e.start_timestamp or 0)


def guardar_partido(
    cliente: SofascoreClient,
    almacen: Almacen,
    evento: Event,
    progreso: Progreso,
    forzar: bool = False,
) -> bool:
    """Trae el detalle de un partido y lo guarda. Devuelve si ha hecho falta pedirlo.

    Un partido ya guardado no se vuelve a pedir: es lo que hace que el barrido
    se pueda repetir y reanudar sin coste.
    """
    if not evento.is_finished:
        # Uno por jugar no tiene estadísticas; se guarda la cabecera y ya.
        almacen.guardar_evento(evento)
        return False
    if not forzar and almacen.tiene(evento.id):
        progreso.ya_estaban += 1
        return False
    try:
        antes = cliente.stats.requests
        informe = build_report(cliente, evento, sections=SECCIONES)
        almacen.guardar_informe(informe)
        progreso.peticiones += cliente.stats.requests - antes
        progreso.partidos_guardados += 1
        return True
    except SofascoreError as exc:
        progreso.fallos += 1
        progreso.detalle.append(f"{evento.id}: {exc}")
        return False


def rellenar_equipo(
    cliente: SofascoreClient,
    almacen: Almacen,
    equipo_id: int,
    ultimos: int = 6,
    progreso: Progreso | None = None,
) -> Progreso:
    """Los últimos partidos jugados de un equipo, con detalle, en la base."""
    progreso = progreso or Progreso()
    try:
        crudos = cliente.team_events(equipo_id, when="last")
    except SofascoreError as exc:
        progreso.fallos += 1
        progreso.detalle.append(f"equipo {equipo_id}: {exc}")
        return progreso

    eventos = [Event.from_api(e) for e in crudos]
    eventos = [e for e in eventos if e.is_finished]
    eventos.sort(key=lambda e: e.start_timestamp or 0, reverse=True)
    for evento in eventos[:ultimos]:
        progreso.partidos_vistos += 1
        guardar_partido(cliente, almacen, evento, progreso)
    return progreso


def barrer(
    cliente: SofascoreClient,
    almacen: Almacen,
    fecha: str | None = None,
    grupos: tuple[str, ...] | list[str] | None = None,
    ultimos: int = 6,
    maximo_peticiones: int = 0,
    avisar: Callable[[str], None] | None = None,
) -> dict:
    """El barrido entero: la agenda del día y el historial de quien juega.

    ``maximo_peticiones`` pone un tope para poder probarlo sin gastar una
    mañana entera; ``0`` es sin tope. Cortar por la mitad no rompe nada: lo
    guardado queda guardado y el siguiente barrido sigue por donde falte.
    """
    decir = avisar or (lambda _t: None)
    progreso = Progreso()
    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    partidos = agenda(cliente, dia, grupos)
    decir(f"{len(partidos)} partidos el {dia} en las competiciones elegidas.")
    for evento in partidos:
        almacen.guardar_evento(evento)

    equipos: dict[int, str] = {}
    for evento in partidos:
        for equipo in (evento.home, evento.away):
            if equipo.id:
                equipos[equipo.id] = equipo.name

    decir(f"{len(equipos)} equipos de los que traer sus últimos {ultimos} partidos.")
    for numero, (equipo_id, nombre) in enumerate(sorted(equipos.items(), key=lambda kv: kv[1]), 1):
        if maximo_peticiones and progreso.peticiones >= maximo_peticiones:
            decir(f"Tope de {maximo_peticiones} peticiones alcanzado; lo dejo aquí.")
            break
        decir(f"  [{numero}/{len(equipos)}] {nombre}")
        rellenar_equipo(cliente, almacen, equipo_id, ultimos, progreso)

    almacen.anotar("ultimo_barrido", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    almacen.anotar("ultima_fecha_barrida", dia)
    return {
        "fecha": dia,
        "partidos_del_dia": len(partidos),
        "equipos": len(equipos),
        **progreso.as_dict(),
        "fallos_detalle": progreso.detalle[:10],
    }


def proximos_dias(dias: int = 2) -> list[str]:
    """Las fechas de hoy y los próximos días, para barrer con antelación."""
    hoy = datetime.now(timezone.utc)
    return [(hoy + timedelta(days=n)).strftime("%Y-%m-%d") for n in range(dias)]


__all__ = ["barrer", "agenda", "rellenar_equipo", "guardar_partido", "ligas_de",
           "GRUPOS", "POR_DEFECTO", "SECCIONES", "Progreso"]
