"""Cómo juega un equipo, cómo está un jugador, cómo pita un árbitro.

Un dato suelto no dice nada. «42% de posesión» no significa lo mismo en una
liga que promedia el 50% que en una que promedia el 46%, y «tres partidos sin
marcar» no es igual para un delantero que tira ocho veces por partido que para
uno que no tira.

Por eso todo lo de aquí sale de la **memoria** (:mod:`cancha.almacen`) y todo
va **comparado con su liga**. Es lo que no se podía hacer pidiendo un partido
cada vez.

Las claves de estadística son las que devuelve la API de verdad, cogidas de una
ejecución real y no de lo que uno se imagina que habrá.
"""

from __future__ import annotations

from typing import Any

from .almacen import Almacen

#: Las dimensiones con las que se describe a un equipo, y de qué salen.
#: Cada una es (clave de la API, cómo se lee cuando está alta).
DIMENSIONES: dict[str, tuple[str, str]] = {
    "posesion": ("ballPossession", "tiene el balón"),
    "tiros": ("totalShotsOnGoal", "tira mucho"),
    "xg": ("expectedGoals", "genera peligro"),
    "ocasiones_claras": ("bigChanceCreated", "llega a ocasiones claras"),
    "pases": ("passes", "toca mucho el balón"),
    "pases_largos": ("accurateLongBalls", "juega en largo"),
    "centros": ("accurateCross", "ataca por fuera"),
    "corners": ("cornerKicks", "vive del córner"),
    "entradas_ultimo_tercio": ("finalThirdEntries", "llega arriba con frecuencia"),
    "toques_en_area": ("touchesInOppBox", "se mete en el área"),
    "recuperaciones": ("ballRecovery", "recupera mucho"),
    "entradas": ("totalTackle", "entra fuerte"),
    "intercepciones": ("interceptionWon", "corta líneas de pase"),
    "despejes": ("totalClearance", "despeja mucho"),
    "faltas": ("fouls", "hace faltas"),
    "amarillas": ("yellowCards", "ve tarjetas"),
    "kilometros": ("kilometersCovered", "corre"),
    "sprints": ("numberOfSprints", "aprieta"),
    "paradas": ("goalkeeperSaves", "su portero trabaja"),
}

#: A partir de qué distancia sobre la media de la liga una diferencia es
#: digna de mención. En proporción, no en valor absoluto.
UMBRAL_RASGO = 0.18


def _medias(filas: list[dict], equipo_id: int | None = None,
            excluir: int | None = None) -> dict[str, float]:
    """Media por clave de estadística, desde la perspectiva de un equipo.

    Cada fila de la base trae el valor del local y el del visitante; según de
    quién se pregunte, se coge uno u otro. Con ``equipo_id=None`` se promedian
    los dos lados, que es como se saca la media de una liga.

    ``excluir`` deja fuera los valores de un equipo al calcular esa media de
    liga: comparar a alguien contra una media que le incluye a él suaviza
    justo lo que se quiere ver. En una liga de veinte equipos el efecto es
    pequeño, pero es el cálculo correcto.
    """
    sumas: dict[str, list[float]] = {}
    for fila in filas:
        clave = fila["clave"]
        if equipo_id is None:
            for lado, dueño in (("local", "local_id"), ("visitante", "visitante_id")):
                if excluir is not None and fila.get(dueño) == excluir:
                    continue
                if fila.get(lado) is not None:
                    sumas.setdefault(clave, []).append(fila[lado])
            continue
        es_local = fila.get("local_id") == equipo_id
        valor = fila.get("local") if es_local else fila.get("visitante")
        if valor is not None:
            sumas.setdefault(clave, []).append(valor)
    return {c: sum(v) / len(v) for c, v in sumas.items() if v}


def _concedidas(filas: list[dict], equipo_id: int) -> dict[str, float]:
    """Lo mismo, pero lo que le hacen: la mitad defensiva del retrato."""
    sumas: dict[str, list[float]] = {}
    for fila in filas:
        es_local = fila.get("local_id") == equipo_id
        valor = fila.get("visitante") if es_local else fila.get("local")
        if valor is not None:
            sumas.setdefault(fila["clave"], []).append(valor)
    return {c: sum(v) / len(v) for c, v in sumas.items() if v}


