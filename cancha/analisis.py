"""Los números que un modelo no debe calcular a ojo.

Un LLM sumando treinta valores de xG te da un número redondo, con aplomo y
equivocado. Y las preguntas que de verdad importan al analizar un partido no se
contestan mirando una tabla:

* ¿cuándo dejó de ser un partido igualado?
* ¿ganó el que mereció, o el que tuvo el día?
* ¿esos 2.58 de xG son tres ocasiones clarísimas o quince disparos de lejos?

Todo lo de aquí son funciones puras sobre un informe ya traído: no tocan la red,
así que son rápidas, deterministas y fáciles de comprobar. Y sobre todo, son
**correctas**, que es lo que no se puede decir de la aritmética de un modelo.
"""

from __future__ import annotations

from typing import Any

#: Valor de xG por debajo del cual un disparo es poco más que un intento.
UMBRAL_LEJANO = 0.05
#: A partir de aquí, ocasión clara.
UMBRAL_CLARA = 0.30


def _lados(informe) -> tuple[str, str]:
    return informe.event.home.name, informe.event.away.name


def _tiros_por_lado(informe) -> dict[str, list[dict]]:
    local, visitante = _lados(informe)
    salida: dict[str, list[dict]] = {local: [], visitante: []}
    for tiro in informe.shots():
        salida[local if tiro.get("isHome") else visitante].append(tiro)
    return salida


# --------------------------------------------------------------- xG acumulado

def carrera_xg(informe, cada: int = 5) -> dict:
    """El xG acumulado de cada equipo minuto a minuto.

    Es la forma honesta de contar un partido: enseña *cuándo* se generó el
    peligro, no solo cuánto. Un 2.5 hecho en diez minutos finales no es el mismo
    partido que un 2.5 repartido.
    """
    local, visitante = _lados(informe)
    tiros = sorted(informe.shots(), key=lambda t: t.get("time") or 0)
    if not tiros:
        return {"disponible": False, "nota": "Este partido no trae mapa de tiros."}

    acumulado = {local: 0.0, visitante: 0.0}
    serie = []
    for tiro in tiros:
        equipo = local if tiro.get("isHome") else visitante
        acumulado[equipo] += tiro.get("xg") or 0
        serie.append({
            "minuto": tiro.get("time"),
            "equipo": equipo,
            "jugador": (tiro.get("player") or {}).get("name", ""),
            "xg_del_tiro": round(tiro.get("xg") or 0, 3),
            "gol": tiro.get("shotType") == "goal",
            local: round(acumulado[local], 2),
            visitante: round(acumulado[visitante], 2),
        })

    # Cuándo se rompió el partido: el minuto en que uno se pone por delante en
    # xG y ya no lo pierde.
    lider_final = local if acumulado[local] > acumulado[visitante] else visitante
    rival = visitante if lider_final == local else local
    rompio = None
    for punto in serie:
        if punto[lider_final] > punto[rival]:
            rompio = rompio if rompio is not None else punto["minuto"]
        else:
            rompio = None

    return {
        "disponible": True,
        "total": {local: round(acumulado[local], 2), visitante: round(acumulado[visitante], 2)},
        "marcador": informe.event.scoreline,
        "manda_en_xg": lider_final if abs(acumulado[local] - acumulado[visitante]) > 0.2 else None,
        "desde_el_minuto": rompio,
        "serie": serie if cada <= 1 else _resumir_serie(serie, local, visitante, cada),
    }


