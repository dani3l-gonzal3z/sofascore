"""De «un partido» a un id de evento.

El objetivo del framework es que escribas el partido como lo dirías en voz alta
y él se encargue. Aquí se aceptan cuatro formas de nombrarlo:

* el id numérico (``12345678``);
* la URL de Sofascore (``https://www.sofascore.com/.../#id:12345678``);
* ``"Real Madrid vs Barcelona"`` (con ``--date`` si hay varios);
* cualquier texto libre que la búsqueda de Sofascore entienda.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .client import SofascoreClient
from .errors import AmbiguousMatch, MatchNotFound, SofascoreError
from .models import Event

#: Separadores admitidos entre local y visitante.
SEPARADORES = [" vs ", " vs. ", " v ", " x ", " - ", " – ", " — ", " contra ", " against "]

_PATRONES_ID = [
    re.compile(r"#id[:=](\d{4,})"),
    re.compile(r"[,&?]id[:=](\d{4,})"),
    re.compile(r"/event/(\d{4,})"),
    re.compile(r"sofascore\.com/[^\s]*?/(\d{6,})(?:[/?#]|$)"),
]


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y sin puntuación: para comparar nombres."""
    if not texto:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower()).strip()


def parecido(a: str, b: str) -> float:
    """Similitud 0..1 entre dos nombres, tolerante a prefijos tipo «FC»."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.92
    return SequenceMatcher(None, na, nb).ratio()


def parse_event_id(texto: str) -> int | None:
    """Extrae el id de un evento de un número o de una URL de Sofascore."""
    texto = (texto or "").strip()
    if texto.isdigit():
        return int(texto)
    for patron in _PATRONES_ID:
        encontrado = patron.search(texto)
        if encontrado:
            return int(encontrado.group(1))
    return None


def split_teams(consulta: str) -> tuple[str, str] | None:
    """Parte ``"A vs B"`` en ``("A", "B")`` si encuentra un separador."""
    texto = f" {consulta.strip()} "
    for separador in SEPARADORES:
        if separador in texto.lower():
            indice = texto.lower().index(separador)
            local = texto[:indice].strip()
            visitante = texto[indice + len(separador):].strip()
            if local and visitante:
                return local, visitante
    return None


@dataclass
class Candidate:
    """Un partido candidato con su puntuación."""

    event: Event
    score: float
    reason: str = ""

    def __str__(self) -> str:
        return f"[{self.score:.2f}] {self.event.label} · id={self.event.id}"


@dataclass
class Resolution:
    """Resultado de la resolución: el elegido y sus alternativas."""

    event: Event
    source: str
    candidates: list[Candidate] = field(default_factory=list)
    #: Aviso para el usuario cuando la elección merece una explicación.
    warning: str = ""
    #: Cuántos candidatos ha aportado cada fuente. Para ``--debug``: cuando algo
    #: no aparece, esto dice qué se llegó a consultar y qué devolvió.
    sources: dict[str, int] = field(default_factory=dict)

    @property
    def event_id(self) -> int:
        return self.event.id


def _puntuar(evento: Event, local: str, visitante: str, fecha: str | None) -> tuple[float, str]:
    """Puntúa un evento contra los nombres pedidos (y la fecha, si la hay)."""
    directo = (parecido(evento.home.name, local) + parecido(evento.away.name, visitante)) / 2
    invertido = (parecido(evento.home.name, visitante) + parecido(evento.away.name, local)) / 2
    if invertido > directo:
        puntos, motivo = invertido, "coincidencia con los equipos (orden invertido)"
    else:
        puntos, motivo = directo, "coincidencia con los equipos"
    if fecha:
        if evento.date == fecha:
            puntos += 0.5
            motivo += " y fecha exacta"
        else:
            puntos -= 0.35
            motivo += " pero otra fecha"
    return puntos, motivo


def _recencia(evento: Event) -> float:
    """Distancia en segundos entre el partido y ahora (para desempatar)."""
    momento = evento.kickoff
    if momento is None:
        return float("inf")
    return abs((datetime.now(timezone.utc) - momento).total_seconds())


def _eventos_de_busqueda(cliente: SofascoreClient, consulta: str) -> list[Event]:
    eventos = []
    for resultado in cliente.search(consulta):
        if resultado.get("type") != "event":
            continue
        entidad = resultado.get("entity") or {}
        if entidad.get("id"):
            eventos.append(Event.from_api(entidad))
    return eventos


def _equipos_de_busqueda(cliente: SofascoreClient, nombre: str, limite: int = 3) -> list[dict]:
    equipos = []
    for resultado in cliente.search(nombre):
        if resultado.get("type") != "team":
            continue
        entidad = resultado.get("entity") or {}
        if entidad.get("id"):
            equipos.append(entidad)
        if len(equipos) >= limite:
            break
    return equipos


def _eventos_de_equipo(
    cliente: SofascoreClient, team_id: int, paginas: int = 1
) -> list[Event]:
    """Calendario de un equipo. Cada página son ~30 partidos, del más reciente atrás.

    Con ``paginas=1`` solo se ven los últimos partidos; para buscar un cruce de
    hace temporadas hay que retroceder, que es lo que hace ``paginas`` mayor.
    """
    eventos: list[Event] = []
    for pagina in range(max(1, paginas)):
        try:
            tanda = cliente.team_events(team_id, when="last", page=pagina)
        except SofascoreError:
            break
        if not tanda:
            break
        eventos.extend(Event.from_api(e) for e in tanda)
    try:
        eventos.extend(Event.from_api(e) for e in cliente.team_events(team_id, when="next"))
    except SofascoreError:
        pass
    return eventos


def _paginas_para(date: str | None) -> int:
    """Cuántas páginas de calendario hay que retroceder para llegar a esa fecha.

    Un equipo juega del orden de 50-60 partidos por temporada y cada página trae
    unos 30, así que dos páginas por año cubren de sobra. Se limita a 8 para no
    ponerse a pedir sin fin.
    """
    if not date:
        return 1
    try:
        pedida = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 1
    anos = max(0.0, (datetime.now(timezone.utc) - pedida).days / 365)
    return min(8, 1 + int(anos * 2 + 0.5))


def resolve_event(
    cliente: SofascoreClient,
    consulta: str | int,
    date: str | None = None,
    strict: bool = False,
    min_score: float = 0.55,
) -> Resolution:
    """Convierte una consulta libre en un partido concreto.

    ``date`` (``AAAA-MM-DD``) desempata cuando dos equipos se han cruzado
    muchas veces. Con ``strict=True`` se lanza :class:`AmbiguousMatch` si hay
    empate en vez de elegir el partido más cercano en el tiempo.
    """
    fuentes: dict[str, int] = {}
    consulta_texto = str(consulta).strip()
    if not consulta_texto:
        raise MatchNotFound("La consulta está vacía: dime un partido, un id o una URL.")

    # 1) Id o URL: no hay nada que adivinar.
    event_id = parse_event_id(consulta_texto)
    if event_id:
        evento = cliente.event(event_id)
        if not evento.id:
            raise MatchNotFound(f"No existe ningún partido con id {event_id}.")
        return Resolution(event=evento, source="id")

    equipos = split_teams(consulta_texto)
    candidatos: dict[int, Candidate] = {}

    def registrar(evento: Event, puntos: float, motivo: str, fuente: str = "") -> None:
        if not evento.id:
            return
        if fuente:
            fuentes[fuente] = fuentes.get(fuente, 0) + 1
        previo = candidatos.get(evento.id)
        if previo is None or puntos > previo.score:
            candidatos[evento.id] = Candidate(event=evento, score=puntos, reason=motivo)

    def hay_de_la_fecha() -> bool:
        return bool(date) and any(c.event.date == date for c in candidatos.values())

    # 2) Buscador general de Sofascore.
    fuentes.setdefault("buscador", 0)
    for evento in _eventos_de_busqueda(cliente, consulta_texto):
        if equipos:
            puntos, motivo = _puntuar(evento, equipos[0], equipos[1], date)
        else:
            puntos = max(
                parecido(f"{evento.home.name} {evento.away.name}", consulta_texto),
                parecido(evento.slug.replace("-", " "), consulta_texto),
            )
            motivo = "resultado del buscador"
            if date:
                puntos += 0.5 if evento.date == date else -0.35
        registrar(evento, puntos, motivo, "buscador")

    # 3) Si das fecha, los partidos de ese día son la fuente autoritativa: están
    #    todos, por viejo que sea el cruce. Se consulta SIEMPRE, no como último
    #    recurso —el buscador devuelve encantado el cruce de otro año o de otra
    #    competición, y con un nombre perfecto se cuela por delante del bueno.
    if date:
        # Se apunta el intento aunque no traiga nada: un 0 aquí dice "se
        # preguntó y vino vacío", que no es lo mismo que no haber preguntado.
        fuentes.setdefault("partidos del día", 0)
        try:
            programados = cliente.scheduled_events(date)
        except SofascoreError:
            fuentes["partidos del día (error)"] = fuentes.pop("partidos del día", 0)
            programados = []
        for datos in programados:
            evento = Event.from_api(datos)
            if equipos:
                puntos, _ = _puntuar(evento, equipos[0], equipos[1], None)
            else:
                puntos = parecido(f"{evento.home.name} {evento.away.name}", consulta_texto)
            registrar(evento, puntos + 0.15, f"partidos del {date}", "partidos del día")

    # 4) Si hay dos equipos, mirar su calendario. Retrocediendo lo que haga falta
    #    cuando la fecha pedida es antigua: una sola página son los últimos ~30
    #    partidos y un cruce de hace dos temporadas se queda muy atrás.
    if equipos and not (hay_de_la_fecha() or any(c.score >= 0.9 for c in candidatos.values())):
        local, visitante = equipos
        paginas = _paginas_para(date)
        fuentes.setdefault("calendario", 0)
        for equipo in _equipos_de_busqueda(cliente, local):
            for evento in _eventos_de_equipo(cliente, int(equipo["id"]), paginas=paginas):
                puntos, motivo = _puntuar(evento, local, visitante, date)
                registrar(evento, puntos, f"calendario de {equipo.get('name', local)}: {motivo}",
                          "calendario")
            if hay_de_la_fecha():
                break

    # 5) Y si aún no aparece el día pedido, preguntar por el histórico del cruce:
    #    teniendo cualquier enfrentamiento entre esos dos equipos, la API
    #    devuelve la serie completa. Es una petición y llega donde no llega el
    #    calendario.
    if date and equipos and candidatos and not hay_de_la_fecha():
        mejores = sorted(candidatos.values(), key=lambda c: -c.score)[:2]
        fuentes.setdefault("histórico h2h", 0)
        for candidato in mejores:
            try:
                historico = cliente.h2h_events(candidato.event.id)
            except SofascoreError:
                continue
            for datos in historico:
                evento = Event.from_api(datos)
                puntos, motivo = _puntuar(evento, equipos[0], equipos[1], date)
                registrar(evento, puntos, f"histórico del cruce: {motivo}", "histórico h2h")
            if hay_de_la_fecha():
                break

    viables = [c for c in candidatos.values() if c.score >= min_score]
    aviso = ""

    # 5) La fecha es una condición, no una sugerencia: si has dicho un día y hay
    #    algo ese día, no se elige nada de otro día. Y si no hay nada, se dice.
    if date and viables:
        del_dia = [c for c in viables if c.event.date == date]
        if del_dia:
            viables = del_dia
        else:
            consultado = ", ".join(f"{k}: {v}" for k, v in fuentes.items()) or "nada"
            aviso = (
                f"No he encontrado ningún partido el {date} (consultado — {consultado}). "
                f"Lo que te doy es de otra fecha; compruébalo."
            )

    if not viables:
        raise MatchNotFound(
            f"No he encontrado ningún partido para '{consulta_texto}'"
            + (f" el {date}." if date else ".")
            + " Prueba con los nombres completos de los equipos, añade la fecha "
            "(--date AAAA-MM-DD) o pega la URL del partido."
        )

    viables.sort(key=lambda c: (-c.score, _recencia(c.event)))
    mejor = viables[0]

    if strict and len(viables) > 1 and abs(viables[1].score - mejor.score) < 0.01:
        raise AmbiguousMatch(consulta_texto, [str(c) for c in viables])

    return Resolution(
        event=mejor.event, source=mejor.reason, candidates=viables,
        warning=aviso, sources=fuentes,
    )
