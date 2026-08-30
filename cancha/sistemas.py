"""Jugador contra sistema: cómo rinde alguien según a qué se enfrenta.

Es la pregunta más interesante que se le puede hacer a estos datos y la más
fácil de contestar mal. Casi cualquier herramienta te dirá «contra bloque bajo
rinde 0,18 de xG» a partir de dos partidos, y eso no es un dato: es ruido con
formato de dato.

Aquí se hace con tres cuidados que no son opcionales:

**Uno: el sistema se mide, no se supone.** No vale decir «el Getafe es bloque
bajo». Cada partido se caracteriza por lo que pasó en él —formación, presión,
posesión— porque el mismo equipo no juega igual en casa que fuera ni contra el
primero que contra el último.

**Dos: se compara contra su liga, no contra un número absoluto.** Presionar
alto en la Premier no es lo mismo que en la Segunda. Los cortes salen de los
terciles de la propia competición.

**Tres: si no hay muestra, se dice.** Todo va normalizado por 90 minutos, todo
lleva su número de partidos, y las diferencias se contrastan contra el azar con
una prueba de Poisson. Cuando la diferencia cabe dentro de lo que explica la
suerte, la respuesta es «no se sabe», no una cifra bonita.

Lo que esto **no** puede decirte está escrito en cada respuesta: un jugador se
enfrenta a bloques bajos sobre todo cuando su equipo es favorito, así que parte
de lo que se vea será el contexto y no él.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .almacen import Almacen

#: Métricas de conteo: se puede contrastar con Poisson porque son sucesos
#: discretos y más o menos independientes dentro de un partido.
METRICAS_CONTEO = {
    "tiros": "totalShots",
    "tiros_a_puerta": "onTargetScoringAttempt",
    "goles": "goals",
    "asistencias": "goalAssist",
    "pases_clave": "keyPass",
    "regates": "wonContest",
    "duelos_ganados": "duelWon",
    "perdidas": "possessionLostCtrl",
    "faltas_recibidas": "wasFouled",
}

#: Métricas continuas: se describen, no se contrastan con Poisson.
METRICAS_CONTINUAS = {
    "xg": "expectedGoals",
    "xa": "expectedAssists",
    "toques": "touches",
    "rating": None,
}

#: Mínimos por debajo de los cuales no se concluye nada.
MINIMO_PARTIDOS = 3
MINIMO_MINUTOS = 180

#: Cuándo una diferencia deja de parecer casualidad.
P_SENAL = 0.05
P_INDICIO = 0.10


# ----------------------------------------------------------- prueba de Poisson

def _log_factorial(n: int) -> float:
    return math.lgamma(n + 1)


def poisson_cdf(k: int, lam: float) -> float:
    """P(X ≤ k) para una Poisson de media ``lam``.

    Se suma en logaritmos para que no se desborde con medias grandes.
    """
    if lam <= 0:
        return 1.0
    total = 0.0
    for i in range(int(k) + 1):
        total += math.exp(-lam + i * math.log(lam) - _log_factorial(i))
    return min(1.0, total)


def probabilidad_de_azar(observado: int, esperado: float) -> float:
    """Probabilidad de ver algo así de extremo si nada hubiera cambiado.

    Es un contraste de una cola: si observó menos de lo esperado, cuánto de
    probable era ver *tan poco*; si observó más, cuánto de probable era ver
    *tanto*. No es una prueba de hipótesis con todas las de la ley —los tiros
    de un partido no son del todo independientes— pero sí una vara honesta
    para separar «pasa algo» de «han sido seis partidos».
    """
    if esperado <= 0:
        return 1.0
    if observado <= esperado:
        return poisson_cdf(observado, esperado)
    return 1.0 - poisson_cdf(observado - 1, esperado)


def _veredicto(p: float, partidos: int, minutos: float) -> str:
    if partidos < MINIMO_PARTIDOS or minutos < MINIMO_MINUTOS:
        return "sin muestra"
    if p < P_SENAL:
        return "señal"
    if p < P_INDICIO:
        return "indicio"
    return "dentro de lo normal"


# ------------------------------------------------------- medir un sistema rival

def _stats_de(almacen: Almacen, partido_id: int) -> dict[str, dict[str, float]]:
    """Las estadísticas de un partido, separadas por lado."""
    filas = almacen.consulta(
        "SELECT clave, local, visitante FROM estadisticas "
        "WHERE partido_id = ? AND periodo = 'ALL'", (partido_id,))
    return {
        "local": {f["clave"]: f["local"] for f in filas if f["local"] is not None},
        "visitante": {f["clave"]: f["visitante"] for f in filas if f["visitante"] is not None},
    }


def presion_aproximada(defensor: dict[str, float], atacante: dict[str, float]) -> float | None:
    """Pases que concede el defensor por cada acción defensiva suya.

    Es la idea del PPDA: cuanto **más bajo**, más presiona. La aproximación
    está en que el PPDA de verdad solo cuenta las acciones en campo rival, y
    aquí no hay reparto por zonas: se usan los totales. Sirve para ordenar
    equipos entre sí, no para comparar con cifras publicadas por ahí.
    """
    acciones = sum(defensor.get(c, 0) or 0
                   for c in ("totalTackle", "interceptionWon", "fouls"))
    pases = atacante.get("passes") or 0
    if acciones <= 0 or pases <= 0:
        return None
    return round(pases / acciones, 2)


def sistema_del_rival(almacen: Almacen, partido_id: int, rival_id: int) -> dict | None:
    """Cómo jugó el rival en ese partido concreto.

    Se mide el partido, no el equipo: el mismo rival no plantea lo mismo en
    casa que fuera, ni contra el primero que contra el último.
    """
    partidos = almacen.consulta("SELECT * FROM partidos WHERE id = ?", (partido_id,))
    if not partidos:
        return None
    partido = partidos[0]
    rival_es_local = partido["local_id"] == rival_id
    lado, otro = ("local", "visitante") if rival_es_local else ("visitante", "local")

    stats = _stats_de(almacen, partido_id)
    suyas, nuestras = stats[lado], stats[otro]
    if not suyas:
        return None

    formacion = partido["formacion_local"] if rival_es_local else partido["formacion_visitante"]
    return {
        "partido_id": partido_id,
        "fecha": partido["fecha"],
        "liga_id": partido["liga_id"],
        "rival": partido["local"] if rival_es_local else partido["visitante"],
        "rival_local": rival_es_local,
        "formacion": formacion,
        "defensas": _defensas(formacion),
        "posesion": suyas.get("ballPossession"),
        "presion": presion_aproximada(suyas, nuestras),
        "despejes": suyas.get("totalClearance"),
        "tiros_concedidos": nuestras.get("totalShotsOnGoal"),
        "xg_concedido": nuestras.get("expectedGoals"),
    }


def _defensas(formacion: str | None) -> int | None:
    """Cuántos defensas dibuja una formación: el 4 o el 5 de la primera cifra."""
    if not formacion:
        return None
    primera = formacion.split("-")[0].strip()
    return int(primera) if primera.isdigit() else None


def umbrales_de_liga(almacen: Almacen, liga_id: int) -> dict:
    """Los cortes con los que se clasifica en esa competición.

    Terciles de presión y de posesión entre todos los partidos guardados de la
    liga. Sin esto, «presiona alto» sería una opinión: con esto es «está en el
    tercio que más presiona de su liga».
    """
    partidos = almacen.consulta(
        "SELECT id FROM partidos WHERE liga_id = ? AND estado = 'finished'", (liga_id,))
    presiones, posesiones = [], []
    for fila in partidos:
        stats = _stats_de(almacen, fila["id"])
        for lado, otro in (("local", "visitante"), ("visitante", "local")):
            valor = presion_aproximada(stats[lado], stats[otro])
            if valor:
                presiones.append(valor)
            posesion = stats[lado].get("ballPossession")
            if posesion:
                posesiones.append(posesion)

    def terciles(valores: list[float]) -> tuple[float, float] | None:
        if len(valores) < 12:
            return None
        ordenados = sorted(valores)
        return (ordenados[len(ordenados) // 3], ordenados[2 * len(ordenados) // 3])

    return {
        "liga_id": liga_id,
        "muestras": len(presiones),
        "presion": terciles(presiones),
        "posesion": terciles(posesiones),
    }


def clasificar(sistema: dict, umbrales: dict) -> dict[str, str]:
    """Pone etiquetas a un sistema: línea, presión y posesión.

    Todas relativas a su liga. Si no hay muestra suficiente para los cortes, se
    devuelve «sin clasificar» en vez de inventarse un umbral absoluto.
    """
    etiquetas: dict[str, str] = {}

    defensas = sistema.get("defensas")
    if defensas:
        etiquetas["linea"] = "linea de 5" if defensas >= 5 else (
            "linea de 3" if defensas == 3 else "linea de 4")

    cortes = umbrales.get("presion")
    presion = sistema.get("presion")
    if cortes and presion:
        bajo, alto = cortes
        # Menos pases por acción defensiva = presiona más.
        etiquetas["presion"] = ("presiona alto" if presion <= bajo else
                                "bloque bajo" if presion >= alto else "presion media")

    cortes = umbrales.get("posesion")
    posesion = sistema.get("posesion")
    if cortes and posesion:
        bajo, alto = cortes
        etiquetas["balon"] = ("cede el balon" if posesion <= bajo else
                              "domina el balon" if posesion >= alto else "reparte")
    return etiquetas


# --------------------------------------------------- el jugador contra el sistema

def _actuacion(fila: dict) -> dict:
    datos = {}
    if fila.get("datos"):
        try:
            datos = json.loads(fila["datos"])
        except (ValueError, TypeError):
            datos = {}
    salida = {"minutos": fila.get("minutos") or 0, "rating": fila.get("rating")}
    for nombre, clave in METRICAS_CONTEO.items():
        salida[nombre] = datos.get(clave, 0) or 0
    for nombre, clave in METRICAS_CONTINUAS.items():
        if clave:
            salida[nombre] = datos.get(clave, 0) or 0
    return salida


def _agregar(actuaciones: list[dict]) -> dict:
    """Suma y normaliza por 90 minutos un conjunto de actuaciones."""
    minutos = sum(a["minutos"] for a in actuaciones)
    if minutos <= 0:
        return {"partidos": len(actuaciones), "minutos": 0, "por_90": {}, "totales": {}}
    totales = {}
    for nombre in list(METRICAS_CONTEO) + [n for n, c in METRICAS_CONTINUAS.items() if c]:
        totales[nombre] = sum(a.get(nombre, 0) for a in actuaciones)
    notas = [a["rating"] for a in actuaciones if a.get("rating")]
    return {
        "partidos": len(actuaciones),
        "minutos": minutos,
        "totales": totales,
        "por_90": {n: round(v * 90 / minutos, 3) for n, v in totales.items()},
        "rating": round(sum(notas) / len(notas), 2) if notas else None,
    }


def jugador_contra_sistema(
    almacen: Almacen,
    jugador_id: int,
    eje: str = "presion",
    minimo_minutos: int = 20,
) -> dict:
    """Cómo rinde un jugador según el sistema del rival.

    ``eje`` es por qué se agrupa: ``presion`` (alto / medio / bloque bajo),
    ``linea`` (de 4 o de 5 defensas) o ``balon`` (quién domina la pelota).

    Cada grupo se compara con **su propia media**, no con la de otros
    jugadores, y la diferencia se contrasta contra el azar. Un grupo con dos
    partidos sale marcado como «sin muestra» aunque el número sea llamativo:
    eso es lo que lo hace fiable.
    """
    actuaciones = almacen.consulta(
        """SELECT a.*, p.id AS partido, p.liga_id, p.local_id, p.visitante_id,
                  p.local, p.visitante, p.fecha
           FROM actuaciones a JOIN partidos p ON p.id = a.partido_id
           WHERE a.jugador_id = ? AND p.estado = 'finished'
           ORDER BY p.momento DESC""",
        (jugador_id,),
    )
    actuaciones = [a for a in actuaciones if (a["minutos"] or 0) >= minimo_minutos]
    if not actuaciones:
        return {"disponible": False,
                "nota": "No hay actuaciones guardadas de ese jugador. Haz un barrido."}

    umbrales_por_liga: dict[int, dict] = {}
    grupos: dict[str, list[dict]] = {}
    sin_clasificar = 0
    equipo_del_jugador = actuaciones[0]["equipo_id"]

    for fila in actuaciones:
        rival_id = (fila["visitante_id"] if fila["local_id"] == equipo_del_jugador
                    else fila["local_id"])
        sistema = sistema_del_rival(almacen, fila["partido"], rival_id)
        if not sistema:
            sin_clasificar += 1
            continue
        liga = sistema.get("liga_id")
        if liga not in umbrales_por_liga:
            umbrales_por_liga[liga] = umbrales_de_liga(almacen, liga)
        etiqueta = clasificar(sistema, umbrales_por_liga[liga]).get(eje)
        if not etiqueta:
            sin_clasificar += 1
            continue
        entrada = _actuacion(fila)
        entrada.update({"rival": sistema["rival"], "fecha": sistema["fecha"],
                        "formacion_rival": sistema["formacion"]})
        grupos.setdefault(etiqueta, []).append(entrada)

    todas = [_actuacion(f) for f in actuaciones]
    base = _agregar(todas)
    if not base["minutos"]:
        return {"disponible": False, "nota": "Ese jugador no acumula minutos suficientes."}

    salida_grupos = {}
    for etiqueta, lista in sorted(grupos.items()):
        bloque = _agregar(lista)
        bloque["contra"] = [
            {"rival": a["rival"], "fecha": a["fecha"], "formacion": a["formacion_rival"],
             "minutos": a["minutos"]} for a in lista
        ]
        bloque["comparado_con_su_media"] = _comparar(bloque, base)
        salida_grupos[etiqueta] = bloque

    return {
        "disponible": True,
        "jugador_id": jugador_id,
        "jugador": actuaciones[0]["jugador"],
        "eje": eje,
        "su_media": base,
        "grupos": salida_grupos,
        "partidos_sin_clasificar": sin_clasificar,
        "como_leerlo": (
            "Cada grupo se compara con la media del propio jugador. 'señal' "
            "quiere decir que la diferencia es difícil de explicar por azar "
            f"(p<{P_SENAL}); 'indicio', que es sugerente (p<{P_INDICIO}); "
            f"'sin muestra', que hay menos de {MINIMO_PARTIDOS} partidos o "
            f"{MINIMO_MINUTOS} minutos y no se puede decir nada."
        ),
        "lo_que_no_dice": (
            "Un jugador se enfrenta a según qué sistemas en según qué "
            "circunstancias: a bloques bajos, sobre todo cuando su equipo es "
            "favorito. Parte de lo que se vea aquí es el contexto del partido y "
            "no él."
        ),
    }


def _comparar(grupo: dict, base: dict) -> dict:
    """Enfrenta un grupo con la media del jugador, contrastando con Poisson."""
    salida = {}
    minutos = grupo["minutos"]
    for nombre in METRICAS_CONTEO:
        tasa_base = base["por_90"].get(nombre, 0)
        observado = int(round(grupo["totales"].get(nombre, 0)))
        esperado = tasa_base * minutos / 90
        p = probabilidad_de_azar(observado, esperado)
        salida[nombre] = {
            "por_90": grupo["por_90"].get(nombre, 0),
            "su_media_por_90": round(tasa_base, 3),
            "diferencia": round(grupo["por_90"].get(nombre, 0) - tasa_base, 3),
            "esperado": round(esperado, 2),
            "observado": observado,
            "p": round(p, 4),
            "veredicto": _veredicto(p, grupo["partidos"], minutos),
        }
    for nombre in METRICAS_CONTINUAS:
        if nombre == "rating":
            continue
        tasa_base = base["por_90"].get(nombre, 0)
        salida[nombre] = {
            "por_90": grupo["por_90"].get(nombre, 0),
            "su_media_por_90": round(tasa_base, 3),
            "diferencia": round(grupo["por_90"].get(nombre, 0) - tasa_base, 3),
            "veredicto": "solo descriptivo",
        }
    return salida


def lo_relevante(analisis: dict, incluir_indicios: bool = True) -> list[dict]:
    """Solo lo que ha pasado el filtro: nada de listas de cien números."""
    if not analisis.get("disponible"):
        return []
    aceptados = {"señal"} | ({"indicio"} if incluir_indicios else set())
    salida = []
    for etiqueta, grupo in analisis["grupos"].items():
        for metrica, datos in grupo["comparado_con_su_media"].items():
            if datos.get("veredicto") in aceptados:
                salida.append({
                    "contra": etiqueta,
                    "metrica": metrica,
                    "por_90": datos["por_90"],
                    "su_media": datos["su_media_por_90"],
                    "diferencia": datos["diferencia"],
                    "partidos": grupo["partidos"],
                    "veredicto": datos["veredicto"],
                    "p": datos["p"],
                })
    salida.sort(key=lambda f: f["p"])
    return salida


# ------------------------------------------------------ un jugador contra uno

def sistema_habitual(almacen: Almacen, equipo_id: int, ultimos: int = 8) -> dict:
    """Con qué suele plantear un equipo, mirando sus últimos partidos."""
    partidos = almacen.partidos_de_equipo(equipo_id, ultimos=ultimos)
    if not partidos:
        return {"disponible": False, "nota": "Sin partidos guardados de ese equipo."}

    sistemas, etiquetas = [], {}
    umbrales_cache: dict[int, dict] = {}
    for partido in partidos:
        sistema = sistema_del_rival(almacen, partido["id"], equipo_id)
        if not sistema:
            continue
        sistemas.append(sistema)
        liga = sistema.get("liga_id")
        if liga not in umbrales_cache:
            umbrales_cache[liga] = umbrales_de_liga(almacen, liga)
        for eje, valor in clasificar(sistema, umbrales_cache[liga]).items():
            etiquetas.setdefault(eje, {}).setdefault(valor, 0)
            etiquetas[eje][valor] += 1

    if not sistemas:
        return {"disponible": False,
                "nota": "Hay partidos pero sin estadísticas: barre con más detalle."}

    def promedio(clave: str) -> float | None:
        valores = [s[clave] for s in sistemas if s.get(clave) is not None]
        return round(sum(valores) / len(valores), 2) if valores else None

    formaciones: dict[str, int] = {}
    for sistema in sistemas:
        if sistema.get("formacion"):
            formaciones[sistema["formacion"]] = formaciones.get(sistema["formacion"], 0) + 1

    return {
        "disponible": True,
        "equipo_id": equipo_id,
        "equipo": sistemas[0]["rival"],
        "partidos": len(sistemas),
        "formaciones": dict(sorted(formaciones.items(), key=lambda kv: -kv[1])),
        "posesion": promedio("posesion"),
        "presion": promedio("presion"),
        "xg_concedido": promedio("xg_concedido"),
        "tiros_concedidos": promedio("tiros_concedidos"),
        "asi_juega": {eje: max(cuentas, key=cuentas.get)
                      for eje, cuentas in etiquetas.items()},
    }


def duelo(almacen: Almacen, jugador_id: int, rival_id: int) -> dict:
    """Qué le pasa a este jugador contra el sistema que suele plantear ese rival.

    Es la pregunta de la que sale todo esto: no «cómo va el jugador» ni «cómo
    juega el rival», sino qué ha hecho el uno cuando le han puesto delante lo
    que el otro suele poner.
    """
    rival = sistema_habitual(almacen, rival_id)
    if not rival.get("disponible"):
        return {"disponible": False, "nota": rival.get("nota")}

    salida: dict[str, Any] = {
        "disponible": True,
        "rival": rival,
        "por_eje": {},
    }
    jugador = None
    for eje, etiqueta in (rival.get("asi_juega") or {}).items():
        analisis = jugador_contra_sistema(almacen, jugador_id, eje=eje)
        if not analisis.get("disponible"):
            return {"disponible": False, "nota": analisis.get("nota")}
        jugador = jugador or analisis["jugador"]
        grupo = analisis["grupos"].get(etiqueta)
        salida["por_eje"][eje] = {
            "el_rival_es": etiqueta,
            "encontrado": bool(grupo),
            "resumen": None if not grupo else {
                "partidos": grupo["partidos"],
                "minutos": grupo["minutos"],
                "rating": grupo.get("rating"),
                "relevante": [
                    f for f in lo_relevante({"disponible": True,
                                             "grupos": {etiqueta: grupo}})
                ],
                "todo": grupo["comparado_con_su_media"],
                "contra": grupo["contra"],
            },
            "su_media": analisis["su_media"]["por_90"],
        }
    salida["jugador"] = jugador
    salida["jugador_id"] = jugador_id
    salida["lo_que_no_dice"] = (
        "Esto describe lo que ha pasado, no lo que va a pasar. Y con seis u "
        "ocho partidos por grupo, hasta una 'señal' puede ser una racha."
    )
    return salida


__all__ = [
    "jugador_contra_sistema", "duelo", "sistema_habitual", "sistema_del_rival",
    "clasificar", "umbrales_de_liga", "presion_aproximada", "lo_relevante",
    "probabilidad_de_azar", "poisson_cdf",
    "METRICAS_CONTEO", "METRICAS_CONTINUAS",
    "MINIMO_PARTIDOS", "MINIMO_MINUTOS", "P_SENAL", "P_INDICIO",
]
