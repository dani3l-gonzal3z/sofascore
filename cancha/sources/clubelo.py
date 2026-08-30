"""ClubElo: la fuerza real de un club, en un número.

`clubelo.com <http://clubelo.com>`_ mantiene un Elo de más de 600 clubes
europeos desde 1939, actualizado partido a partido. Es la referencia para dos
preguntas que las estadísticas de un partido no contestan:

* ¿cuánto valía de verdad ganar ahí?
* ¿este equipo está mejor o peor que hace seis meses?

Su API sirve CSV plano, sin claves ni límites raros, así que es la fuente más
sencilla de todas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..errors import NotFound
from .base import Fuente, _numero, registrar


@registrar
@dataclass
class ClubElo(Fuente):
    """Clasificación Elo de clubes, por fecha o por equipo."""

    NOMBRE = "clubelo"

    nombre: str = "clubelo"
    # Su documentación dice http, pero https funciona y es lo que debe
    # intentarse primero; el http queda de reserva.
    base_url: str = "https://api.clubelo.com"
    urls_alternativas: tuple[str, ...] = ("http://api.clubelo.com",)
    rate_limit: float = 2.0
    #: Tarda lo suyo en contestar: 15 segundos se le quedan cortos.
    timeout: float = 30.0
    #: Con el transporte que imita a Chrome no contestaba ni por http ni por
    #: https: treinta segundos y cero bytes. Es una API pública que sirve CSV,
    #: sin anti-bot que sortear, así que se le habla con urllib y en paz.
    transporte_preferido: str = "urllib"
    #: El Elo cambia como mucho una vez al día.
    ttl: int = 12 * 3600
    descripcion: str = (
        "Elo de clubes europeos desde 1939, actualizado partido a partido. "
        "Sirve para saber cuánto vale de verdad un rival y cómo evoluciona un equipo."
    )
    headers: dict[str, str] = field(default_factory=dict)

    # --- consultas ---

    def por_fecha(self, fecha: str | None = None) -> list[dict]:
        """La clasificación entera en una fecha (``AAAA-MM-DD``; por defecto, hoy).

        Los valores anteriores a 1960 son provisionales, según la propia fuente.
        """
        dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filas = self.csv(f"/{dia}")
        return [self._fila(f) for f in filas]

    def equipo(self, nombre: str) -> list[dict]:
        """El histórico completo de un club, en tramos con su Elo.

        El nombre es el que usa ClubElo (``Real Madrid``, ``Barcelona``,
        ``Man City``). Si no lo encuentras, míralo en :meth:`por_fecha`.
        """
        limpio = nombre.strip().replace(" ", "")
        filas = self.csv(f"/{limpio}")
        historico = [self._fila(f) for f in filas]
        if not historico:
            raise NotFound(404, self.url(f"/{limpio}"), f"Sin Elo para '{nombre}'.")
        return historico

    def actual(self, nombre: str) -> dict | None:
        """El Elo de hoy de un club: el último tramo de su histórico."""
        historico = self.equipo(nombre)
        return historico[-1] if historico else None

    def top(self, cuantos: int = 20, fecha: str | None = None,
            pais: str | None = None) -> list[dict]:
        """Los mejores del ranking, opcionalmente de un solo país."""
        filas = self.por_fecha(fecha)
        if pais:
            filas = [f for f in filas if (f.get("pais") or "").upper() == pais.upper()]
        con_puesto = [f for f in filas if isinstance(f.get("puesto"), int)]
        con_puesto.sort(key=lambda f: f["puesto"])
        return con_puesto[:cuantos]

    def comparar(self, local: str, visitante: str) -> dict:
        """Enfrenta el Elo de dos clubes y estima quién parte por delante.

        La fórmula es la de Elo de toda la vida: cada 100 puntos de diferencia
        valen algo más de tres cuartos de probabilidad. No cuenta lesiones, ni
        campo, ni el estado de forma — es el punto de partida, no la conclusión.
        """
        uno, otro = self.actual(local), self.actual(visitante)
        if not (uno and otro):
            raise NotFound(404, "clubelo", "No hay Elo de alguno de los dos equipos.")
        diferencia = (uno["elo"] or 0) - (otro["elo"] or 0)
        esperado = 1 / (1 + 10 ** (-diferencia / 400))
        return {
            "local": {"equipo": uno["equipo"], "elo": uno["elo"], "puesto": uno.get("puesto")},
            "visitante": {"equipo": otro["equipo"], "elo": otro["elo"],
                          "puesto": otro.get("puesto")},
            "diferencia_elo": round(diferencia, 1),
            "probabilidad_local": round(esperado, 3),
            "nota": "Elo puro: no cuenta campo, lesiones ni estado de forma.",
        }

    # --- traducción ---

    @staticmethod
    def _fila(fila: dict) -> dict:
        """Del CSV de ClubElo a nombres que se entiendan."""
        return {
            "puesto": _numero(fila.get("Rank")),
            "equipo": fila.get("Club"),
            "pais": fila.get("Country"),
            "nivel": _numero(fila.get("Level")),
            "elo": _numero(fila.get("Elo")),
            "desde": fila.get("From"),
            "hasta": fila.get("To"),
        }


__all__ = ["ClubElo"]