def medias_de_liga(almacen: Almacen, liga_id: int, temporada_id: int | None = None,
                   excluir_equipo: int | None = None) -> dict:
    """La media de cada estadística en una competición.

    Es la vara de medir: sin ella, los números de un equipo son solo números.
    Con ``excluir_equipo`` se mide contra **el resto**, que es lo que hay que
    hacer para no comparar a alguien contra una media en la que él pesa.
    """
    sql = "SELECT id FROM partidos WHERE liga_id = ? AND estado = 'finished'"
    parametros: tuple = (liga_id,)
    if temporada_id:
        sql += " AND temporada_id = ?"
        parametros += (temporada_id,)
    ids = [f["id"] for f in almacen.consulta(sql, parametros)]
    if not ids:
        return {"partidos": 0, "medias": {}}
    filas = almacen.estadisticas_de_partidos(ids)
    return {"partidos": len(ids), "medias": _medias(filas, excluir=excluir_equipo)}


def estilo_de_equipo(
    almacen: Almacen,
    equipo_id: int,
    ultimos: int = 6,
    comparar_con_liga: bool = True,
) -> dict:
    """Cómo juega un equipo, según sus últimos partidos guardados.

    Devuelve los números, su distancia con la media de la liga y una lectura en
    palabras: los rasgos en los que se sale de lo normal, que es lo único que
    de verdad describe a un equipo.
    """
    partidos = almacen.partidos_de_equipo(equipo_id, ultimos=ultimos)
    if not partidos:
        return {"disponible": False,
                "nota": "No hay partidos guardados de ese equipo. Haz un barrido antes."}

    ids = [p["id"] for p in partidos]
    filas = almacen.estadisticas_de_partidos(ids)
    propias = _medias(filas, equipo_id)
    rivales = _concedidas(filas, equipo_id)

    liga_id = partidos[0].get("liga_id")
    referencia = (
        medias_de_liga(almacen, liga_id, excluir_equipo=equipo_id)
        if (comparar_con_liga and liga_id) else {}
    )
    medias_liga = referencia.get("medias", {})

    dimensiones = {}
    rasgos = []
    for nombre, (clave, lectura) in DIMENSIONES.items():
        valor = propias.get(clave)
        if valor is None:
            continue
        media = medias_liga.get(clave)
        bloque: dict[str, Any] = {"clave": clave, "valor": round(valor, 2)}
        if media:
            diferencia = (valor - media) / media
            bloque["media_liga"] = round(media, 2)
            bloque["diferencia"] = round(diferencia, 3)
            if abs(diferencia) >= UMBRAL_RASGO:
                rasgos.append({
                    "rasgo": lectura if diferencia > 0 else f"no {lectura}",
                    "dimension": nombre,
                    "cuanto": f"{diferencia:+.0%} sobre la media de su liga",
                })
        dimensiones[nombre] = bloque

    rasgos.sort(key=lambda r: -abs(float(r["cuanto"].split("%")[0].replace("+", ""))))
    resultados = _resultados(partidos, equipo_id)

    return {
        "disponible": True,
        "equipo_id": equipo_id,
        "equipo": _nombre_equipo(partidos[0], equipo_id),
        "partidos_mirados": len(partidos),
        "desde": partidos[-1]["fecha"],
        "hasta": partidos[0]["fecha"],
        "liga": partidos[0].get("liga"),
        "partidos_en_la_media_de_liga": referencia.get("partidos", 0),
        "resultados": resultados,
        "dimensiones": dimensiones,
        "lo_que_le_distingue": rasgos[:6],
        "concede": {
            "xg": round(rivales.get("expectedGoals", 0), 2),
            "tiros": round(rivales.get("totalShotsOnGoal", 0), 1),
            "ocasiones_claras": round(rivales.get("bigChanceCreated", 0), 1),
        },
        "aviso": None if medias_liga else
                 "Sin media de liga con la que comparar: los números están solos. "
                 "Barre más partidos de esa competición.",
    }


def _nombre_equipo(partido: dict, equipo_id: int) -> str:
    return partido["local"] if partido["local_id"] == equipo_id else partido["visitante"]


