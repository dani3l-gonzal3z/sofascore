"""Una sesión de análisis: pagar una vez por lo que se pregunta varias.

Cuando una IA analiza un partido no hace una pregunta, hace ocho: el resumen,
las estadísticas, los tiros, quién jugó, la cronología… Sin nada que las una,
cada herramienta resuelve el partido otra vez y vuelve a pedir las mismas
secciones. La caché en disco tapa el coste en red, pero no el trabajo repetido
ni la espera del limitador de peticiones.

La :class:`Sesion` es lo que faltaba: se queda con los partidos ya resueltos y
con las secciones ya traídas, y **solo pide lo que aún no tiene**. Pedir
``statistics`` y luego ``shotmap`` del mismo partido trae una sección cada vez,
no dos informes enteros.

    sesion = Sesion()
    sesion.informe("Real Madrid vs Barcelona", ["statistics"])
    sesion.informe("Real Madrid vs Barcelona", ["shotmap"])   # reaprovecha todo

Es de usar y tirar, para una conversación o un análisis. No es una caché
compartida entre procesos: eso ya lo hace :mod:`cancha.cache`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import SofascoreClient
from .config import Settings
from .endpoints import resolve_sections
from .match import MatchReport, build_report
from .models import Event
from .resolve import Resolution, resolve_event


@dataclass
class Sesion:
    """Sostiene el trabajo ya hecho para no repetirlo."""

    cliente: SofascoreClient | None = None
    settings: Settings | None = None
    #: Fichero de la memoria. Se abre la primera vez que hace falta.
    ruta_almacen: str = "datos/cancha.db"
    #: Cuántas veces se ha evitado repetir trabajo. Para poder demostrarlo.
    reutilizados: int = 0

    _resoluciones: dict[str, Resolution] = field(default_factory=dict, repr=False)
    _informes: dict[int, MatchReport] = field(default_factory=dict, repr=False)
    _propia: bool = field(default=False, repr=False)
    _almacen: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.cliente is None:
            self.cliente = SofascoreClient(self.settings or Settings.from_env())
            self._propia = True

    # --- contexto ---

    def __enter__(self) -> Sesion:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def almacen(self):
        """La memoria local, abierta solo si alguien la pide."""
        if self._almacen is None:
            from .almacen import Almacen

            self._almacen = Almacen(self.ruta_almacen)
        return self._almacen

    def close(self) -> None:
        if self._almacen is not None:
            self._almacen.close()
            self._almacen = None
        if self._propia and self.cliente is not None:
            self.cliente.close()

    # --- partidos ---

    def resolucion(self, partido: str | int, fecha: str | None = None) -> Resolution:
        """Resuelve un partido, recordando la resolución entera.

        Se guarda la resolución y no solo el partido elegido porque los
        candidatos y el aviso también valen: quien pregunte "¿cuál de todos?"
        no debería pagar otra búsqueda.

        La consulta se recuerda tal cual se escribió: preguntar dos veces por
        "Real Madrid vs Barcelona" no vuelve a buscar.
        """
        clave = f"{partido}|{fecha or ''}"
        if clave in self._resoluciones:
            self.reutilizados += 1
            return self._resoluciones[clave]
        resolucion = resolve_event(self.cliente, partido, date=fecha)
        self._resoluciones[clave] = resolucion
        # Un id ya resuelto vale también si luego lo piden por id.
        self._resoluciones.setdefault(f"{resolucion.event.id}|", resolucion)
        return resolucion

    def evento(self, partido: str | int | Event, fecha: str | None = None) -> Event:
        """El partido, ya resuelto. Un :class:`Event` se devuelve tal cual."""
        if isinstance(partido, Event):
            return partido
        return self.resolucion(partido, fecha).event

    def informe(
        self,
        partido: str | int | Event,
        secciones: list[str] | None = None,
        fecha: str | None = None,
        **opciones,
    ) -> MatchReport:
        """El informe de un partido, trayendo solo las secciones que falten."""
        evento = self.evento(partido, fecha)
        pedidas = [s.name for s in resolve_sections(secciones, sport=evento.sport)]

        guardado = self._informes.get(evento.id)
        if guardado is None:
            informe = build_report(self.cliente, evento, sections=secciones, **opciones)
            self._informes[evento.id] = informe
            return informe

        faltan = [n for n in pedidas if n not in guardado.sections]
        if not faltan:
            self.reutilizados += 1
            return guardado

        # Solo lo que falta: lo demás ya está pagado.
        nuevo = build_report(self.cliente, evento, sections=faltan, **opciones)
        for nombre, resultado in nuevo.sections.items():
            guardado.sections.setdefault(nombre, resultado)
        guardado.meta["secciones_pedidas"] = sorted(guardado.sections)
        return guardado

    def olvidar(self, partido: str | int | Event | None = None) -> None:
        """Tira lo guardado, de un partido o de todo.

        Hace falta para un partido en juego: ahí los datos cambian cada minuto
        y reaprovecharlos sería justo lo contrario de lo que quieres.
        """
        if partido is None:
            self._resoluciones.clear()
            self._informes.clear()
            return
        if isinstance(partido, Event):
            evento = partido
        else:
            guardada = self._resoluciones.get(f"{partido}|")
            evento = guardada.event if guardada else None
        if evento is not None:
            self._informes.pop(evento.id, None)
            for clave, resolucion in list(self._resoluciones.items()):
                if resolucion.event.id == evento.id:
                    self._resoluciones.pop(clave, None)

    # --- qué hay dentro ---

    def estado(self) -> dict:
        """Qué se está reaprovechando, para ``--debug`` y para los tests."""
        return {
            "partidos_resueltos": len({r.event.id for r in self._resoluciones.values()}),
            "informes": {
                informe.event.id: sorted(informe.sections)
                for informe in self._informes.values()
            },
            "trabajo_reutilizado": self.reutilizados,
            "peticiones": self.cliente.stats.as_dict() if self.cliente else {},
        }


__all__ = ["Sesion"]
