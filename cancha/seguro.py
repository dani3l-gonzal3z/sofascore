"""Lo que casi siempre pasa, medido en vez de supuesto.

La intuición de la que sale este módulo es buena: *«si el Madrid perdió el
último, es rarísimo que pierda el siguiente»*. El problema es el número. Nadie
sabe si eso es el 99 %, el 80 % o exactamente lo mismo que pasa siempre, porque
nadie lo ha contado.

Aquí se cuenta. Un **patrón** es una condición que se puede ver antes del
partido y un desenlace que se ve después. Se recorre todo el historial
guardado, se mira en cuántos casos se cumplió la condición y en cuántos de
esos pasó el desenlace, y se publican tres cifras juntas:

* la **frecuencia** observada, con su número de casos;
* el **suelo de confianza** (Wilson al 95 %), que es lo que se puede defender
  con esa muestra: con 8 de 8 la frecuencia es 100 % y el suelo, 67 %;
* la **elevación** sobre la tasa base — y esta es la importante. Si los
  favoritos ganan el 62 % de las veces y «favorito tras perder» gana el 63 %,
  el patrón no existe: es el equipo, no la reacción.

Nada de esto produce un 99,99 %. En esa horquilla no hay fútbol; lo que hay son
patrones del 75 al 90 % que el mercado ya conoce y paga en consecuencia. Lo
que sí produce es saber **cuál de tus corazonadas aguanta el recuento** y cuál
era la tasa base disfrazada.

    from cancha.seguro import calibrar, avisos

    calibrar(almacen)                       # qué dice tu historial de cada patrón
    avisos(almacen, cliente, "2026-09-19")  # qué se cumple hoy, y con qué número
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .almacen import Almacen
from .cuotas import UMBRAL_FAVORITO

#: Casos por debajo de los cuales no se publica un patrón. Treinta es poco para
#: una tesis y bastante para no hacer el ridículo.
MINIMO_CASOS = 30
#: Suelo de confianza a partir del cual se considera «casi seguro».
UMBRAL_SEGURO = 0.80
#: Y a partir del cual, meramente «probable».
UMBRAL_PROBABLE = 0.65
#: Elevación mínima sobre la tasa base para que el patrón diga algo propio.
#: Por debajo de esto el patrón describe el fútbol, no la situación.
ELEVACION_MINIMA = 0.05


# --------------------------------------------------------------- estadística

def wilson(exitos: int, casos: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción.

    Es el que hay que usar con muestras cortas y proporciones cerca de 1, que
    es exactamente el caso: la fórmula de toda la vida (``p ± z·√(p(1-p)/n)``)
    con 8 de 8 da un intervalo de ancho cero, que es absurdo.
    """
    if casos <= 0:
        return (0.0, 1.0)
    p = exitos / casos
    denominador = 1 + z * z / casos
    centro = (p + z * z / (2 * casos)) / denominador
    margen = (z / denominador) * math.sqrt(p * (1 - p) / casos + z * z / (4 * casos * casos))
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def veredicto(suelo: float, elevacion: float, casos: int) -> str:
    """Cómo de fiar es un patrón, en una palabra."""
    if casos < MINIMO_CASOS:
        return "sin muestra"
    if abs(elevacion) < ELEVACION_MINIMA:
        return "es la tasa base"
    if suelo >= UMBRAL_SEGURO:
        return "casi seguro"
    if suelo >= UMBRAL_PROBABLE:
        return "probable"
    return "poco"


# ------------------------------------------------------------- los contextos

