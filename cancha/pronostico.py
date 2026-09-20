"""El pronóstico de un partido: marcador, córners y tarjetas, **calculados**.

Aquí está la línea que separa este módulo de un adivino. Los números no los
dice un modelo de lenguaje: los calcula esta aritmética a partir de lo que hay
en la memoria, y el modelo solo los lee en voz alta. Un 8B al que le das
treinta y ocho partidos y le pides «el marcador exacto» te da uno, con mucha
seguridad y ninguna base: los inventa, y suenan perfectos. Eso es lo peor que
podría hacer este proyecto.

**Cómo se calculan los goles.** El modelo clásico de fuerzas multiplicativas,
que es el que hay detrás de casi todo lo que se publica:

    λ_local   = media_liga × ataque(local) × defensa(visitante) × ventaja
    λ_visita  = media_liga × ataque(visitante) × defensa(local) ÷ ventaja

donde ``ataque(e)`` es lo que marca ese equipo dividido por lo que marca un
equipo medio de su liga, ``defensa(e)`` lo mismo con lo que encaja, y
``ventaja`` sale de comparar lo que se marca en casa con lo que se marca fuera
en esa competición. Con las dos lambdas, la matriz de marcadores es el producto
de dos Poisson, y de ahí salen el 1X2, los más/menos y el «marcan los dos».

**Se prefiere el xG a los goles** cuando hay muestra: marcar dos con 0,4 de xG
es suerte, y la suerte no se repite. Se dice siempre cuál de los dos se ha
usado.

**Córners y tarjetas** van por la media de lo que hace uno y lo que concede el
otro, y las tarjetas además por el árbitro si está identificado y tiene
partidos suficientes.

Lo que este módulo **no** hace, dicho aquí y en cada respuesta: no corrige la
correlación entre los dos marcadores (Dixon-Coles), así que los resultados
bajos —0-0, 1-1— salen algo por debajo de lo real; y no sabe de lesiones,
rotaciones ni de si el partido no vale nada. El mercado sí sabe de todo eso, y
por eso cada pronóstico se compara con la cuota cuando la hay: **donde coinciden
no hay nada que ganar**, solo algo que entender.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .almacen import Almacen

#: Por debajo de esto no se pronostica: se dice que falta muestra. Cinco
#: partidos por equipo es poquísimo, y aun así es el suelo por debajo del cual
#: el número sería una broma.
MINIMO_PARTIDOS = 5
#: Y por debajo de esto no se usa el xG, se usan los goles.
MINIMO_PARA_XG = 4
#: Partidos del árbitro para que su ritmo de tarjetas pese algo.
MINIMO_ARBITRO = 8
#: Cuántos partidos «de equipo medio» pesan como creencia previa.
#:
#: Sin esto el modelo multiplicativo se dispara: un equipo que en diez partidos
#: ha marcado el doble de la media contra otro que ha encajado el doble da
#: lambdas de cinco goles, que no existen. Y no es un fallo de la fórmula, es
#: que con diez partidos **no se sabe** que un equipo sea el doble de bueno: lo
#: parece. Así que la fuerza medida se tira hacia la media según la muestra —con
#: diez partidos y un previo de ocho se queda a medio camino—, que es lo que
#: hace cualquier ajuste serio y lo que evita el ridículo.
PRIOR_PARTIDOS = 8
#: Hasta qué marcador se construye la matriz. Con λ de 1,5 la cola por encima
#: de 8 es inapreciable, y cerrarla evita una matriz infinita.
MAXIMO_GOLES = 8

#: Las líneas de las que habla la gente. No son las únicas, son las que se usan.
LINEAS_GOLES = (0.5, 1.5, 2.5, 3.5, 4.5)
LINEAS_CORNERS = (7.5, 8.5, 9.5, 10.5, 11.5)
LINEAS_TARJETAS = (2.5, 3.5, 4.5, 5.5)


# ------------------------------------------------------------------ Poisson

def poisson(lam: float, k: int) -> float:
    """P(X = k) para una Poisson de media ``lam``.

    Por logaritmos con ``lgamma``: con lambdas pequeñas y k pequeños daría
    igual, pero el factorial directo se desborda en cuanto alguien pide una
    matriz grande, y desbordarse en silencio es lo que no puede pasar.
    """
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def cola_superior(lam: float, linea: float) -> float:
    """P(X > línea) para una Poisson. Con línea 2,5 es P(X ≥ 3)."""
    umbral = math.floor(linea) + 1
    acumulada = sum(poisson(lam, k) for k in range(umbral))
    return max(0.0, min(1.0, 1 - acumulada))


def matriz(lam_local: float, lam_visitante: float,
           maximo: int = MAXIMO_GOLES) -> list[list[float]]:
    """La probabilidad de cada marcador, suponiendo los dos lados independientes.

    El supuesto de independencia es el que falla en los resultados bajos: un
    0-0 es más frecuente de lo que dice el producto. Se dice en la respuesta en
    vez de disimularlo.
    """
    locales = [poisson(lam_local, g) for g in range(maximo + 1)]
    visitantes = [poisson(lam_visitante, g) for g in range(maximo + 1)]
    return [[pl * pv for pv in visitantes] for pl in locales]


# ------------------------------------------------------------------- fuerzas

def encoger(bruto: float, partidos: int, prior: int = PRIOR_PARTIDOS) -> float:
    """Tira una fuerza medida hacia la media, según lo corta que sea la muestra.

    Con muchos partidos apenas la toca; con pocos la deja casi en 1, que es
    decir «de este equipo todavía no sé nada especial». Es la diferencia entre
    un pronóstico y una extrapolación.
    """
    if partidos <= 0:
        return 1.0
    peso = partidos / (partidos + prior)
    return 1 + peso * (bruto - 1)


@dataclass
class Fuerza:
    """Lo que ataca y lo que defiende un equipo, en relación con su liga."""

    equipo_id: int
    equipo: str
    partidos: int
    marca: float
    concede: float
    ataque: float            # ya encogida hacia la media
    defensa: float
    ataque_bruto: float      # lo que ha hecho, sin encoger
    defensa_bruta: float
    fuente: str              # "xG" o "goles"

    def as_dict(self) -> dict:
        return {"equipo": self.equipo, "partidos": self.partidos,
                "marca_por_partido": round(self.marca, 2),
                "concede_por_partido": round(self.concede, 2),
                "ataque": round(self.ataque, 2), "defensa": round(self.defensa, 2),
                "ataque_sin_encoger": round(self.ataque_bruto, 2),
                "defensa_sin_encoger": round(self.defensa_bruta, 2),
                "medido_en": self.fuente}


def _medias_de_goles(almacen: Almacen, liga_id: int | None) -> dict:
    """Lo que se marca en esa liga, en casa y fuera. La vara de medir."""
    sql = ("SELECT AVG(goles_local) AS local, AVG(goles_visitante) AS visitante, "
           "COUNT(*) AS n FROM partidos WHERE estado = 'finished' "
           "AND goles_local IS NOT NULL")
    parametros: tuple = ()
    if liga_id:
        sql += " AND liga_id = ?"
        parametros = (liga_id,)
    fila = almacen.consulta(sql, parametros)[0]
    if not fila["n"]:
        return {"partidos": 0}
    local, visitante = fila["local"] or 0.0, fila["visitante"] or 0.0
    media = (local + visitante) / 2
    return {
        "partidos": fila["n"],
        "en_casa": round(local, 3),
        "fuera": round(visitante, 3),
        "por_equipo": round(media, 3),
        # De cuánto es jugar en casa, en esta liga y no en abstracto.
        "ventaja_local": round(math.sqrt(local / visitante), 3) if visitante else 1.0,
    }


def _xg_de(almacen: Almacen, partidos: list[dict], equipo_id: int) -> tuple[float, float, int]:
    """(xG a favor, xG en contra, partidos con dato) de una lista de partidos."""
    ids = [p["id"] for p in partidos]
    if not ids:
        return (0.0, 0.0, 0)
    filas = almacen.estadisticas_de_partidos(ids, claves=["expectedGoals"])
    favor, contra = [], []
    for fila in filas:
        es_local = fila.get("local_id") == equipo_id
        mio = fila.get("local") if es_local else fila.get("visitante")
        suyo = fila.get("visitante") if es_local else fila.get("local")
        if mio is not None and suyo is not None:
            favor.append(mio)
            contra.append(suyo)
    if not favor:
        return (0.0, 0.0, 0)
    return (sum(favor) / len(favor), sum(contra) / len(contra), len(favor))


def _goles_de(partidos: list[dict], equipo_id: int) -> tuple[float, float, int]:
    favor, contra = [], []
    for partido in partidos:
        local, visitante = partido.get("goles_local"), partido.get("goles_visitante")
        if local is None or visitante is None:
            continue
        es_local = partido.get("local_id") == equipo_id
        favor.append(local if es_local else visitante)
        contra.append(visitante if es_local else local)
    if not favor:
        return (0.0, 0.0, 0)
    return (sum(favor) / len(favor), sum(contra) / len(contra), len(favor))


def fuerza_de(almacen: Almacen, equipo_id: int, nombre: str, liga: dict,
              ultimos: int = 10, antes_de: str | None = None,
              media_xg_liga: float | None = None) -> Fuerza | None:
    """Ataque y defensa de un equipo, relativos a su liga.

    ``antes_de`` corta por fecha: pronosticar un partido con datos posteriores
    a él da un acierto espectacular y completamente falso.
    """
    partidos = almacen.partidos_de_equipo(equipo_id, ultimos=ultimos, antes_de=antes_de)
    if len(partidos) < MINIMO_PARTIDOS:
        return None

    marca_xg, concede_xg, con_xg = _xg_de(almacen, partidos, equipo_id)
    if con_xg >= MINIMO_PARA_XG and media_xg_liga:
        marca, concede, fuente, base = marca_xg, concede_xg, "xG", media_xg_liga
    else:
        marca, concede, _ = _goles_de(partidos, equipo_id)
        fuente, base = "goles", liga.get("por_equipo") or 0.0
    if not base:
        return None
    ataque_bruto, defensa_bruta = marca / base, concede / base
    cuantos = len(partidos)
    return Fuerza(equipo_id=equipo_id, equipo=nombre, partidos=cuantos,
                  marca=marca, concede=concede,
                  ataque=encoger(ataque_bruto, cuantos),
                  defensa=encoger(defensa_bruta, cuantos),
                  ataque_bruto=ataque_bruto, defensa_bruta=defensa_bruta,
                  fuente=fuente)


def _media_xg_liga(almacen: Almacen, liga_id: int | None) -> float | None:
    sql = ("SELECT AVG(e.local) AS l, AVG(e.visitante) AS v, COUNT(*) AS n "
           "FROM estadisticas e JOIN partidos p ON p.id = e.partido_id "
           "WHERE e.clave = 'expectedGoals' AND e.periodo = 'ALL' "
           "AND p.estado = 'finished'")
    parametros: tuple = ()
    if liga_id:
        sql += " AND p.liga_id = ?"
        parametros = (liga_id,)
    fila = almacen.consulta(sql, parametros)[0]
    if not fila["n"] or fila["l"] is None:
        return None
    return ((fila["l"] or 0) + (fila["v"] or 0)) / 2


# ------------------------------------------------------- lo que sale de ahí

def _desde_la_matriz(rejilla: list[list[float]]) -> dict:
    """1X2, marcadores más probables, más/menos y «marcan los dos»."""
    local = empate = visitante = 0.0
    ambos = 0.0
    por_total: dict[int, float] = {}
    marcadores: list[tuple[str, float]] = []
    for gl, fila in enumerate(rejilla):
        for gv, probabilidad in enumerate(fila):
            if gl > gv:
                local += probabilidad
            elif gl == gv:
                empate += probabilidad
            else:
                visitante += probabilidad
            if gl and gv:
                ambos += probabilidad
            por_total[gl + gv] = por_total.get(gl + gv, 0.0) + probabilidad
            marcadores.append((f"{gl}-{gv}", probabilidad))

    total = local + empate + visitante or 1.0
    marcadores.sort(key=lambda m: -m[1])
    mas_de = {}
    for linea in LINEAS_GOLES:
        umbral = math.floor(linea) + 1
        mas_de[str(linea)] = round(
            sum(p for g, p in por_total.items() if g >= umbral) / total, 4)
    return {
        "1x2": {"local": round(local / total, 4), "empate": round(empate / total, 4),
                "visitante": round(visitante / total, 4)},
        "marcadores": [{"marcador": m, "probabilidad": round(p / total, 4)}
                       for m, p in marcadores[:8]],
        "mas_de": mas_de,
        "ambos_marcan": round(ambos / total, 4),
    }


def _media_de_dos_lados(almacen: Almacen, clave: str, local: list[dict],
                        visitante: list[dict], local_id: int,
                        visitante_id: int) -> dict:
    """Lo que hace uno y lo que concede el otro, promediado. Para córners y tarjetas.

    La media de las dos vistas es lo estándar: si el Girona saca seis córners y
    al Osasuna le sacan ocho, lo razonable es esperar siete, no seis ni ocho.
    """
    def lados(partidos: list[dict], equipo_id: int) -> tuple[float, float, int]:
        ids = [p["id"] for p in partidos]
        if not ids:
            return (0.0, 0.0, 0)
        filas = almacen.estadisticas_de_partidos(ids, claves=[clave])
        favor, contra = [], []
        for fila in filas:
            es_local = fila.get("local_id") == equipo_id
            mio = fila.get("local") if es_local else fila.get("visitante")
            suyo = fila.get("visitante") if es_local else fila.get("local")
            if mio is not None:
                favor.append(mio)
            if suyo is not None:
                contra.append(suyo)
        return (sum(favor) / len(favor) if favor else 0.0,
                sum(contra) / len(contra) if contra else 0.0, len(favor))

    hace_l, concede_l, n_l = lados(local, local_id)
    hace_v, concede_v, n_v = lados(visitante, visitante_id)
    if not (n_l and n_v):
        return {"disponible": False,
                "nota": f"No hay '{clave}' guardado de los dos equipos. Abastece el partido."}
    esperado_local = (hace_l + concede_v) / 2
    esperado_visitante = (hace_v + concede_l) / 2
    return {
        "disponible": True,
        "esperado_local": round(esperado_local, 2),
        "esperado_visitante": round(esperado_visitante, 2),
        "esperado_total": round(esperado_local + esperado_visitante, 2),
        "muestra": {"local": n_l, "visitante": n_v},
    }


def _lineas(lam: float, lineas: tuple[float, ...]) -> dict:
    return {str(x): round(cola_superior(lam, x), 4) for x in lineas}


# ------------------------------------------------------------------ público

def pronostico(almacen: Almacen, partido, cliente=None, ultimos: int = 10) -> dict:
    """Marcador, córners y tarjetas de un partido, con lo que los sostiene."""
    from .previa import _resolver

    evento = partido if hasattr(partido, "home") else _resolver(almacen, partido, cliente)
    if evento is None:
        return {"disponible": False,
                "nota": "No encuentro ese partido ni en la memoria ni en la API."}

    liga = _medias_de_goles(almacen, evento.unique_tournament_id)
    if not liga.get("partidos"):
        return {"disponible": False,
                "nota": "No tengo partidos guardados de esa competición. "
                        "Abastece el partido primero: te trae su contexto entero."}

    media_xg = _media_xg_liga(almacen, evento.unique_tournament_id)
    antes_de = evento.date or None
    fuerzas = {}
    for lado, equipo in (("local", evento.home), ("visitante", evento.away)):
        if not equipo.id:
            continue
        fuerzas[lado] = fuerza_de(almacen, equipo.id, equipo.name, liga,
                                  ultimos=ultimos, antes_de=antes_de,
                                  media_xg_liga=media_xg)

    salida: dict[str, Any] = {
        "disponible": True,
        "partido": {"id": evento.id, "local": evento.home.name,
                    "visitante": evento.away.name, "fecha": evento.date,
                    "competicion": evento.tournament, "arbitro": evento.referee},
        "liga": liga,
    }

    if not (fuerzas.get("local") and fuerzas.get("visitante")):
        faltan = [lado for lado in ("local", "visitante")
                  if not fuerzas.get(lado)]
        salida["disponible"] = False
        salida["nota"] = (
            f"Necesito al menos {MINIMO_PARTIDOS} partidos guardados de cada equipo y "
            f"me faltan los del {' y el '.join(faltan)}. Abastece el partido: te trae "
            "los últimos diez de los dos.")
        return salida

    local, visitante = fuerzas["local"], fuerzas["visitante"]
    base = media_xg if local.fuente == "xG" and media_xg else (liga.get("por_equipo") or 0)
    ventaja = liga.get("ventaja_local") or 1.0
    lam_local = base * local.ataque * visitante.defensa * ventaja
    lam_visitante = base * visitante.ataque * local.defensa / (ventaja or 1.0)

    rejilla = matriz(lam_local, lam_visitante)
    salida["goles"] = {
        "esperados": {"local": round(lam_local, 2), "visitante": round(lam_visitante, 2),
                      "total": round(lam_local + lam_visitante, 2)},
        "medido_en": local.fuente,
        "ventaja_local": ventaja,
        "fuerzas": {"local": local.as_dict(), "visitante": visitante.as_dict()},
        **_desde_la_matriz(rejilla),
    }

    # Córners y tarjetas: partidos de cada equipo, una sola vez.
    partidos_local = almacen.partidos_de_equipo(local.equipo_id, ultimos=ultimos,
                                                antes_de=antes_de)
    partidos_visitante = almacen.partidos_de_equipo(visitante.equipo_id, ultimos=ultimos,
                                                    antes_de=antes_de)

    corners = _media_de_dos_lados(almacen, "cornerKicks", partidos_local,
                                  partidos_visitante, local.equipo_id, visitante.equipo_id)
    if corners.get("disponible"):
        corners["mas_de"] = _lineas(corners["esperado_total"], LINEAS_CORNERS)
    salida["corners"] = corners

    salida["tarjetas"] = _tarjetas(almacen, evento, partidos_local, partidos_visitante,
                                   local, visitante)
    salida["mercado"] = _contra_el_mercado(almacen, evento, salida["goles"]["1x2"])
    salida["como_se_calcula"] = (
        f"Goles: fuerzas multiplicativas sobre {liga['partidos']} partidos guardados de "
        f"la competición, medidas en {local.fuente}. Las fuerzas van encogidas hacia la "
        f"media de la liga según la muestra ({local.partidos} y {visitante.partidos} "
        "partidos): con diez partidos no se sabe que un equipo sea el doble de bueno, lo "
        f"parece. La ventaja de jugar en casa ({ventaja:.2f}) sale de esa misma liga, no "
        "de un número de manual. Córners y tarjetas: la media entre lo que hace uno y lo "
        "que concede el otro. Las líneas salen de una Poisson con esa media."
    )
    salida["lo_que_no_dice"] = (
        "No sabe de lesiones, rotaciones, ni de si el partido se juega a nada. No "
        "corrige la correlación entre los dos marcadores, así que el 0-0 y el 1-1 "
        "salen algo por debajo de lo real. Y el marcador más probable de un partido "
        "de fútbol ronda el 10-12 %: que uno encabece la lista no significa que vaya "
        "a pasar, significa que es el menos raro de muchos."
    )
    return salida


def _tarjetas(almacen: Almacen, evento, partidos_local: list[dict],
              partidos_visitante: list[dict], local: Fuerza, visitante: Fuerza) -> dict:
    from .perfiles import perfil_de_arbitro

    datos = _media_de_dos_lados(almacen, "yellowCards", partidos_local, partidos_visitante,
                                local.equipo_id, visitante.equipo_id)
    if not datos.get("disponible"):
        return datos

    esperado = datos["esperado_total"]
    datos["arbitro"] = {"disponible": False, "nota": "Sin árbitro designado todavía."}
    if evento.referee:
        perfil = perfil_de_arbitro(almacen, evento.referee)
        if perfil.get("disponible") and perfil["partidos_mirados"] >= MINIMO_ARBITRO:
            # `perfil_de_arbitro` da amarillas **por equipo** (promedia los dos
            # lados) y aquí se compara con el total del partido, así que hay
            # que doblarlo. Dividir unos por otros sin mirar las unidades daba
            # un factor de 0,5 clavado y partía por la mitad todas las tarjetas.
            suyas = perfil["por_partido"]["amarillas"] * 2
            media = _media_de_amarillas(almacen, evento.unique_tournament_id)
            factor = (suyas / media) if media else 1.0
            datos["arbitro"] = {
                "disponible": True, "arbitro": perfil["arbitro"],
                "partidos_mirados": perfil["partidos_mirados"],
                "amarillas_por_partido": round(suyas, 2),
                "media_de_la_liga": round(media, 2) if media else None,
                "factor": round(factor, 2),
                "lectura": (f"{perfil['arbitro']} saca {suyas:.2f} amarillas por "
                            f"partido (las dos partes) frente a las {media:.2f} de su "
                            "liga" if media else None),
            }
            esperado = round(esperado * factor, 2)
        else:
            datos["arbitro"] = {
                "disponible": False,
                "nota": (f"De {evento.referee} tengo "
                         f"{perfil.get('partidos_mirados', 0)} partidos y hacen falta "
                         f"{MINIMO_ARBITRO}: no le aplico ningún ajuste."),
            }
    datos["esperado_total_con_arbitro"] = esperado
    datos["mas_de"] = _lineas(esperado, LINEAS_TARJETAS)
    return datos


def _media_de_amarillas(almacen: Almacen, liga_id: int | None) -> float | None:
    """Amarillas por partido en esa liga, **sumando los dos equipos**."""
    sql = ("SELECT AVG(e.local + e.visitante) AS m, COUNT(*) AS n "
           "FROM estadisticas e JOIN partidos p ON p.id = e.partido_id "
           "WHERE e.clave = 'yellowCards' AND e.periodo = 'ALL' AND p.estado = 'finished'")
    parametros: tuple = ()
    if liga_id:
        sql += " AND p.liga_id = ?"
        parametros = (liga_id,)
    fila = almacen.consulta(sql, parametros)[0]
    return fila["m"] if fila["n"] else None


def _contra_el_mercado(almacen: Almacen, evento, mio: dict) -> dict:
    """Lo que dice la cuota frente a lo que dice esto. Es la pregunta honesta.

    El mercado es un modelo, y uno muy bueno: sabe de lesiones, de alineaciones
    y de dinero. Donde coincide con este cálculo no hay nada que ganar. Donde
    no coincide, lo más probable sigue siendo que se equivoque este.
    """
    guardadas = almacen.cuotas_de(evento.id)
    if not guardadas:
        return {"disponible": False,
                "nota": "No tengo cuotas de este partido. Con ellas se podría ver si "
                        "este pronóstico dice algo que el mercado no diga ya."}
    suyas = guardadas.get("probabilidades") or {}
    diferencias = {lado: round(mio.get(lado, 0) - (suyas.get(lado) or 0), 4)
                   for lado in ("local", "empate", "visitante")}
    mayor = max(diferencias.values(), key=abs) if diferencias else 0.0
    return {
        "disponible": True,
        "mercado": suyas,
        "mio": mio,
        "diferencias": diferencias,
        "lectura": (
            "Este cálculo y el mercado dicen prácticamente lo mismo: no hay nada "
            "que ganar aquí, solo algo que entender."
            if abs(mayor) < 0.05 else
            f"Este cálculo se separa {mayor:+.0%} del mercado en su mayor diferencia. "
            "Antes de creértelo: el mercado sabe de alineaciones y bajas, y esto no."
        ),
    }


def texto(datos: dict, ancho: int = 76) -> list[str]:
    """El pronóstico en líneas, para el terminal y para Telegram."""
    import textwrap

    if not datos.get("disponible"):
        return [datos.get("nota", "No hay pronóstico.")]

    p = datos["partido"]
    g = datos["goles"]
    lineas = [f"{p['local']} - {p['visitante']}   ({p['competicion']}, {p['fecha']})", ""]
    lineas.append(f"Goles esperados: {g['esperados']['local']} - "
                  f"{g['esperados']['visitante']}   (medido en {g['medido_en']})")
    uno = g["1x2"]
    lineas.append(f"  1X2:  {uno['local']:.0%} local · {uno['empate']:.0%} empate · "
                  f"{uno['visitante']:.0%} visitante")
    lineas.append("  Marcadores más probables:")
    for marcador in g["marcadores"][:5]:
        lineas.append(f"      {marcador['marcador']}   {marcador['probabilidad']:.1%}")
    lineas.append("  Más de:  " + " · ".join(
        f"{linea} {valor:.0%}" for linea, valor in g["mas_de"].items()))
    lineas.append(f"  Marcan los dos: {g['ambos_marcan']:.0%}")
    lineas.append("")

    corners = datos.get("corners") or {}
    if corners.get("disponible"):
        lineas.append(f"Córners: {corners['esperado_total']} esperados "
                      f"({corners['esperado_local']} - {corners['esperado_visitante']})")
        lineas.append("  Más de:  " + " · ".join(
            f"{linea} {valor:.0%}" for linea, valor in corners["mas_de"].items()))
    else:
        lineas.append(f"Córners: {corners.get('nota', 'sin datos')}")
    lineas.append("")

    tarjetas = datos.get("tarjetas") or {}
    if tarjetas.get("disponible"):
        arbitro = tarjetas.get("arbitro") or {}
        total = tarjetas.get("esperado_total_con_arbitro", tarjetas["esperado_total"])
        lineas.append(f"Amarillas: {total} esperadas")
        if arbitro.get("disponible"):
            lineas.append(f"  {arbitro['lectura']} ({arbitro['partidos_mirados']} partidos)")
        elif arbitro.get("nota"):
            lineas.append(f"  {arbitro['nota']}")
        lineas.append("  Más de:  " + " · ".join(
            f"{linea} {valor:.0%}" for linea, valor in tarjetas["mas_de"].items()))
    else:
        lineas.append(f"Amarillas: {tarjetas.get('nota', 'sin datos')}")
    lineas.append("")

    mercado = datos.get("mercado") or {}
    if mercado.get("disponible"):
        suyas = mercado["mercado"]
        lineas.append(f"El mercado dice: {suyas.get('local', 0):.0%} · "
                      f"{suyas.get('empate', 0):.0%} · {suyas.get('visitante', 0):.0%}")
    for texto_largo in (mercado.get("lectura"), datos.get("como_se_calcula"),
                        datos.get("lo_que_no_dice")):
        if texto_largo:
            lineas.append("")
            lineas += textwrap.wrap(texto_largo, ancho)
    return lineas


__all__ = ["LINEAS_CORNERS", "LINEAS_GOLES", "LINEAS_TARJETAS", "MINIMO_PARTIDOS",
           "PRIOR_PARTIDOS", "Fuerza", "cola_superior", "encoger", "fuerza_de",
           "matriz", "poisson", "pronostico", "texto"]
