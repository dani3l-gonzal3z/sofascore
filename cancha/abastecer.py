"""Traer todo lo que hace falta para analizar **un** partido, y guardarlo.

El barrido es al por mayor: los partidos del día y el historial de quien juega.
Esto es lo contrario, al detalle: dime un partido y te traigo lo que cuesta
entenderlo —los últimos de cada equipo por separado, lo que han jugado entre
ellos, y lo que ha pitado el árbitro— con todo el detalle y guardado.

Existe porque la alternativa era peor. Sin esto, buscar un partido de mañana
sobre una memoria vacía devolvía «haz un barrido antes», que es pedirle al
usuario que adivine qué barrer. Ahora se trae, se guarda, y la segunda vez
sale gratis.

**Lo que cuesta.** Un partido con detalle completo son seis peticiones. Un
abastecimiento típico son unos cuarenta partidos, así que unas 240 peticiones:
al límite de tres por segundo que trae el cliente, minuto y medio.

**Lo que no cuesta.** La segunda vez, casi nada, y esa es la parte importante.
Los últimos diez del Madrid y los últimos diez del Barça se solapan con los del
resto de su liga, así que a partir del cuarto o quinto análisis de la misma
competición la mayoría ya está guardada. La memoria no crece exponencialmente:
**se satura**, que es justo lo que se quiere de una memoria.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .almacen import Almacen
from .barrido import Progreso, guardar_partido
from .client import SofascoreClient
from .errors import SofascoreError
from .models import Event

#: Cuántos partidos anteriores de cada equipo se traen por defecto. Diez es el
#: número del que habla la gente («sus últimos diez») y da para una media que
#: no es solo la última semana.
ULTIMOS = 10
#: Y cuántos del árbitro, que necesita más muestra: sus tarjetas por partido no
#: significan nada con seis.
ULTIMOS_ARBITRO = 15


@dataclass
class Plan:
    """Qué se va a pedir y cuánto de eso ya está. Se puede mirar antes de pedir."""

    partido: str = ""
    locales: list[Event] = field(default_factory=list)
    visitantes: list[Event] = field(default_factory=list)
    entre_ellos: list[Event] = field(default_factory=list)
    del_arbitro: list[Event] = field(default_factory=list)
    arbitro: str = ""

    @property
    def todos(self) -> list[Event]:
        """Sin repetir: un partido entre los dos sale por tres sitios a la vez."""
        vistos: dict[int, Event] = {}
        for grupo in (self.locales, self.visitantes, self.entre_ellos, self.del_arbitro):
            for evento in grupo:
                vistos.setdefault(evento.id, evento)
        return list(vistos.values())

    def cuentas(self, almacen: Almacen) -> dict:
        todos = self.todos
        # Un partido está hecho si tiene estadísticas **o** si ya se pidió y
        # resultó no tenerlas. Contando solo lo primero, los que no las tienen
        # se quedaban para siempre en «faltan 2»: traías, volvías a entrar y
        # te los volvía a pedir, cada vez, gastando peticiones en algo que no
        # existe en la fuente.
        con_datos = [e for e in todos if almacen.tiene(e.id)]
        vacios = [e for e in todos
                  if e not in con_datos and almacen.sin_estadisticas(e.id)]
        faltan = [e for e in todos
                  if e not in con_datos and e not in vacios]
        return {
            "partido": self.partido,
            "arbitro": self.arbitro or None,
            "de_cada_uno": {"local": len(self.locales), "visitante": len(self.visitantes)},
            "entre_ellos": len(self.entre_ellos),
            "del_arbitro": len(self.del_arbitro),
            "en_total": len(todos),
            "ya_estaban": len(con_datos),
            "sin_estadisticas": len(vacios),
            "hay_que_pedir": len(faltan),
            # Seis peticiones por partido: la cabecera y las cinco secciones.
            "peticiones_estimadas": len(faltan) * 6,
        }


def planear(cliente: SofascoreClient, almacen: Almacen, partido: str | int | Event,
            ultimos: int = ULTIMOS, ultimos_arbitro: int = ULTIMOS_ARBITRO,
            con_arbitro: bool = True) -> Plan:
    """Qué partidos harían falta, sin traer ninguno todavía.

    Se puede enseñar antes de gastar: «esto son 38 partidos, 26 no los tienes,
    unas 156 peticiones». Decidir a ciegas cuánto vas a pedirle a un servidor
    ajeno no es decidir.
    """
    evento = _resolver(cliente, almacen, partido)
    plan = Plan(partido=f"{evento.home} - {evento.away}", arbitro=evento.referee or "")

    for lado, destino in (("home", "locales"), ("away", "visitantes")):
        equipo = getattr(evento, lado)
        if not equipo.id:
            continue
        setattr(plan, destino, _anteriores(_eventos_de_equipo(cliente, equipo.id),
                                           evento, ultimos))

    plan.entre_ellos = _anteriores(_h2h(cliente, evento), evento, ultimos)

    if con_arbitro and evento.referee:
        plan.del_arbitro = _anteriores(
            _del_arbitro(almacen, evento.referee), evento, ultimos_arbitro)
    return plan


def abastecer(cliente: SofascoreClient, almacen: Almacen, partido: str | int | Event,
              ultimos: int = ULTIMOS, ultimos_arbitro: int = ULTIMOS_ARBITRO,
              con_arbitro: bool = True, maximo_peticiones: int = 0,
              avisar: Callable[[str], None] | None = None) -> dict:
    """Trae y guarda todo lo que hace falta para analizar ese partido.

    Se puede cortar y repetir: lo guardado no se vuelve a pedir, así que
    reanudar es simplemente volver a llamar.
    """
    decir = avisar or (lambda _t: None)
    inicio = cliente.stats.requests

    def gastadas() -> int:
        return cliente.stats.requests - inicio

    def queda_cupo() -> bool:
        return not maximo_peticiones or gastadas() < maximo_peticiones

    evento = _resolver(cliente, almacen, partido)
    almacen.guardar_evento(evento)          # la cabecera primero, por las claves ajenas
    plan = planear(cliente, almacen, evento, ultimos, ultimos_arbitro, con_arbitro)
    cuentas = plan.cuentas(almacen)
    decir(f"{plan.partido}: {cuentas['en_total']} partidos hacen falta, "
          f"{cuentas['ya_estaban']} ya estaban, {cuentas['hay_que_pedir']} por pedir "
          f"(~{cuentas['peticiones_estimadas']} peticiones).")

    progreso = Progreso()
    pendientes = [e for e in plan.todos if not almacen.dado_por_hecho(e.id)]
    for numero, anterior in enumerate(pendientes, 1):
        if not queda_cupo():
            decir(f"Tope de {maximo_peticiones} peticiones alcanzado ({gastadas()} "
                  "gastadas); lo dejo aquí. Vuelve a llamarlo y sigue por donde falte.")
            break
        progreso.partidos_vistos += 1
        decir(f"  [{numero}/{len(pendientes)}] {anterior.home} - {anterior.away} "
              f"({anterior.date})")
        guardar_partido(cliente, almacen, anterior, progreso)

    progreso.peticiones = gastadas()
    # Sin fusionar los dos diccionarios a lo bruto: ambos traen `ya_estaban` y
    # significan cosas distintas —los que ya había y los que se intentaron y
    # resultaron estar—, y el de `Progreso` siempre es cero aquí porque los
    # guardados se apartan antes de empezar. Fusionarlos daba un cero en la
    # cara del usuario justo cuando la memoria empezaba a servir para algo.
    return {
        **cuentas,
        "guardados": progreso.partidos_guardados,
        "pedidos": progreso.partidos_vistos,
        "fallos": progreso.fallos,
        "peticiones": progreso.peticiones,
        "sin_estadisticas": cuentas["sin_estadisticas"] + progreso.sin_estadisticas,
        "completo": (progreso.partidos_guardados + progreso.sin_estadisticas
                     + cuentas["ya_estaban"] + cuentas["sin_estadisticas"]
                     >= cuentas["en_total"]),
        "fallos_detalle": progreso.detalle[:10],
        "como_leerlo": (
            "La segunda vez que pidas un partido de esta liga costará mucho menos: "
            "los últimos de un equipo son también los últimos de sus rivales, así "
            "que la memoria se solapa consigo misma y se satura."
        ),
    }


# ------------------------------------------------------------------ interiores

def _resolver(cliente: SofascoreClient, almacen: Almacen,
              partido: str | int | Event) -> Event:
    if isinstance(partido, Event):
        return partido
    from .previa import _resolver as resolver_previa

    evento = resolver_previa(almacen, partido, cliente)
    if evento is None:
        raise SofascoreError(f"No encuentro el partido {partido!r}.")
    return evento


def _anteriores(crudos: list[dict] | list[Event], evento: Event, cuantos: int) -> list[Event]:
    """Los ``cuantos`` partidos **anteriores** a este, del más reciente atrás.

    El filtro por fecha no es cosmético: meter en la memoria un partido
    posterior al que se analiza y luego promediar «sus últimos diez» sería
    mirar el futuro. Aquí se corta en el origen para que no dependa de que
    cada análisis se acuerde de cortarlo.
    """
    limite = evento.start_timestamp or 0
    eventos = [c if isinstance(c, Event) else Event.from_api(c) for c in crudos]
    eventos = [e for e in eventos
               if e.id != evento.id and e.is_finished and (e.start_timestamp or 0) < limite]
    eventos.sort(key=lambda e: e.start_timestamp or 0, reverse=True)
    return eventos[:cuantos]


def _eventos_de_equipo(cliente: SofascoreClient, equipo_id: int) -> list[dict]:
    try:
        return cliente.team_events(equipo_id, when="last")
    except SofascoreError:
        return []


def _h2h(cliente: SofascoreClient, evento: Event) -> list[dict]:
    try:
        return cliente.h2h_events(evento)
    except SofascoreError:
        return []


def _del_arbitro(almacen: Almacen, arbitro: str) -> list[Event]:
    """Los partidos que ha pitado, de la memoria.

    Sofascore no publica una ruta de «partidos de este árbitro», así que esto
    sale de lo que ya haya guardado. Merece decirse claro: el perfil del
    árbitro mejora con los barridos, no con este abastecimiento; lo que hace
    aquí es completar con detalle los que estén a medias, que son los que
    impiden contarle las tarjetas.
    """
    from .previa import _evento_desde_fila

    filas = almacen.consulta(
        "SELECT * FROM partidos WHERE arbitro = ? AND estado = 'finished' "
        "ORDER BY momento DESC LIMIT 60", (arbitro,))
    return [_evento_desde_fila(f) for f in filas]


__all__ = ["Plan", "ULTIMOS", "ULTIMOS_ARBITRO", "abastecer", "planear"]