@dataclass
class Antes:
    """Lo que se sabe de un partido **antes** de que empiece.

    Separar esto del resultado no es una floritura: es lo que impide que una
    condición mire el marcador sin querer. Una condición solo recibe un
    ``Antes``, y aquí dentro no hay forma de saber cómo acabó.
    """

    equipo_id: int | None
    rival_id: int | None
    es_local: bool
    fecha: str
    liga_id: int | None
    arbitro: str = ""
    #: Probabilidades del mercado, si las hay: local / empate / visitante.
    mercado: dict[str, float] = field(default_factory=dict)
    #: Partidos anteriores de cada equipo, del más reciente atrás.
    _mios: list[dict] = field(default_factory=list, repr=False)
    _suyos: list[dict] = field(default_factory=list, repr=False)
    _arbitrados: list[dict] = field(default_factory=list, repr=False)

    # --- el mercado ---

    @property
    def prob_propia(self) -> float | None:
        if not self.mercado:
            return None
        return self.mercado.get("local" if self.es_local else "visitante")

    @property
    def prob_rival(self) -> float | None:
        if not self.mercado:
            return None
        return self.mercado.get("visitante" if self.es_local else "local")

    @property
    def era_favorito(self) -> bool | None:
        propia = self.prob_propia
        return None if propia is None else propia >= UMBRAL_FAVORITO

    # --- el historial ---

    def mios(self, cuantos: int = 6) -> list[dict]:
        return self._mios[:cuantos]

    def suyos(self, cuantos: int = 6) -> list[dict]:
        return self._suyos[:cuantos]

    def arbitrados(self, cuantos: int = 15) -> list[dict]:
        return self._arbitrados[:cuantos]

    # --- lecturas cómodas del historial ---

    @staticmethod
    def _lado(partido: dict, equipo_id: int | None) -> tuple[int, int] | None:
        local, visitante = partido.get("goles_local"), partido.get("goles_visitante")
        if local is None or visitante is None or equipo_id is None:
            return None
        return (local, visitante) if partido.get("local_id") == equipo_id else (visitante, local)

    def resultados(self, cuantos: int = 6, rival: bool = False) -> list[str]:
        """``["G", "P", "E", …]`` del más reciente atrás."""
        lista = self.suyos(cuantos) if rival else self.mios(cuantos)
        quien = self.rival_id if rival else self.equipo_id
        salida = []
        for partido in lista:
            marcador = self._lado(partido, quien)
            if marcador is None:
                continue
            favor, contra = marcador
            salida.append("G" if favor > contra else ("E" if favor == contra else "P"))
        return salida

    def goles(self, cuantos: int = 6, rival: bool = False) -> list[tuple[int, int]]:
        """``[(a favor, en contra), …]`` del más reciente atrás."""
        lista = self.suyos(cuantos) if rival else self.mios(cuantos)
        quien = self.rival_id if rival else self.equipo_id
        return [m for m in (self._lado(p, quien) for p in lista) if m is not None]

    def media_estadistica(self, clave: str, cuantos: int = 6,
                          rival: bool = False, concedida: bool = False) -> float | None:
        """La media de una estadística en sus últimos partidos.

        ``concedida`` la mira del revés: lo que le hacen en vez de lo que hace.
        """
        lista = self.suyos(cuantos) if rival else self.mios(cuantos)
        quien = self.rival_id if rival else self.equipo_id
        ids = [p["id"] for p in lista]
        if not ids or quien is None:
            return None
        filas = _estadisticas(self.almacen, ids, clave)
        valores = []
        for fila in filas:
            es_local = fila.get("local_id") == quien
            if concedida:
                es_local = not es_local
            valor = fila.get("local") if es_local else fila.get("visitante")
            if valor is not None:
                valores.append(valor)
        return sum(valores) / len(valores) if valores else None

    #: Se inyecta al construirlo; no entra en el repr para no ensuciar.
    almacen: Any = field(default=None, repr=False)


@dataclass
class Despues:
    """Cómo acabó. Solo lo ve el desenlace de un patrón, nunca la condición."""

    equipo_id: int | None
    es_local: bool
    goles_local: int | None
    goles_visitante: int | None
    estadisticas: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)

    @property
    def completo(self) -> bool:
        return self.goles_local is not None and self.goles_visitante is not None

    @property
    def favor(self) -> int | None:
        if not self.completo:
            return None
        return self.goles_local if self.es_local else self.goles_visitante

    @property
    def contra(self) -> int | None:
        if not self.completo:
            return None
        return self.goles_visitante if self.es_local else self.goles_local

    @property
    def total(self) -> int | None:
        if not self.completo:
            return None
        return (self.goles_local or 0) + (self.goles_visitante or 0)

    @property
    def gano(self) -> bool | None:
        return None if not self.completo else self.favor > self.contra

    @property
    def perdio(self) -> bool | None:
        return None if not self.completo else self.favor < self.contra

    @property
    def empato(self) -> bool | None:
        return None if not self.completo else self.favor == self.contra

    @property
    def marco(self) -> bool | None:
        return None if not self.completo else (self.favor or 0) > 0

    @property
    def encajo(self) -> bool | None:
        return None if not self.completo else (self.contra or 0) > 0

    @property
    def ambos_marcaron(self) -> bool | None:
        if not self.completo:
            return None
        return (self.goles_local or 0) > 0 and (self.goles_visitante or 0) > 0

    def suma(self, clave: str) -> float | None:
        """La suma de una estadística entre los dos equipos."""
        par = self.estadisticas.get(clave)
        if not par or par[0] is None or par[1] is None:
            return None
        return par[0] + par[1]


# ------------------------------------------------------------- los patrones

@dataclass(frozen=True)
class Patron:
    """Una condición que se ve antes y un desenlace que se ve después."""

    nombre: str
    titulo: str
    pregunta: str
    condicion: Callable[[Antes], bool | None]
    desenlace: Callable[[Despues], bool | None]
    #: ``equipo`` se evalúa una vez por equipo; ``partido``, una por partido.
    ambito: str = "equipo"
    #: Estadísticas que hace falta tener del partido para juzgar el desenlace.
    necesita: tuple[str, ...] = ()
    porque: str = ""
    #: Con qué otro patrón hay que compararlo para que la comparación valga.
    #: Sin esto, «favorito tras no ganar» se compara con todos los equipos del
    #: mundo y parece un hallazgo, cuando lo que hay que preguntarse es si
    #: gana más que un favorito cualquiera.
    referencia: str = ""