def _resultados(partidos: list[dict], equipo_id: int) -> dict:
    """Ganados, empatados y perdidos, con los goles a favor y en contra."""
    ganados = empatados = perdidos = favor = contra = 0
    racha = []
    for partido in partidos:
        es_local = partido["local_id"] == equipo_id
        mios = partido["goles_local"] if es_local else partido["goles_visitante"]
        suyos = partido["goles_visitante"] if es_local else partido["goles_local"]
        if mios is None or suyos is None:
            continue
        favor += mios
        contra += suyos
        if mios > suyos:
            ganados += 1
            racha.append("G")
        elif mios == suyos:
            empatados += 1
            racha.append("E")
        else:
            perdidos += 1
            racha.append("P")
    return {
        "ganados": ganados, "empatados": empatados, "perdidos": perdidos,
        "goles_favor": favor, "goles_contra": contra,
        # Del más reciente al más antiguo, como se lee una racha.
        "racha": "".join(racha),
    }


# ------------------------------------------------------------------- jugadores

#: Qué se mira de un jugador y cómo se llama en los datos que guarda la API
#: dentro de las alineaciones.
METRICAS_JUGADOR = {
    "minutos": "minutesPlayed",
    "goles": "goals",
    "asistencias": "goalAssist",
    "tiros": "totalShots",
    "tiros_a_puerta": "onTargetScoringAttempt",
    "xg": "expectedGoals",
    "xa": "expectedAssists",
    "pases_clave": "keyPass",
    "regates": "wonContest",
    "duelos_ganados": "duelWon",
    "perdidas": "possessionLostCtrl",
    "toques": "touches",
}


def forma_de_jugador(almacen: Almacen, jugador_id: int, ultimas: int = 6) -> dict:
    """Cómo está un jugador, y qué rachas lleva.

    Lo interesante no es la media, es lo que se sale de ella: cuántos partidos
    lleva sin marcar, sin tirar entre palos o sin jugar. Eso es lo que un
    análisis quiere saber y lo que no se ve mirando un partido suelto.
    """
    import json

    actuaciones = almacen.actuaciones_de_jugador(jugador_id, ultimas=ultimas)
    if not actuaciones:
        return {"disponible": False,
                "nota": "No hay partidos guardados de ese jugador."}

    partidos = []
    for fila in actuaciones:
        datos = {}
        with_datos = fila.get("datos")
        if with_datos:
            try:
                datos = json.loads(with_datos)
            except (ValueError, TypeError):
                datos = {}
        partidos.append({
            "fecha": fila["fecha"],
            "partido": f"{fila['local']} - {fila['visitante']}",
            "titular": bool(fila["titular"]),
            "minutos": fila["minutos"] or 0,
            "rating": fila["rating"],
            **{nombre: datos.get(clave, 0) for nombre, clave in METRICAS_JUGADOR.items()
               if nombre != "minutos"},
        })

    jugados = [p for p in partidos if p["minutos"]]
    medias = {}
    for nombre in METRICAS_JUGADOR:
        if nombre == "minutos":
            continue
        valores = [p.get(nombre) or 0 for p in jugados]
        if valores:
            medias[nombre] = round(sum(valores) / len(valores), 2)

    notas = [p["rating"] for p in jugados if p["rating"]]
    return {
        "disponible": True,
        "jugador_id": jugador_id,
        "jugador": actuaciones[0]["jugador"],
        "partidos_mirados": len(partidos),
        "titularidades": sum(1 for p in partidos if p["titular"]),
        "minutos_totales": sum(p["minutos"] for p in partidos),
        "rating_medio": round(sum(notas) / len(notas), 2) if notas else None,
        "por_partido": medias,
        "rachas": rachas(partidos),
        "partido_a_partido": partidos,
    }


