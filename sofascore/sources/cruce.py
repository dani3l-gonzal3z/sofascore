"""Cruzar fuentes: donde discrepan es donde hay algo que mirar.

``soccerdata`` y ``ScraperFC`` te dan una tabla por fuente y el emparejado te lo
comes tú: los equipos se llaman distinto en cada sitio, los partidos llevan ids
distintos y las temporadas se numeran distinto. Aquí eso lo hace el framework.

Lo que sale de aquí es lo que de verdad le sirve a una IA para analizar:

* el mismo partido visto por **dos modelos de xG** independientes, con la
  diferencia calculada — cuando Sofascore dice 1.48 y Understat 2.10, esa
  distancia es información, no ruido;
* la **fuerza real** de los dos equipos según ClubElo, que dice cuánto valía
  ganar ahí;
* y todo con el aviso de qué fuente no ha contestado, sin tumbar el resto.
"""

from __future__ import annotations

from typing import Any

from ..client import SofascoreClient
from ..errors import SofascoreError
from ..match import build_report
from ..models import Event
from ..resolve import resolve_event
from .clubelo import ClubElo
from .understat import Understat

#: De qué competición de Sofascore es cada liga de Understat.
#: Understat solo cubre las cinco grandes; el resto no tiene equivalente.
UNDERSTAT_POR_TORNEO = {
    8: "La_liga",       # LaLiga
    17: "EPL",          # Premier League
    35: "Bundesliga",
    23: "Serie_A",
    34: "Ligue_1",
}


def temporada_de(evento: Event) -> int | None:
    """El año de inicio de la temporada de un partido.

    Understat numera las temporadas por su año de arranque: la 24/25 es 2024.
    Una liga europea empieza en verano, así que de agosto en adelante el año es
    el del propio partido, y de enero a julio es el anterior.
    """
    if not evento.kickoff:
        return None
    momento = evento.kickoff
    return momento.year if momento.month >= 7 else momento.year - 1


def _xg_de_sofascore(informe) -> dict | None:
    """El xG que da Sofascore, del mapa de tiros si está y si no del resumen."""
    tiros = informe.shots()
    if tiros:
        totales = {"local": 0.0, "visitante": 0.0}
        for tiro in tiros:
            lado = "local" if tiro.get("isHome") else "visitante"
            totales[lado] += tiro.get("xg") or 0
        return {k: round(v, 2) for k, v in totales.items()}
    estadistica = informe.statistic("expectedGoals")
    if estadistica:
        try:
            return {"local": float(estadistica.get("home")),
                    "visitante": float(estadistica.get("away"))}
        except (TypeError, ValueError):
            return None
    return None


def contexto_partido(
    cliente: SofascoreClient,
    partido: str | int,
    fecha: str | None = None,
    fuentes: tuple[str, ...] = ("understat", "clubelo"),
) -> dict:
    """Reúne lo que dicen todas las fuentes sobre un mismo partido.

    Ninguna fuente que falle tumba el resultado: cada una deja su estado
    escrito, igual que hacen las secciones de un informe.
    """
    evento = resolve_event(cliente, partido, date=fecha).event
    informe = build_report(cliente, evento, sections=["statistics", "shotmap"])

    salida: dict[str, Any] = {
        "partido": {
            "id": evento.id,
            "local": evento.home.name,
            "visitante": evento.away.name,
            "marcador": evento.scoreline,
            "fecha": evento.date,
            "competicion": evento.tournament,
        },
        "sofascore": {"xg": _xg_de_sofascore(informe), "tiros": len(informe.shots())},
        "fuentes": {},
    }

    if "understat" in fuentes:
        salida["fuentes"]["understat"] = _understat(evento)
    if "clubelo" in fuentes:
        salida["fuentes"]["clubelo"] = _clubelo(evento)

    salida["contraste_xg"] = _contrastar(
        salida["sofascore"].get("xg"),
        (salida["fuentes"].get("understat") or {}).get("xg"),
    )
    return salida


def _understat(evento: Event) -> dict:
    """El mismo partido en Understat, emparejado por equipos y temporada."""
    liga = UNDERSTAT_POR_TORNEO.get(evento.unique_tournament_id or 0)
    if not liga:
        return {"estado": "no_cubierta",
                "nota": f"Understat no cubre '{evento.tournament}'. "
                        f"Solo las cinco grandes ligas."}
    año = temporada_de(evento)
    if not año:
        return {"estado": "sin_fecha", "nota": "El partido no trae fecha de inicio."}

    fuente = Understat()
    try:
        emparejado = fuente.buscar_partido(liga, año, evento.home.name, evento.away.name)
        if not emparejado:
            return {"estado": "no_encontrado",
                    "nota": f"No hay partido equivalente en {liga} {año}."}
        totales = fuente.xg_partido(emparejado["id"])
        return {
            "estado": "ok",
            "partido_id": emparejado["id"],
            "encaje": emparejado["encaje"],
            "equipos": totales["equipos"],
            "xg": _por_lado(totales["equipos"], evento, emparejado),
        }
    except SofascoreError as exc:
        return {"estado": "error", "nota": str(exc)}
    finally:
        fuente.close()


def _por_lado(equipos: dict, evento: Event, emparejado: dict) -> dict | None:
    """Traduce el xG de Understat a 'local' y 'visitante' según Sofascore."""
    from ..resolve import parecido

    salida: dict[str, float] = {}
    for nombre, bloque in equipos.items():
        en_casa = parecido(nombre, evento.home.name)
        fuera = parecido(nombre, evento.away.name)
        salida["local" if en_casa >= fuera else "visitante"] = bloque["xg"]
    return salida or None


def _clubelo(evento: Event) -> dict:
    """La fuerza de los dos equipos según ClubElo."""
    fuente = ClubElo()
    try:
        return {"estado": "ok", **fuente.comparar(evento.home.name, evento.away.name)}
    except SofascoreError as exc:
        return {
            "estado": "error",
            "nota": f"{exc}. ClubElo escribe los nombres a su manera "
                    f"('Man City', 'Inter'): compruébalo con la clasificación.",
        }
    finally:
        fuente.close()


def _contrastar(sofascore: dict | None, understat: dict | None) -> dict:
    """Enfrenta los dos modelos de xG y dice si merece la pena mirarlo."""
    if not (sofascore and understat):
        return {"posible": False,
                "nota": "Hace falta el xG de las dos fuentes para compararlos."}
    filas = {}
    for lado in ("local", "visitante"):
        uno, otro = sofascore.get(lado), understat.get(lado)
        if uno is None or otro is None:
            continue
        filas[lado] = {
            "sofascore": round(uno, 2),
            "understat": round(otro, 2),
            "diferencia": round(otro - uno, 2),
        }
    if not filas:
        return {"posible": False, "nota": "No coinciden los lados de las dos fuentes."}
    mayor = max(abs(f["diferencia"]) for f in filas.values())
    return {
        "posible": True,
        "por_equipo": filas,
        "discrepancia_maxima": mayor,
        "lectura": (
            "Los dos modelos coinciden: el xG es sólido."
            if mayor < 0.3 else
            "Discrepan bastante. Suele pasar con penaltis, remates bloqueados o "
            "tiros muy lejanos, donde cada modelo pondera distinto. Mira los "
            "disparos uno a uno antes de sacar conclusiones."
        ),
    }


__all__ = ["contexto_partido", "temporada_de", "UNDERSTAT_POR_TORNEO"]