def _racha(resultados: list[str], letra: str, cuantos: int) -> bool:
    return len(resultados) >= cuantos and all(r == letra for r in resultados[:cuantos])


def _no_gano_el_ultimo(antes: Antes) -> bool | None:
    resultados = antes.resultados(1)
    return None if not resultados else resultados[0] != "G"


def _era_favorito_y_no_gano(antes: Antes) -> bool | None:
    """La corazonada del usuario, escrita para poder contarla.

    Hacen falta dos cosas: que el equipo **fuera favorito** en su último
    partido y no lo ganara, y que **vuelva a serlo** hoy. Sin lo segundo no se
    compara nada: un favorito que ganó y uno que perdió solo son comparables si
    los dos vuelven a salir de favoritos.
    """
    if antes.era_favorito is not True:
        return None
    anterior = antes.mios(1)
    if not anterior:
        return None
    marcador = antes._lado(anterior[0], antes.equipo_id)
    if marcador is None:
        return None
    cuotas = antes.almacen.cuotas_de(anterior[0]["id"]) if antes.almacen else None
    if not cuotas:
        return None
    era_local = anterior[0].get("local_id") == antes.equipo_id
    probabilidad = cuotas["probabilidades"].get("local" if era_local else "visitante")
    if probabilidad is None or probabilidad < UMBRAL_FAVORITO:
        return None
    favor, contra = marcador
    return favor <= contra


def _favorito_hoy(antes: Antes) -> bool | None:
    return antes.era_favorito


def _favorito_claro_hoy(antes: Antes) -> bool | None:
    propia = antes.prob_propia
    return None if propia is None else propia >= 0.65


def _viene_de_perder(antes: Antes) -> bool | None:
    resultados = antes.resultados(1)
    return None if not resultados else resultados[0] == "P"


def _marca_siempre(antes: Antes) -> bool | None:
    goles = antes.goles(6)
    if len(goles) < 6:
        return None
    return all(favor > 0 for favor, _ in goles)


def _lleva_sin_marcar(antes: Antes) -> bool | None:
    goles = antes.goles(3)
    if len(goles) < 3:
        return None
    return all(favor == 0 for favor, _ in goles)


def _gana_todo(antes: Antes) -> bool | None:
    resultados = antes.resultados(4)
    return None if len(resultados) < 4 else _racha(resultados, "G", 4)


def _ambos_marcan_siempre(antes: Antes) -> bool | None:
    mios, suyos = antes.goles(6), antes.goles(6, rival=True)
    if len(mios) < 5 or len(suyos) < 5:
        return None
    con_ambos = sum(1 for favor, contra in mios if favor > 0 and contra > 0)
    con_ambos += sum(1 for favor, contra in suyos if favor > 0 and contra > 0)
    return con_ambos / (len(mios) + len(suyos)) >= 0.8


def _partido_de_goles(antes: Antes) -> bool | None:
    mios, suyos = antes.goles(6), antes.goles(6, rival=True)
    if len(mios) < 5 or len(suyos) < 5:
        return None
    media = (sum(a + b for a, b in mios) / len(mios)
             + sum(a + b for a, b in suyos) / len(suyos)) / 2
    return media >= 3.2


def _partido_cerrado(antes: Antes) -> bool | None:
    mios, suyos = antes.goles(6), antes.goles(6, rival=True)
    if len(mios) < 5 or len(suyos) < 5:
        return None
    media = (sum(a + b for a, b in mios) / len(mios)
             + sum(a + b for a, b in suyos) / len(suyos)) / 2
    return media <= 2.2


def _muchos_corners(antes: Antes) -> bool | None:
    mios = antes.media_estadistica("cornerKicks", 6)
    suyos = antes.media_estadistica("cornerKicks", 6, rival=True)
    concedidos = antes.media_estadistica("cornerKicks", 6, concedida=True)
    if mios is None or suyos is None or concedidos is None:
        return None
    return (mios + suyos + concedidos) / 2 >= 11.0


def _arbitro_tarjetero(antes: Antes) -> bool | None:
    partidos = antes.arbitrados(12)
    if len(partidos) < 8 or not antes.almacen:
        return None
    filas = _estadisticas(antes.almacen, [p["id"] for p in partidos], "yellowCards")
    totales = [(f.get("local") or 0) + (f.get("visitante") or 0) for f in filas]
    if len(totales) < 8:
        return None
    return sum(totales) / len(totales) >= 4.8


