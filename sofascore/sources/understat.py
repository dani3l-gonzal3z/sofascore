"""Understat: un segundo modelo de xG con el que contrastar.

`understat.com <https://understat.com>`_ publica goles esperados disparo a
disparo para las cinco grandes ligas y la rusa. Su valor no es repetir lo que
ya da Sofascore, sino **discrepar**: son dos modelos distintos entrenados con
datos distintos, y donde no se ponen de acuerdo suele haber algo que mirar.

Ya no hace falta scrapear su HTML: sirve JSON directamente.

* ``/getStatData`` — las ligas y temporadas que cubre.
* ``/getLeagueData/{liga}/{año}`` — partidos, equipos y jugadores de una temporada.
* ``/getMatchData/{id}`` — los disparos de un partido, con su xG.

Un aviso: pide una cookie de sesión que se consigue visitando su portada. El
transporte con ``curl_cffi`` la conserva; con ``urllib`` a secas puede que no,
y entonces responda 403. Es otra razón para tener ``curl_cffi`` instalado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import NotFound
from .base import Fuente, _numero, registrar

#: Los identificadores que usa Understat para cada liga.
LIGAS = {
    "epl": "EPL",
    "premier": "EPL",
    "laliga": "La_liga",
    "la liga": "La_liga",
    "bundesliga": "Bundesliga",
    "serie a": "Serie_A",
    "seriea": "Serie_A",
    "ligue 1": "Ligue_1",
    "ligue1": "Ligue_1",
    "rfpl": "RFPL",
}

#: Sus enumerados, en cristiano.
SITUACIONES = {
    "OpenPlay": "jugada abierta",
    "FromCorner": "córner",
    "SetPiece": "balón parado",
    "DirectFreekick": "falta directa",
    "Penalty": "penalti",
}
PARTES = {
    "RightFoot": "pie derecho",
    "LeftFoot": "pie izquierdo",
    "Head": "cabeza",
    "OtherBodyParts": "otra",
}
RESULTADOS = {
    "Goal": "gol",
    "OwnGoal": "gol en propia",
    "BlockedShot": "bloqueado",
    "SavedShot": "parada",
    "MissedShots": "fuera",
    "ShotOnPost": "al palo",
}


@registrar
@dataclass
class Understat(Fuente):
    """Goles esperados disparo a disparo, de un modelo independiente."""

    NOMBRE = "understat"

    nombre: str = "understat"
    base_url: str = "https://understat.com"
    #: No es una API pública: se va despacio por educación.
    rate_limit: float = 1.0
    ttl: int = 7 * 24 * 3600
    descripcion: str = (
        "xG disparo a disparo de las cinco grandes ligas y la rusa, de un modelo "
        "distinto al de Sofascore. Sirve para contrastar: donde discrepan, hay algo."
    )
    headers: dict[str, str] = field(
        default_factory=lambda: {"X-Requested-With": "XMLHttpRequest"}
    )

    def arrancar(self) -> None:
        """Visita la portada para que la sesión coja su cookie."""
        self.texto("/", ttl=3600)

    # --- consultas ---

    def ligas(self) -> Any:
        """Las ligas y temporadas que cubre."""
        return self.json("/getStatData")

    def temporada(self, liga: str, año: int | str) -> dict:
        """Partidos, equipos y jugadores de una liga en una temporada.

        ``liga`` acepta el identificador de Understat (``EPL``, ``La_liga``) o
        un alias (``premier``, ``laliga``). ``año`` es el de inicio: 2024 para
        la temporada 24/25.
        """
        datos = self.json(f"/getLeagueData/{self.slug(liga)}/{año}")
        return {
            "partidos": datos.get("dates") or [],
            "jugadores": datos.get("players") or [],
            "equipos": datos.get("teams") or {},
        }

    def partido(self, match_id: int | str) -> dict:
        """Los datos de un partido: disparos y alineaciones con su xG."""
        datos = self.json(f"/getMatchData/{int(match_id)}")
        if not datos or "shots" not in datos:
            raise NotFound(404, f"/getMatchData/{match_id}", "Understat no tiene ese partido.")
        return datos

    def tiros(self, match_id: int | str) -> list[dict]:
        """Los disparos de un partido, aplanados y en orden."""
        datos = self.partido(match_id)
        disparos = datos.get("shots") or {}
        filas = []
        for lado in ("h", "a"):
            for tiro in disparos.get(lado, []) or []:
                filas.append({
                    "minuto": _numero(tiro.get("minute")),
                    "jugador": tiro.get("player"),
                    "jugador_id": _numero(tiro.get("player_id")),
                    "equipo": tiro.get("h_team") if lado == "h" else tiro.get("a_team"),
                    "local": lado == "h",
                    "xg": _numero(tiro.get("xG")),
                    "resultado": RESULTADOS.get(tiro.get("result"), tiro.get("result")),
                    "situacion": SITUACIONES.get(tiro.get("situation"), tiro.get("situation")),
                    "parte_cuerpo": PARTES.get(tiro.get("shotType"), tiro.get("shotType")),
                    "asistio": tiro.get("player_assisted"),
                    "accion_previa": tiro.get("lastAction"),
                    "x": _numero(tiro.get("X")),
                    "y": _numero(tiro.get("Y")),
                })
        filas.sort(key=lambda f: f["minuto"] or 0)
        return filas

    def xg_partido(self, match_id: int | str) -> dict:
        """El xG total de cada equipo en un partido, sumando sus disparos."""
        filas = self.tiros(match_id)
        if not filas:
            raise NotFound(404, str(match_id), "Sin disparos para ese partido.")
        totales: dict[str, dict] = {}
        for fila in filas:
            equipo = fila["equipo"] or ("local" if fila["local"] else "visitante")
            bloque = totales.setdefault(equipo, {"xg": 0.0, "tiros": 0, "goles": 0})
            bloque["xg"] += fila["xg"] or 0
            bloque["tiros"] += 1
            bloque["goles"] += 1 if fila["resultado"] == "gol" else 0
        for bloque in totales.values():
            bloque["xg"] = round(bloque["xg"], 2)
        return {"fuente": "understat", "partido_id": int(match_id), "equipos": totales}

    def buscar_partido(self, liga: str, año: int | str, local: str,
                       visitante: str) -> dict | None:
        """Encuentra el id de Understat de un partido por equipos y temporada.

        Understat numera sus partidos aparte, así que para cruzar sus datos con
        los de Sofascore hay que emparejarlos por nombre. Se compara sin
        acentos ni mayúsculas y admite nombres parciales, que cada fuente
        escribe los equipos a su manera.
        """
        from ..resolve import parecido

        mejor, mejor_puntos, invertido = None, 0.0, False
        for partido in self.temporada(liga, año)["partidos"]:
            casa = ((partido.get("h") or {}).get("title")) or ""
            fuera = ((partido.get("a") or {}).get("title")) or ""
            directo = (parecido(casa, local) + parecido(fuera, visitante)) / 2
            # Quien es local aquí puede ser visitante allí (o venir del revés en
            # la consulta): se prueban los dos órdenes y se anota cuál encajó.
            inverso = (parecido(casa, visitante) + parecido(fuera, local)) / 2
            puntos = max(directo, inverso)
            if puntos > mejor_puntos:
                mejor, mejor_puntos, invertido = partido, puntos, inverso > directo
        if mejor and mejor_puntos >= 0.6:
            return {
                "id": _numero(mejor.get("id")),
                "local": (mejor.get("h") or {}).get("title"),
                "visitante": (mejor.get("a") or {}).get("title"),
                "fecha": (mejor.get("datetime") or "")[:10],
                "encaje": round(mejor_puntos, 2),
                "orden_invertido": invertido,
            }
        return None

    @staticmethod
    def slug(liga: str) -> str:
        """Traduce un nombre de liga al identificador de Understat."""
        texto = " ".join(str(liga).lower().split())
        if texto in LIGAS:
            return LIGAS[texto]
        sin_espacios = texto.replace(" ", "")
        if sin_espacios in LIGAS:
            return LIGAS[sin_espacios]
        # Puede que ya venga en su formato (EPL, La_liga...).
        return str(liga)


__all__ = ["Understat", "LIGAS", "SITUACIONES", "PARTES", "RESULTADOS"]