def rachas(partidos: list[dict]) -> list[dict]:
    """Cuántos partidos seguidos lleva sin que le pase algo.

    Se cuenta desde el más reciente hacia atrás y solo entre los que jugó: no
    tiene sentido decir que lleva cinco partidos sin marcar si en tres de ellos
    no salió del banquillo.
    """
    jugados = [p for p in partidos if p["minutos"]]
    if not jugados:
        return []

    def sin(metrica: str, etiqueta: str, minimo: int = 2) -> dict | None:
        cuenta = 0
        for partido in jugados:
            if (partido.get(metrica) or 0) > 0:
                break
            cuenta += 1
        if cuenta >= minimo:
            return {
                "racha": f"{cuenta} partidos {etiqueta}",
                "metrica": metrica,
                "partidos": cuenta,
                "desde": jugados[cuenta - 1]["fecha"],
            }
        return None

    salida = []
    for metrica, etiqueta in (
        ("goles", "sin marcar"),
        ("tiros_a_puerta", "sin tirar entre palos"),
        ("tiros", "sin rematar"),
        ("asistencias", "sin asistir"),
        ("pases_clave", "sin dar un pase clave"),
    ):
        encontrada = sin(metrica, etiqueta)
        if encontrada:
            salida.append(encontrada)

    # Y lo contrario: en cuántos seguidos sí ha marcado o asistido.
    for metrica, etiqueta in (("goles", "marcando"), ("asistencias", "asistiendo")):
        cuenta = 0
        for partido in jugados:
            if (partido.get(metrica) or 0) > 0:
                cuenta += 1
            else:
                break
        if cuenta >= 2:
            salida.append({"racha": f"{cuenta} partidos {etiqueta}", "metrica": metrica,
                           "partidos": cuenta, "desde": jugados[cuenta - 1]["fecha"]})

    # Suplencias seguidas: dice tanto como lo que hace en el campo.
    banquillo = 0
    for partido in partidos:
        if partido["titular"]:
            break
        banquillo += 1
    if banquillo >= 2:
        salida.append({"racha": f"{banquillo} partidos sin ser titular",
                       "metrica": "titular", "partidos": banquillo,
                       "desde": partidos[banquillo - 1]["fecha"]})
    return salida


# --------------------------------------------------------------------- árbitros

def perfil_de_arbitro(almacen: Almacen, nombre: str, ultimos: int = 20) -> dict:
    """Cómo pita alguien, según los partidos suyos que haya guardados.

    Sale de contar sus partidos en la base, no de un endpoint: Sofascore no
    publica uno, y ninguna de las librerías que hablan con su API lo usa.
    Cuantos más partidos barridos, más fiable.
    """
    partidos = almacen.partidos_de_arbitro(nombre, ultimos=ultimos)
    if not partidos:
        return {"disponible": False,
                "nota": f"No hay partidos guardados de '{nombre}'. Barre más y vuelve."}

    ids = [p["id"] for p in partidos]
    filas = almacen.estadisticas_de_partidos(
        ids, claves=["yellowCards", "redCards", "fouls"])
    medias = _medias(filas)

    incidencias = almacen.consulta(
        f"""SELECT tipo, clase, local, COUNT(*) AS n FROM incidencias
            WHERE partido_id IN ({','.join('?' * len(ids))})
            GROUP BY tipo, clase, local""", tuple(ids))
    penaltis = sum(f["n"] for f in incidencias
                   if (f["clase"] or "").lower().startswith("penalty"))
    amarillas_local = sum(f["n"] for f in incidencias
                          if f["tipo"] == "card" and f["local"] == 1)
    amarillas_visitante = sum(f["n"] for f in incidencias
                              if f["tipo"] == "card" and f["local"] == 0)

    victorias_local = sum(1 for p in partidos
                          if (p["goles_local"] or 0) > (p["goles_visitante"] or 0))
    return {
        "disponible": True,
        "arbitro": nombre,
        "partidos_mirados": len(partidos),
        "por_partido": {
            "amarillas": round(medias.get("yellowCards", 0), 2),
            "rojas": round(medias.get("redCards", 0), 2),
            "faltas": round(medias.get("fouls", 0), 1),
            "penaltis": round(penaltis / len(partidos), 2),
        },
        "reparto_de_tarjetas": {
            "al_local": amarillas_local,
            "al_visitante": amarillas_visitante,
        },
        "victorias_locales": f"{victorias_local}/{len(partidos)}",
        "aviso": ("Con menos de diez partidos esto es una anécdota, no un patrón."
                  if len(partidos) < 10 else None),
    }


__all__ = [
    "estilo_de_equipo", "forma_de_jugador", "rachas", "perfil_de_arbitro",
    "medias_de_liga", "DIMENSIONES", "METRICAS_JUGADOR",
]