#: Los patrones. Cada uno es una corazonada escrita de forma que se pueda
#: contar; ninguno vale nada hasta que :func:`calibrar` le pone un número.
PATRONES: tuple[Patron, ...] = (
    Patron(
        "reaccion_del_favorito", "La reacción del favorito",
        "Era favorito, no ganó, y hoy vuelve a serlo: ¿gana?",
        _era_favorito_y_no_gano, lambda d: d.gano,
        referencia="favorito_claro_gana",
        porque="Es la corazonada de «si el Madrid perdió, el siguiente lo gana». "
               "Solo cuenta si hoy también es favorito: si no, no hay con qué comparar. "
               "Y se compara con lo que hace un favorito cualquiera, que es la "
               "única forma de saber si la reacción existe.",
    ),
    Patron(
        "favorito_no_pierde", "El favorito no pierde",
        "Sale de favorito: ¿evita la derrota?",
        _favorito_hoy, lambda d: d.perdio is not None and not d.perdio,
        porque="La tasa base contra la que hay que medir todo lo demás.",
    ),
    Patron(
        "favorito_claro_gana", "El favorito claro gana",
        "El mercado le da un 65 % o más: ¿gana?",
        _favorito_claro_hoy, lambda d: d.gano,
        porque="Si el mercado acierta, esto debería salir cerca del 65 %.",
    ),
    Patron(
        "rebote_tras_derrota", "El rebote tras la derrota",
        "Perdió el último: ¿evita perder hoy?",
        _viene_de_perder, lambda d: d.perdio is not None and not d.perdio,
        porque="La versión sin filtro de la corazonada, para ver cuánto aporta "
               "el filtro de favorito.",
    ),
    Patron(
        "sigue_marcando", "El que marca siempre",
        "Marcó en sus seis últimos: ¿marca hoy?",
        _marca_siempre, lambda d: d.marco,
    ),
    Patron(
        "sigue_sin_marcar", "El que no marca",
        "Lleva tres sin marcar: ¿sigue sin marcar?",
        _lleva_sin_marcar, lambda d: d.marco is not None and not d.marco,
        porque="Las rachas malas se rompen; la pregunta es cuándo.",
    ),
    Patron(
        "racha_de_cuatro", "El que gana todo",
        "Ganó los cuatro últimos: ¿gana el quinto?",
        _gana_todo, lambda d: d.gano, referencia="favorito_no_pierde",
    ),
    Patron(
        "ambos_marcan", "Los dos marcan",
        "Los dos vienen de partidos con goles de ambos: ¿marcan los dos?",
        _ambos_marcan_siempre, lambda d: d.ambos_marcaron, ambito="partido",
    ),
    Patron(
        "mas_de_2_5", "Más de 2,5 goles",
        "Entre los dos promedian 3,2 goles por partido: ¿pasan de 2,5?",
        _partido_de_goles, lambda d: None if d.total is None else d.total > 2.5,
        ambito="partido",
    ),
    Patron(
        "menos_de_3_5", "Menos de 3,5 goles",
        "Entre los dos promedian 2,2 goles o menos: ¿se quedan por debajo de 3,5?",
        _partido_cerrado, lambda d: None if d.total is None else d.total < 3.5,
        ambito="partido",
    ),
    Patron(
        "corners", "Más de 9,5 córners",
        "Los dos sacan y conceden muchos córners: ¿pasan de 9,5?",
        _muchos_corners,
        lambda d: None if d.suma("cornerKicks") is None else d.suma("cornerKicks") > 9.5,
        ambito="partido", necesita=("cornerKicks",),
    ),
    Patron(
        "tarjetas", "Más de 3,5 amarillas",
        "Pita un árbitro que promedia casi cinco: ¿pasan de 3,5?",
        _arbitro_tarjetero,
        lambda d: None if d.suma("yellowCards") is None else d.suma("yellowCards") > 3.5,
        ambito="partido", necesita=("yellowCards",),
    ),
)

POR_NOMBRE: dict[str, Patron] = {p.nombre: p for p in PATRONES}


# ------------------------------------------------------------------- medirlo

def _estadisticas(almacen: Almacen | None, ids: list[int], clave: str) -> list[dict]:
    if not almacen or not ids:
        return []
    return almacen.estadisticas_de_partidos(ids, claves=[clave])