def _resumir_serie(serie: list[dict], local: str, visitante: str, cada: int) -> list[dict]:
    """Deja un punto por tramo, para no soltarle 30 filas al modelo."""
    puntos: dict[int, dict] = {}
    for punto in serie:
        tramo = int((punto["minuto"] or 0) // cada) * cada
        puntos[tramo] = {"minuto": tramo + cada, local: punto[local], visitante: punto[visitante]}
    return list(puntos.values())


# ------------------------------------------------------------ calidad de tiro

def calidad_de_tiro(informe) -> dict:
    """Si el xG viene de ocasiones claras o de disparar desde lejos.

    Dos equipos con el mismo xG pueden haber jugado partidos opuestos: tres
    mano a mano o quince chutes desde la frontal. Esto los distingue.
    """
    por_equipo = _tiros_por_lado(informe)
    if not any(por_equipo.values()):
        return {"disponible": False, "nota": "Este partido no trae mapa de tiros."}

    salida = {}
    for equipo, tiros in por_equipo.items():
        if not tiros:
            salida[equipo] = {"tiros": 0}
            continue
        valores = [t.get("xg") or 0 for t in tiros]
        goles = sum(1 for t in tiros if t.get("shotType") == "goal")
        total = sum(valores)
        salida[equipo] = {
            "tiros": len(tiros),
            "xg_total": round(total, 2),
            "xg_por_tiro": round(total / len(tiros), 3),
            "mejor_ocasion": round(max(valores), 3) if valores else 0,
            "ocasiones_claras": sum(1 for v in valores if v >= UMBRAL_CLARA),
            "tiros_lejanos": sum(1 for v in valores if v < UMBRAL_LEJANO),
            "goles": goles,
            "diferencia_goles_xg": round(goles - total, 2),
            "lectura": _lectura_eficacia(goles - total),
        }
    return {"disponible": True, "por_equipo": salida}


def _lectura_eficacia(diferencia: float) -> str:
    if diferencia > 1.0:
        return "Muy por encima de lo esperable: acierto excepcional o portero rival flojo."
    if diferencia > 0.3:
        return "Marcó algo más de lo que sus tiros pedían."
    if diferencia < -1.0:
        return "Muy por debajo: se dejó goles claros por el camino."
    if diferencia < -0.3:
        return "Marcó algo menos de lo que sus tiros pedían."
    return "Marcó lo que sus tiros pedían."


# --------------------------------------------------------------- por situación

def por_situacion(informe) -> dict:
    """Desglose del peligro: jugada abierta, córner, falta, penalti.

    Un equipo que solo genera a balón parado es un equipo distinto de otro con
    el mismo xG desde el juego.
    """
    por_equipo = _tiros_por_lado(informe)
    if not any(por_equipo.values()):
        return {"disponible": False, "nota": "Este partido no trae mapa de tiros."}

    salida: dict[str, Any] = {}
    for equipo, tiros in por_equipo.items():
        bloques: dict[str, dict] = {}
        for tiro in tiros:
            situacion = tiro.get("situation") or "sin clasificar"
            bloque = bloques.setdefault(situacion, {"tiros": 0, "xg": 0.0, "goles": 0})
            bloque["tiros"] += 1
            bloque["xg"] += tiro.get("xg") or 0
            bloque["goles"] += 1 if tiro.get("shotType") == "goal" else 0
        for bloque in bloques.values():
            bloque["xg"] = round(bloque["xg"], 2)
        salida[equipo] = dict(sorted(bloques.items(), key=lambda kv: -kv[1]["xg"]))
    return {"disponible": True, "por_equipo": salida}


# ------------------------------------------------------- aportación por jugador

def aportacion_jugadores(informe, minimo_xg: float = 0.0) -> dict:
    """Quién generó el peligro: xG disparado, asistencias y su valoración.

    Ordenado por xG generado, que es más informativo que la nota: la nota premia
    el partido completo, esto dice quién puso el equipo cerca del gol.
    """
    local, visitante = _lados(informe)
    filas: dict[str, dict] = {}

    for tiro in informe.shots():
        jugador = (tiro.get("player") or {}).get("name", "")
        if not jugador:
            continue
        fila = filas.setdefault(jugador, {
            "jugador": jugador,
            "equipo": local if tiro.get("isHome") else visitante,
            "tiros": 0, "xg": 0.0, "goles": 0, "asistencias": 0, "rating": None,
        })
        fila["tiros"] += 1
        fila["xg"] += tiro.get("xg") or 0
        fila["goles"] += 1 if tiro.get("shotType") == "goal" else 0

    # Las asistencias salen de la cronología, que es donde la API las pone.
    for incidencia in informe.incidents("goal"):
        asistente = (incidencia.get("assist1") or {}).get("name", "")
        if not asistente:
            continue
        fila = filas.setdefault(asistente, {
            "jugador": asistente,
            "equipo": local if incidencia.get("isHome") else visitante,
            "tiros": 0, "xg": 0.0, "goles": 0, "asistencias": 0, "rating": None,
        })
        fila["asistencias"] += 1

    for valoracion in informe.ratings():
        if valoracion["jugador"] in filas:
            filas[valoracion["jugador"]]["rating"] = valoracion["rating"]

    salida = []
    for fila in filas.values():
        fila["xg"] = round(fila["xg"], 3)
        if fila["xg"] >= minimo_xg or fila["asistencias"]:
            salida.append(fila)
    salida.sort(key=lambda f: (-f["xg"], -f["goles"]))
    return {"disponible": bool(salida), "jugadores": salida}


# ----------------------------------------------------------- puntos esperados

def distribucion_de_goles(xgs: list[float]) -> list[float]:
    """Probabilidad de marcar 0, 1, 2… goles, a partir de los xG de cada tiro.

    Cada disparo es una moneda trucada con probabilidad su xG. La distribución
    de la suma se calcula convolucionando una a una: es exacta, no una
    aproximación de Poisson.

    El supuesto que sí se hace es que los disparos son independientes entre sí.
    No es del todo cierto —un rechace nace del tiro anterior— pero es el
    supuesto estándar y el error es pequeño.
    """
    distribucion = [1.0]
    for probabilidad in xgs:
        p = min(max(probabilidad or 0.0, 0.0), 1.0)
        siguiente = [0.0] * (len(distribucion) + 1)
        for goles, acumulada in enumerate(distribucion):
            siguiente[goles] += acumulada * (1 - p)
            siguiente[goles + 1] += acumulada * p
        distribucion = siguiente
    return distribucion


def puntos_esperados(informe) -> dict:
    """Cuántos puntos merecía cada equipo, según sus ocasiones.

    Con la distribución de goles de cada uno se calcula la probabilidad de
    victoria, empate y derrota, y de ahí los puntos esperados. Contesta a la
    pregunta que todo el mundo discute después de un partido: ¿ganó el que
    mereció?
    """
    por_equipo = _tiros_por_lado(informe)
    local, visitante = _lados(informe)
    if not any(por_equipo.values()):
        return {"disponible": False, "nota": "Hacen falta los tiros con su xG."}

    dist_local = distribucion_de_goles([t.get("xg") or 0 for t in por_equipo[local]])
    dist_visitante = distribucion_de_goles([t.get("xg") or 0 for t in por_equipo[visitante]])

    gana_local = empate = gana_visitante = 0.0
    for goles_l, p_l in enumerate(dist_local):
        for goles_v, p_v in enumerate(dist_visitante):
            conjunta = p_l * p_v
            if goles_l > goles_v:
                gana_local += conjunta
            elif goles_l == goles_v:
                empate += conjunta
            else:
                gana_visitante += conjunta

    puntos_l = 3 * gana_local + empate
    puntos_v = 3 * gana_visitante + empate
    reales = _puntos_reales(informe)

    return {
        "disponible": True,
        "probabilidades": {
            f"gana {local}": round(gana_local, 3),
            "empate": round(empate, 3),
            f"gana {visitante}": round(gana_visitante, 3),
        },
        "puntos_esperados": {local: round(puntos_l, 2), visitante: round(puntos_v, 2)},
        "puntos_reales": reales,
        "diferencia": {
            local: round((reales.get(local, 0)) - puntos_l, 2),
            visitante: round((reales.get(visitante, 0)) - puntos_v, 2),
        },
        "lectura": _lectura_justicia(reales, {local: puntos_l, visitante: puntos_v},
                                     local, visitante),
        "supuesto": "Los disparos se tratan como independientes entre sí.",
    }


def _puntos_reales(informe) -> dict[str, int]:
    local, visitante = _lados(informe)
    ganador = informe.event.winner()
    if ganador == "home":
        return {local: 3, visitante: 0}
    if ganador == "away":
        return {local: 0, visitante: 3}
    if ganador == "draw":
        return {local: 1, visitante: 1}
    return {}


def _lectura_justicia(reales: dict, esperados: dict, local: str, visitante: str) -> str:
    if not reales:
        return "El partido no ha terminado o no tiene resultado."
    diferencias = {e: reales.get(e, 0) - esperados[e] for e in (local, visitante)}
    afortunado = max(diferencias, key=lambda e: diferencias[e])
    margen = diferencias[afortunado]
    if margen < 0.5:
        return "El resultado se ajusta a lo que dijeron las ocasiones."
    if margen < 1.5:
        return f"{afortunado} sacó algo más de lo que merecía por ocasiones."
    return f"{afortunado} se llevó bastante más de lo que las ocasiones daban."


# ---------------------------------------------------------------- por periodos

def por_periodos(informe, claves: list[str] | None = None) -> dict:
    """Primera parte contra segunda, con la diferencia hecha.

    Sirve para localizar el ajuste táctico: qué cambió del descanso a la vuelta.
    """
    interesantes = claves or [
        "ballPossession", "expectedGoals", "totalShotsOnGoal", "bigChanceCreated",
        "accuratePasses", "totalTackle", "cornerKicks",
    ]
    salida = []
    for clave in interesantes:
        primera = informe.statistic(clave, "1ST")
        segunda = informe.statistic(clave, "2ND")
        if not (primera and segunda):
            continue
        salida.append({
            "estadistica": primera.get("name") or clave,
            "clave": clave,
            "local_1a": primera.get("home"), "local_2a": segunda.get("home"),
            "visitante_1a": primera.get("away"), "visitante_2a": segunda.get("away"),
        })
    return {"disponible": bool(salida), "periodos": salida}


# -------------------------------------------------------------------- el todo

def analisis_completo(informe, cada: int = 15) -> dict:
    """Todas las métricas de golpe, para arrancar un análisis.

    Cada bloque dice si ha podido calcularse: un partido sin mapa de tiros da
    la mitad de estas cosas, y eso se ve en vez de adivinarse.
    """
    return {
        "partido": {
            "id": informe.event.id,
            "titulo": f"{informe.event.home} {informe.event.scoreline} {informe.event.away}",
            "competicion": informe.event.tournament,
            "fecha": informe.event.date,
        },
        "puntos_esperados": puntos_esperados(informe),
        "calidad_de_tiro": calidad_de_tiro(informe),
        "carrera_xg": carrera_xg(informe, cada=cada),
        "por_situacion": por_situacion(informe),
        "aportacion": aportacion_jugadores(informe, minimo_xg=0.05),
        "por_periodos": por_periodos(informe),
    }


__all__ = [
    "carrera_xg", "calidad_de_tiro", "por_situacion", "aportacion_jugadores",
    "distribucion_de_goles", "puntos_esperados", "por_periodos", "analisis_completo",
]
