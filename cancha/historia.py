"""Traerse la historia de golpe: años de partidos, no seis por equipo.

Hasta aquí la memoria se llenaba de dos maneras, y las dos van partido a
partido: la guardia nocturna trae los del día siguiente y su contexto, y desde
la pantalla de un partido se piden sus cuarenta. Con eso no se junta muestra.
Para que un perfil de equipo signifique algo hacen falta un par de temporadas, y
para juzgar a un árbitro, todavía más; a seis partidos por visita, eso son meses.

Esto trae **una liga entera, temporada a temporada, hacia atrás**:

    from cancha.historia import plan, traer

    plan(cliente, almacen, ["laliga"], anos=3)     # qué va a costar, sin pedirlo
    traer(cliente, almacen, ["laliga"], anos=3)    # y ahora sí

Dos decisiones que lo hacen usable:

**Por temporada y no por equipo.** Una petición devuelve treinta partidos de
toda la liga. Yendo equipo por equipo, cada partido se trae dos veces —una por
cada lado— y hay que pedir veinte calendarios para cubrir lo mismo.

**Se puede parar y seguir.** Un partido ya guardado no se vuelve a pedir, así
que esto se deja corriendo un rato, se corta, y al volver sigue por donde iba.
Con `maximo` se pone un tope de peticiones por tanda. Es imprescindible: tres
años de cinco ligas son decenas de miles de peticiones y varias horas.

Lo que **no** hace: inventarse lo que la fuente no tiene. Hay partidos viejos y
categorías pequeñas sin estadísticas, y esos se apuntan como tales y no se
vuelven a pedir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .almacen import Almacen
from .barrido import Progreso, guardar_partido, ligas_de
from .client import SofascoreClient
from .errors import SofascoreError
from .models import Event

#: Cuántos partidos trae cada página de una temporada. Lo fija la API; se usa
#: para estimar el plan sin gastar peticiones de más.
POR_PAGINA = 30

#: Tope de páginas por temporada. Una liga grande son 380 partidos, o sea trece
#: páginas; esto es el freno para que un id raro no deje esto dando vueltas.
PAGINAS_MAXIMAS = 40

#: Cuántas peticiones cuesta un partido con el detalle de siempre. Es la cuenta
#: que convierte «tres años de LaLiga» en «unas seis mil peticiones», que es lo
#: que hay que saber **antes** de darle al botón.
PETICIONES_POR_PARTIDO = 5


@dataclass
class Avance:
    """Lo que va pasando, para poder enseñarlo y para poder pararlo."""

    ligas: int = 0
    temporadas: int = 0
    partidos_vistos: int = 0
    guardados: int = 0
    ya_estaban: int = 0
    sin_estadisticas: int = 0
    fallos: int = 0
    peticiones: int = 0
    detalle: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ligas": self.ligas, "temporadas": self.temporadas,
                "partidos_vistos": self.partidos_vistos, "guardados": self.guardados,
                "ya_estaban": self.ya_estaban,
                "sin_estadisticas": self.sin_estadisticas, "fallos": self.fallos,
                "peticiones": self.peticiones}


def _desde(anos: int) -> str:
    """La fecha a partir de la cual se trae, como AAAA-MM-DD."""
    return (datetime.now(timezone.utc)
            - timedelta(days=365 * max(1, int(anos)))).strftime("%Y-%m-%d")


def temporadas_de(cliente: SofascoreClient, liga_id: int, anos: int) -> list[dict]:
    """Las temporadas de una liga que caen dentro de la ventana pedida.

    Sofascore no dice las fechas de una temporada en este listado, así que se
    usa su año: «2024/25» entra si 2024 o 2025 caen dentro. Es aproximado por
    arriba, y eso es lo que se quiere: más vale mirar una temporada de más —sus
    partidos se descartan solos por fecha— que dejarse media fuera.
    """
    corte = int(_desde(anos)[:4])
    salida = []
    for temporada in cliente.seasons(liga_id):
        anos_de = [int(x) for x in str(temporada.get("year") or "").replace("/", " ")
                   .replace("-", " ").split() if x.isdigit()]
        anos_de = [a if a > 100 else 2000 + a for a in anos_de]
        if not anos_de or max(anos_de) >= corte:
            salida.append(temporada)
    return salida


def plan(cliente: SofascoreClient, almacen: Almacen,
         grupos: list[str] | None = None, anos: int = 3,
         secciones: list[str] | None = None) -> dict:
    """Qué se va a traer y qué va a costar, **sin** traerlo.

    Cuesta una petición por liga (su lista de temporadas) y ni una más. Es lo que
    permite enseñar «unas 18.000 peticiones, varias horas» antes de empezar, en
    vez de descubrirlo a mitad.
    """
    ligas = ligas_de(grupos, almacen)
    cuantas = len(secciones or []) or PETICIONES_POR_PARTIDO
    detalle = []
    total_temporadas = 0
    for liga_id, nombre in ligas.items():
        try:
            suyas = temporadas_de(cliente, liga_id, anos)
        except SofascoreError as exc:
            detalle.append({"liga": nombre, "error": str(exc)})
            continue
        total_temporadas += len(suyas)
        detalle.append({"liga": nombre, "liga_id": liga_id,
                        "temporadas": len(suyas),
                        "desde": min((str(t.get("year") or "") for t in suyas),
                                     default="")})
    # Una temporada de liga grande son ~380 partidos; de copa, muchos menos. Se
    # usa una estimación prudente y se dice que lo es: un número exacto aquí
    # costaría pedir todas las páginas, que es justo lo que se quiere evitar.
    partidos = total_temporadas * 300
    return {
        "ligas": len(ligas),
        "temporadas": total_temporadas,
        "desde": _desde(anos),
        "partidos_estimados": partidos,
        "peticiones_estimadas": partidos * cuantas + total_temporadas * 13,
        "secciones": list(secciones or []),
        "por_liga": detalle,
        "aviso": (
            f"Es una estimación por arriba: {partidos:,} partidos a {cuantas} "
            "peticiones cada uno. Lo que ya esté guardado no se vuelve a pedir, "
            "así que la segunda vez cuesta mucho menos. Aun así, esto son horas: "
            "déjalo corriendo con un tope y vuelve a darle.").replace(",", "."),
    }


def traer(cliente: SofascoreClient, almacen: Almacen,
          grupos: list[str] | None = None, anos: int = 3,
          secciones: list[str] | None = None, maximo: int = 0,
          avisar: Callable[[str], None] | None = None,
          puede_seguir: Callable[[], bool] | None = None) -> dict:
    """Trae la historia de las ligas elegidas. Se puede cortar y reanudar."""
    decir = avisar or (lambda _t: None)
    avance = Avance()
    ligas = ligas_de(grupos, almacen)
    corte = _desde(anos)
    empezo = cliente.stats.requests

    def gastadas() -> int:
        return cliente.stats.requests - empezo

    def queda() -> bool:
        if puede_seguir is not None and not puede_seguir():
            return False
        return not maximo or gastadas() < maximo

    decir(f"{len(ligas)} competiciones, desde {corte}.")
    for liga_id, nombre in ligas.items():
        if not queda():
            decir("Tope alcanzado: se para aquí y se sigue en la próxima tanda.")
            break
        avance.ligas += 1
        try:
            suyas = temporadas_de(cliente, liga_id, anos)
        except SofascoreError as exc:
            avance.fallos += 1
            avance.detalle.append(f"{nombre}: {exc}")
            decir(f"✗ {nombre}: {exc}")
            continue
        decir(f"{nombre}: {len(suyas)} temporadas.")
        for temporada in suyas:
            if not queda():
                break
            avance.temporadas += 1
            _una_temporada(cliente, almacen, liga_id, temporada, nombre, corte,
                           secciones, avance, decir, queda)

    avance.peticiones = gastadas()
    return {**avance.as_dict(), "desde": corte,
            "detalle": avance.detalle[-60:],
            "completo": queda(),
            "como_leerlo": (
                "«Ya estaban» son los que no ha hecho falta volver a pedir, que es "
                "lo que abarata repetir esto. «Sin estadísticas» son partidos que la "
                "fuente no tiene con detalle —normal en categorías menores y en lo "
                "viejo—: se pidieron una vez y no se vuelven a pedir.")}


def _una_temporada(cliente, almacen, liga_id, temporada, nombre, corte, secciones,
                   avance: Avance, decir, queda) -> None:
    """Todas las páginas de una temporada, de lo más reciente hacia atrás."""
    temporada_id = temporada.get("id")
    if not temporada_id:
        return
    etiqueta = f"{nombre} {temporada.get('year') or ''}".strip()
    for pagina in range(PAGINAS_MAXIMAS):
        if not queda():
            return
        try:
            crudos = cliente.season_events(liga_id, temporada_id, pagina)
        except SofascoreError as exc:
            avance.fallos += 1
            avance.detalle.append(f"{etiqueta} p{pagina}: {exc}")
            return
        if not crudos:
            return
        eventos = [Event.from_api(e) for e in crudos]
        # Ordenados del más nuevo al más viejo: así, en cuanto uno se pasa del
        # corte, todo lo que queda detrás también, y se puede parar.
        eventos.sort(key=lambda e: e.start_timestamp or 0, reverse=True)
        for evento in eventos:
            if not queda():
                return
            if evento.date and evento.date < corte:
                decir(f"{etiqueta}: llegado al corte ({corte}).")
                return
            _uno(cliente, almacen, evento, secciones, avance)
        if len(crudos) < POR_PAGINA:
            return
        decir(f"{etiqueta}: {avance.partidos_vistos} vistos, "
              f"{avance.guardados} traídos, {avance.peticiones} peticiones.")


def _uno(cliente, almacen, evento: Event, secciones, avance: Avance) -> None:
    """Un partido: se guarda con el detalle pedido, si no estaba ya."""
    avance.partidos_vistos += 1
    antes_ya = almacen.dado_por_hecho(evento.id)
    progreso = Progreso()
    guardar_partido(cliente, almacen, evento, progreso, secciones=secciones)
    avance.guardados += progreso.partidos_guardados
    avance.sin_estadisticas += progreso.sin_estadisticas
    avance.fallos += progreso.fallos
    if antes_ya:
        avance.ya_estaban += 1
    avance.detalle.extend(progreso.detalle)


__all__ = ["PETICIONES_POR_PARTIDO", "Avance", "plan", "temporadas_de", "traer"]