class _Historial:
    """Índice en memoria de los partidos por equipo y por árbitro.

    Calibrar doce patrones sobre miles de partidos con una consulta por equipo
    y partido sería una eternidad. Esto se lee una vez y se corta.
    """

    def __init__(self, almacen: Almacen, liga_id: int | None = None,
                 desde: str | None = None) -> None:
        self.almacen = almacen
        sql = "SELECT * FROM partidos WHERE estado = 'finished'"
        parametros: tuple = ()
        if liga_id:
            sql += " AND liga_id = ?"
            parametros += (liga_id,)
        if desde:
            sql += " AND fecha >= ?"
            parametros += (desde,)
        self.partidos = almacen.consulta(sql + " ORDER BY momento ASC", parametros)

        self.por_equipo: dict[int, list[dict]] = {}
        self.por_arbitro: dict[str, list[dict]] = {}
        for partido in self.partidos:
            for lado in ("local_id", "visitante_id"):
                equipo = partido.get(lado)
                if equipo:
                    self.por_equipo.setdefault(equipo, []).append(partido)
            arbitro = partido.get("arbitro")
            if arbitro:
                self.por_arbitro.setdefault(arbitro, []).append(partido)

        self.cuotas = {f["partido_id"]: f for f in almacen.consulta("SELECT * FROM cuotas")}
        self._estadisticas: dict[str, dict[int, dict]] = {}

    def antes_de(self, lista: list[dict], momento: int | None) -> list[dict]:
        """Los partidos anteriores a un momento, del más reciente atrás."""
        if momento is None:
            return []
        previos = [p for p in lista if (p.get("momento") or 0) < momento]
        return previos[::-1]

    def mercado(self, partido_id: int) -> dict[str, float]:
        fila = self.cuotas.get(partido_id)
        if not fila or fila.get("prob_local") is None:
            return {}
        return {"local": fila["prob_local"], "empate": fila.get("prob_empate"),
                "visitante": fila["prob_visitante"]}

    def corte(self, fraccion: float = 0.7) -> int | None:
        """El momento que parte el historial en «lo viejo» y «lo nuevo».

        El corte es **por fecha**, no al azar: partir al azar dejaría partidos
        posteriores en la mitad con la que se mide, y entonces comprobar el
        patrón en la otra mitad no comprobaría nada.
        """
        if len(self.partidos) < 2:
            return None
        indice = int(len(self.partidos) * fraccion)
        indice = min(max(indice, 1), len(self.partidos) - 1)
        return self.partidos[indice].get("momento")

    def estadistica(self, clave: str) -> dict[int, dict]:
        """``{partido_id: fila}`` de una clave, leída de una vez."""
        if clave not in self._estadisticas:
            ids = [p["id"] for p in self.partidos]
            filas = {}
            for trozo in range(0, len(ids), 500):
                for fila in self.almacen.estadisticas_de_partidos(
                        ids[trozo:trozo + 500], claves=[clave]):
                    filas[fila["partido_id"]] = fila
            self._estadisticas[clave] = filas
        return self._estadisticas[clave]


def _antes(indice: _Historial, partido: dict, equipo_id: int | None,
           rival_id: int | None, es_local: bool) -> Antes:
    momento = partido.get("momento")
    return Antes(
        equipo_id=equipo_id, rival_id=rival_id, es_local=es_local,
        fecha=partido.get("fecha") or "", liga_id=partido.get("liga_id"),
        arbitro=partido.get("arbitro") or "",
        mercado=indice.mercado(partido["id"]),
        _mios=indice.antes_de(indice.por_equipo.get(equipo_id or 0, []), momento),
        _suyos=indice.antes_de(indice.por_equipo.get(rival_id or 0, []), momento),
        _arbitrados=indice.antes_de(
            indice.por_arbitro.get(partido.get("arbitro") or "", []), momento),
        almacen=indice.almacen,
    )


def _despues(indice: _Historial, partido: dict, equipo_id: int | None,
             es_local: bool, necesita: tuple[str, ...]) -> Despues:
    estadisticas = {}
    for clave in necesita:
        fila = indice.estadistica(clave).get(partido["id"])
        estadisticas[clave] = (fila.get("local"), fila.get("visitante")) if fila else (None, None)
    return Despues(equipo_id=equipo_id, es_local=es_local,
                   goles_local=partido.get("goles_local"),
                   goles_visitante=partido.get("goles_visitante"),
                   estadisticas=estadisticas)


#: Cuántos casos hacen falta en la parte nueva para que comprobar ahí
#: signifique algo. Menos que el mínimo de siempre, porque es solo el 30 % del
#: historial; por debajo de esto se dice «sin muestra» en vez de un veredicto.
MINIMO_CASOS_FUERA = 12


def medir(almacen: Almacen, patron: Patron, liga_id: int | None = None,
          desde: str | None = None, indice: _Historial | None = None,
          corte: int | None = None) -> dict:
    """Cuenta un patrón sobre el historial guardado.

    Devuelve la frecuencia, el suelo de Wilson, la tasa base del desenlace y la
    elevación de una sobre la otra, que es lo único que dice si el patrón
    aporta algo.

    Con ``corte`` (un momento) se cuenta además por separado lo anterior y lo
    posterior a esa fecha. Sirve para la pregunta que de verdad importa: el
    patrón se ha medido mirando el pasado, ¿y se cumplió luego? Un patrón que
    da 85 % antes y 55 % después no es un patrón, es una casualidad a la que
    le hemos puesto nombre.
    """
    indice = indice or _Historial(almacen, liga_id, desde)
    casos = exitos = 0
    base_casos = base_exitos = 0
    viejos_casos = viejos_exitos = nuevos_casos = nuevos_exitos = 0
    ejemplos: list[dict] = []

    for partido in indice.partidos:
        lados = ((partido.get("local_id"), partido.get("visitante_id"), True),
                 (partido.get("visitante_id"), partido.get("local_id"), False))
        if patron.ambito == "partido":
            lados = (lados[0],)
        for equipo_id, rival_id, es_local in lados:
            if not equipo_id:
                continue
            despues = _despues(indice, partido, equipo_id, es_local, patron.necesita)
            resultado = patron.desenlace(despues)
            if resultado is None:
                continue
            base_casos += 1
            base_exitos += int(resultado)
            antes = _antes(indice, partido, equipo_id, rival_id, es_local)
            if patron.condicion(antes) is not True:
                continue
            casos += 1
            exitos += int(resultado)
            if corte is not None:
                if (partido.get("momento") or 0) < corte:
                    viejos_casos += 1
                    viejos_exitos += int(resultado)
                else:
                    nuevos_casos += 1
                    nuevos_exitos += int(resultado)
            if len(ejemplos) < 8:
                ejemplos.append({
                    "fecha": partido.get("fecha"),
                    "partido": f"{partido.get('local')} {partido.get('goles_local')}"
                               f"-{partido.get('goles_visitante')} {partido.get('visitante')}",
                    "equipo": partido.get("local") if es_local else partido.get("visitante"),
                    "se_cumplio": bool(resultado),
                })

    frecuencia = exitos / casos if casos else None
    base = base_exitos / base_casos if base_casos else None
    suelo, techo = wilson(exitos, casos)
    elevacion = (frecuencia - base) if (frecuencia is not None and base is not None) else 0.0
    return {
        "patron": patron.nombre,
        "titulo": patron.titulo,
        "pregunta": patron.pregunta,
        "porque": patron.porque or None,
        "casos": casos,
        "exitos": exitos,
        "comparado_con": None,
        "indistinguible_de_la_referencia": None,
        "nota": None,
        "frecuencia": round(frecuencia, 4) if frecuencia is not None else None,
        "suelo": round(suelo, 4),
        "techo": round(techo, 4),
        "base": round(base, 4) if base is not None else None,
        "base_casos": base_casos,
        "elevacion": round(elevacion, 4),
        "veredicto": veredicto(suelo, elevacion, casos),
        "fuera_de_muestra": (_fuera_de_muestra(viejos_casos, viejos_exitos,
                                               nuevos_casos, nuevos_exitos, indice, corte)
                             if corte is not None else None),
        "ejemplos": ejemplos,
    }


def _fuera_de_muestra(viejos_casos: int, viejos_exitos: int,
                      nuevos_casos: int, nuevos_exitos: int,
                      indice: _Historial, corte: int) -> dict:
    """Medido solo con lo viejo, ¿se cumplió en lo nuevo?

    No es una prueba de hipótesis nueva: es la misma cuenta hecha dos veces,
    en dos tramos de tiempo, para ver si el número se sostiene. Es lo más
    barato que se puede hacer contra el riesgo de haberle puesto nombre al
    ruido, y lo más difícil de discutir.
    """
    antes = viejos_exitos / viejos_casos if viejos_casos else None
    despues = nuevos_exitos / nuevos_casos if nuevos_casos else None
    suelo, techo = wilson(nuevos_exitos, nuevos_casos)
    fecha_corte = next((p.get("fecha") for p in indice.partidos
                        if (p.get("momento") or 0) >= corte), None)

    if antes is None or nuevos_casos < MINIMO_CASOS_FUERA:
        resultado, lectura = "sin muestra", (
            f"Solo {nuevos_casos} caso{'s' if nuevos_casos != 1 else ''} después del "
            f"{fecha_corte or 'corte'}: no alcanza para comprobar nada. Barre más "
            "partidos y vuelve.")
    # Hacen falta las dos cosas: que la caída no quepa en la muestra **y** que
    # sea de un tamaño que importe. Con 66 casos, pasar del 100 % al 98 % sale
    # del intervalo por los pelos, y llamar a eso «se cae» es dar una alarma
    # donde no ha pasado nada. El umbral es el mismo que usa la elevación.
    elif antes > techo and (antes - despues) >= ELEVACION_MINIMA:
        resultado, lectura = "se cae", (
            f"{antes:.0%} antes del {fecha_corte} y {despues:.0%} después "
            f"({nuevos_casos} casos). La caída es mayor de lo que esa muestra puede "
            "explicar: el número de arriba se apoya sobre todo en lo viejo.")
    else:
        resultado, lectura = "aguanta", (
            f"{antes:.0%} antes del {fecha_corte} y {despues:.0%} después "
            f"({nuevos_casos} casos): se mantiene. Es lo más parecido a una "
            "comprobación que hay aquí, porque lo nuevo no participó en medirlo.")

    return {
        "corte": fecha_corte,
        "antes": {"casos": viejos_casos, "exitos": viejos_exitos,
                  "frecuencia": round(antes, 4) if antes is not None else None},
        "despues": {"casos": nuevos_casos, "exitos": nuevos_exitos,
                    "frecuencia": round(despues, 4) if despues is not None else None,
                    "suelo": round(suelo, 4), "techo": round(techo, 4)},
        "veredicto": resultado,
        "lectura": lectura,
    }


def _comparar_con_referencia(medidos: list[dict]) -> None:
    """Recalcula la elevación contra el patrón de referencia, si lo hay.

    Comparar «el favorito que no ganó» con todo el fútbol es hacer trampa: la
    mitad del efecto es que es favorito. La comparación honesta es contra otro
    favorito, y es la que decide si el patrón aporta algo o es un espejismo.
    """
    por_nombre = {m["patron"]: m for m in medidos}
    for medida in medidos:
        patron = POR_NOMBRE.get(medida["patron"])
        if not patron or not patron.referencia:
            continue
        referencia = por_nombre.get(patron.referencia)
        if not referencia or referencia.get("frecuencia") is None \
                or medida.get("frecuencia") is None:
            continue
        medida["comparado_con"] = {
            "patron": referencia["patron"],
            "titulo": referencia["titulo"],
            "frecuencia": referencia["frecuencia"],
            "casos": referencia["casos"],
        }
        medida["elevacion"] = round(medida["frecuencia"] - referencia["frecuencia"], 4)
        # Si la frecuencia de la referencia cabe dentro del intervalo de este
        # patrón, los dos números son el mismo número con otro nombre.
        dentro = medida["suelo"] <= referencia["frecuencia"] <= medida["techo"]
        medida["indistinguible_de_la_referencia"] = dentro
        if dentro:
            medida["veredicto"] = "es la tasa base"
            medida["nota"] = (
                f"{medida['frecuencia']:.0%} frente al {referencia['frecuencia']:.0%} de "
                f"«{referencia['titulo']}»: con {medida['casos']} casos esa diferencia "
                "no se distingue de cero. El patrón no añade nada."
            )
        else:
            medida["veredicto"] = veredicto(medida["suelo"], medida["elevacion"],
                                            medida["casos"])
            medida["nota"] = (
                f"{medida['frecuencia']:.0%} frente al {referencia['frecuencia']:.0%} de "
                f"«{referencia['titulo']}»: {medida['elevacion']:+.0%}."
            )


def calibrar(almacen: Almacen, liga_id: int | None = None, desde: str | None = None,
             patrones: list[str] | None = None) -> dict:
    """Mide todos los patrones sobre lo guardado, de más fiable a menos."""
    indice = _Historial(almacen, liga_id, desde)
    elegidos = [POR_NOMBRE[n] for n in patrones if n in POR_NOMBRE] if patrones else PATRONES
    # Las referencias se miden siempre, aunque no las pidas: sin ellas no hay
    # con qué comparar lo que sí has pedido.
    necesarias = {p.referencia for p in elegidos if p.referencia} - {p.nombre for p in elegidos}
    elegidos = list(elegidos) + [POR_NOMBRE[n] for n in necesarias if n in POR_NOMBRE]
    # El mismo corte para todos los patrones: comparar unos medidos con tres
    # años y otros con uno no diría nada de los patrones, diría del corte.
    corte = indice.corte()
    medidos = [medir(almacen, p, indice=indice, corte=corte) for p in elegidos]
    _comparar_con_referencia(medidos)
    if patrones:
        pedidos = set(patrones)
        medidos = [m for m in medidos if m["patron"] in pedidos]
    medidos.sort(key=lambda m: (-(m["suelo"] if m["casos"] >= MINIMO_CASOS else 0),
                                -abs(m["elevacion"])))
    utiles = [m for m in medidos if m["veredicto"] in ("casi seguro", "probable")]
    return {
        "partidos_mirados": len(indice.partidos),
        "liga_id": liga_id,
        "desde": desde,
        "patrones": medidos,
        "utiles": [m["patron"] for m in utiles],
        "como_leerlo": (
            f"La frecuencia es lo que pasó; el suelo es lo que esa muestra permite "
            f"defender (Wilson al 95 %). La elevación compara con la tasa base: por "
            f"debajo de {ELEVACION_MINIMA:.0%} el patrón describe el fútbol, no la "
            f"situación. Con menos de {MINIMO_CASOS} casos no se publica nada."
        ),
        "aguantan_fuera_de_muestra": [
            m["patron"] for m in medidos
            if (m.get("fuera_de_muestra") or {}).get("veredicto") == "aguanta"
        ],
        "lo_que_no_dice": (
            "Se prueban doce patrones a la vez sobre el mismo historial: alguno "
            "parecerá bueno por puro azar. Contra eso está la comprobación fuera "
            "de muestra —medir con el 70 % más viejo y mirar si se cumple en el "
            "30 % más nuevo—, que es lo único de aquí que no participó en elegir "
            "el patrón. Y todo esto se mide sobre los partidos que tú has "
            "barrido, que son sobre todo de equipos que juegan hoy: no es una "
            "muestra del fútbol, es una muestra de tu memoria."
        ),
    }


# ------------------------------------------------------------- qué pasa hoy

def _antes_de_un_evento(almacen: Almacen, evento, equipo_id: int | None,
                        rival_id: int | None, es_local: bool) -> Antes:
    """Como ``_antes`` pero para un partido por jugar, que no está en el índice."""
    from .cuotas import desde_fila

    fila = almacen.consulta("SELECT * FROM cuotas WHERE partido_id = ?", (evento.id,))
    bloque = desde_fila(fila[0]) if fila else None
    mercado = bloque["probabilidades"] if bloque else {}
    return Antes(
        equipo_id=equipo_id, rival_id=rival_id, es_local=es_local,
        fecha=evento.date, liga_id=evento.unique_tournament_id,
        arbitro=evento.referee or "", mercado=mercado,
        _mios=almacen.partidos_de_equipo(equipo_id, ultimos=12) if equipo_id else [],
        _suyos=almacen.partidos_de_equipo(rival_id, ultimos=12) if rival_id else [],
        _arbitrados=(almacen.partidos_de_arbitro(evento.referee, ultimos=20)
                     if evento.referee else []),
        almacen=almacen,
    )


def avisos(almacen: Almacen, cliente=None, fecha: str | None = None,
           grupos: list[str] | None = None, eventos=None,
           umbral: float = UMBRAL_PROBABLE, calibracion: dict | None = None) -> dict:
    """Qué patrones se cumplen hoy, y con qué número detrás.

    Primero se calibra con el historial —cada patrón se lleva su frecuencia
    medida— y después se mira qué condiciones se cumplen en los partidos del
    día. Lo que sale no es una predicción: es «esto ha pasado tantas veces de
    tantas en lo que tú tienes guardado».
    """
    from .barrido import agenda

    calibracion = calibracion or calibrar(almacen)
    medidas = {m["patron"]: m for m in calibracion["patrones"]}
    if eventos is None:
        eventos = agenda(cliente, fecha, grupos, almacen) if cliente else []

    salida: list[dict] = []
    for evento in eventos:
        for equipo_id, rival_id, es_local in (
                (evento.home.id, evento.away.id, True),
                (evento.away.id, evento.home.id, False)):
            antes = _antes_de_un_evento(almacen, evento, equipo_id, rival_id, es_local)
            for patron in PATRONES:
                if patron.ambito == "partido" and not es_local:
                    continue
                medida = medidas.get(patron.nombre) or {}
                if medida.get("casos", 0) < MINIMO_CASOS:
                    continue
                if medida["suelo"] < umbral or abs(medida["elevacion"]) < ELEVACION_MINIMA:
                    continue
                try:
                    if patron.condicion(antes) is not True:
                        continue
                except (TypeError, KeyError, ValueError):
                    continue
                sujeto = (evento.home.name if es_local else evento.away.name)
                salida.append({
                    "partido_id": evento.id,
                    "partido": f"{evento.home} - {evento.away}",
                    "competicion": evento.tournament,
                    "hora_utc": evento.kickoff.strftime("%H:%M") if evento.kickoff else None,
                    "sujeto": sujeto if patron.ambito == "equipo" else "el partido",
                    "patron": patron.nombre,
                    "titulo": patron.titulo,
                    "dice": patron.pregunta,
                    "frecuencia": medida["frecuencia"],
                    "suelo": medida["suelo"],
                    "base": medida["base"],
                    "elevacion": medida["elevacion"],
                    "casos": medida["casos"],
                    "veredicto": medida["veredicto"],
                    "fuera_de_muestra": medida.get("fuera_de_muestra"),
                    "mercado": antes.prob_propia,
                })
    salida.sort(key=lambda a: -a["suelo"])
    return {
        "fecha": fecha or "hoy",
        "avisos": salida,
        "partidos_mirados": len(list(eventos)),
        "calibrado_con": calibracion["partidos_mirados"],
        "como_leerlo": calibracion["como_leerlo"],
        "aguantan_fuera_de_muestra": calibracion.get("aguantan_fuera_de_muestra", []),
        "lo_que_no_dice": (
            "Nada de esto es una apuesta segura. El número más alto que sale de "
            "un historial de fútbol ronda el 85-90 %, y el mercado ya lo sabe: "
            "cuando la frecuencia y la cuota coinciden, no hay nada que ganar, "
            "solo algo que entender. " + calibracion["lo_que_no_dice"]
        ),
    }


__all__ = [
    "Patron", "PATRONES", "POR_NOMBRE", "Antes", "Despues",
    "wilson", "veredicto", "medir", "calibrar", "avisos",
    "MINIMO_CASOS", "MINIMO_CASOS_FUERA", "UMBRAL_SEGURO", "UMBRAL_PROBABLE",
    "ELEVACION_MINIMA",
]
