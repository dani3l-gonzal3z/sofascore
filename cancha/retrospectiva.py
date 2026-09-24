"""Un partido ya jugado: lo que dijimos antes, lo que pasó, y quién estuvo más cerca.

Todo lo que se dice de un partido antes de jugarse queda escrito en tres sitios
que no se tocan después: el briefing del día (un fichero por día), el registro
de predicciones (la primera que se apunta es la que cuenta) y los picks (con su
cuota de entonces). Esto los junta con el resultado y los pone uno al lado del
otro, sin retocar nada:

* **qué dijo el briefing**, en corto: nuestro 1X2, los goles esperados, los
  marcadores más probables, dónde no estábamos de acuerdo con el mercado y el
  pick, si lo hubo;
* **qué pasó**: el marcador y, con él, cada suceso resuelto;
* **quién estuvo más cerca**, suceso a suceso: la probabilidad que le dio cada uno
  —nosotros, el mercado, cada agente— **a lo que pasó**. No «¿acertó?», que con
  un 1X2 es tirar una moneda con tres caras: un 45 % al que ganó es mejor
  pronóstico que un 30 %, aunque ninguno de los dos «acertase» nada.

Un partido suelto no dice si un modelo es bueno —eso lo dice el backtest con
cientos—, y la lectura lo recuerda cada vez. Sirve para otra cosa: para ver en
qué se equivocó y si lo que se veía venir tenía sentido.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from typing import Any

#: Los sucesos de sí/no: con una sola fila apuntada, la probabilidad de lo que
#: pasó es la suya o la contraria.
BINARIOS = ("mas_2_5", "ambos_marcan", "corners", "tarjetas")

#: Cómo se lee cada suceso del registro.
NOMBRES = {"1x2": "1X2", "mas_2_5": "Más de 2,5 goles", "ambos_marcan": "Ambos marcan",
           "corners": "Más de 9,5 córners", "tarjetas": "Más de 3,5 amarillas",
           "marcador_exacto": "Marcador exacto"}

#: Diferencia de probabilidad (sobre lo que pasó) por debajo de la cual no se
#: dice que nadie estuvo «más cerca»: dos puntos es ruido de redondeo.
EMPATE = 0.02


def retrospectiva(almacen, partido_id: int, carpeta_briefings: str | Path | None = None) -> dict:
    """Todo lo dicho antes de un partido, junto a lo que pasó."""
    from .briefing import CARPETA_POR_DEFECTO

    filas = almacen.consulta("SELECT * FROM partidos WHERE id = ?", (int(partido_id),))
    if not filas:
        return {"disponible": False,
                "nota": "Ese partido no está en la memoria: ábrelo una vez para traerlo."}
    fila = filas[0]
    jugado = _jugado(fila)
    marcador = f"{fila['goles_local']}-{fila['goles_visitante']}" if jugado else None
    salida: dict[str, Any] = {
        "disponible": True,
        "partido": {"id": fila["id"], "local": fila["local"], "visitante": fila["visitante"],
                    "fecha": fila["fecha"], "competicion": fila["liga"]},
        "jugado": jugado, "marcador": marcador,
        "briefing": del_briefing(carpeta_briefings or CARPETA_POR_DEFECTO,
                                 fila["fecha"], fila["id"]),
        "picks": _picks(almacen, fila["id"]),
        "dictamen": _dictamen(almacen, fila["id"], fila.get("momento")),
    }
    predicciones = almacen.consulta(
        """SELECT autor, mercado, seleccion, probabilidad, prob_mercado, prob_cierre,
                  hecha_el, horas_antes
           FROM predicciones WHERE partido_id = ? ORDER BY autor, mercado, seleccion""",
        (fila["id"],))
    salida["apuntado"] = _apuntado(predicciones)
    if jugado:
        salida["sucesos"] = comparar(almacen, fila, predicciones)
        salida["aciertos"] = _aciertos(salida, predicciones, fila)
    salida["lectura"] = _lectura(salida)
    return salida


def _jugado(fila: dict) -> bool:
    return (fila.get("goles_local") is not None and fila.get("goles_visitante") is not None
            and (fila.get("estado") or "").lower() in ("finished", "ended", "ft"))


# ------------------------------------------------------------ el briefing

def del_briefing(carpeta: str | Path, fecha: str | None, partido_id: int) -> dict | None:
    """Lo que dijo de este partido el briefing de su día, en corto.

    Se mira también el día de antes y el de después: la fecha de un partido es la
    de UTC y el briefing es del día en que se hizo, y un partido a medianoche cae
    en uno o en otro según dónde vivas.
    """
    from .briefing import cargar

    if not fecha:
        return None
    with suppress(ValueError):
        dia = date.fromisoformat(str(fecha)[:10])
        for delta in (0, -1, 1):
            datos = cargar((dia + timedelta(days=delta)).isoformat(), carpeta)
            for p in (datos or {}).get("partidos") or []:
                if (p.get("partido") or {}).get("id") == partido_id:
                    return _en_corto(p, datos)
    return None


def _en_corto(p: dict, briefing: dict) -> dict:
    pron = p.get("pronostico") or {}
    mercado = p.get("mercado") or {}
    rasgos = {}
    for lado in ("local", "visitante"):
        estilo = (p.get("equipos") or {}).get(lado) or {}
        rasgos[lado] = [r["rasgo"] for r in estilo.get("lo_que_le_distingue") or []][:3]
    return {
        "del_dia": briefing.get("fecha"),
        "generado": briefing.get("generado"),
        "pronostico": {k: pron.get(k) for k in ("disponible", "1x2", "esperados",
                                                 "marcadores", "mas_2_5", "ambos_marcan",
                                                 "muestra", "nota") if k in pron},
        "mercado": mercado.get("probabilidades") if mercado.get("disponible") else None,
        "discrepancias": [s for s in (p.get("frente_al_mercado") or {}).get("sucesos") or []
                          if s.get("discrepa")],
        "pick": (p.get("candidatos") or [None])[0],
        "rasgos": rasgos,
    }


# ------------------------------------------------------------ lo apuntado

def _apuntado(predicciones: list[dict]) -> dict:
    """Quién apuntó qué, y cuántas horas antes del saque."""
    autores: dict[str, dict] = {}
    for f in predicciones:
        suyo = autores.setdefault(f["autor"], {"sucesos": 0, "horas_antes": f["horas_antes"],
                                               "hecha_el": f["hecha_el"]})
        suyo["sucesos"] += 1
    return autores


def _picks(almacen, partido_id: int) -> list[dict]:
    with suppress(Exception):
        return almacen.consulta(
            """SELECT nivel, suceso, mercado, seleccion, cuota, casa, prob_nuestra,
                      prob_mercado, valor, regla, resuelto, acerto, beneficio, cuota_cierre
               FROM picks WHERE partido_id = ? ORDER BY nivel""", (partido_id,))
    return []


def _dictamen(almacen, partido_id: int, momento: int | None) -> dict | None:
    """El primer dictamen del analista, si lo hubo **antes** del saque.

    Uno hecho después ya sabía el resultado, y ponerlo al lado del marcador como
    si fuera una predicción sería hacerse trampas.
    """
    from datetime import datetime, timezone

    # Sumando desde la época y no con `fromtimestamp`, que en Windows revienta con
    # fechas anteriores a 1970 (ver `Event.kickoff`).
    saque = None
    with suppress(OverflowError, TypeError, ValueError):
        saque = ((datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=int(momento)))
                 .strftime("%Y-%m-%d %H:%M:%S") if momento else None)
    with suppress(Exception):
        filas = [f for f in almacen.dictamenes_de(partido_id, limite=50)
                 if not saque or str(f.get("hecho_el") or "") < saque]
        if filas:
            primero = filas[-1]
            respuesta = (primero.get("respuesta") or "").strip()
            return {"hecho_el": primero.get("hecho_el"), "modelo": primero.get("modelo"),
                    "resumen": _primeras(respuesta, 600), "cuantos": len(filas)}
    return None


def _primeras(texto: str, tope: int) -> str:
    if len(texto) <= tope:
        return texto
    corte = texto.rfind(". ", 0, tope)
    return texto[:corte + 1 if corte > tope // 2 else tope].rstrip() + " …"


# ------------------------------------------------------------ la comparación

def comparar(almacen, partido: dict, predicciones: list[dict]) -> list[dict]:
    """Suceso a suceso, cuánta probabilidad le dio cada autor a lo que pasó."""
    from .registro import _resultado_de

    grupos: dict[tuple[str, str], list[dict]] = {}
    for f in predicciones:
        if f["mercado"] in NOMBRES:
            grupos.setdefault((f["mercado"], f["autor"]), []).append(f)

    por_suceso: dict[str, dict] = {}
    for (mercado, autor), suyas in grupos.items():
        prob, paso = None, None
        for f in suyas:
            real = _resultado_de(almacen, {**f, "partido_id": partido["id"],
                                           "goles_local": partido["goles_local"],
                                           "goles_visitante": partido["goles_visitante"],
                                           "estado": partido["estado"]})
            if real is None:
                continue
            acerto, valor = real
            paso = valor
            if acerto:
                prob = f["probabilidad"]
            elif mercado in BINARIOS and len(suyas) == 1:
                prob = 1 - f["probabilidad"]
        if paso is None:
            continue
        suceso = por_suceso.setdefault(mercado, {"suceso": NOMBRES[mercado], "mercado": mercado,
                                                 "paso": _que_paso(mercado, paso, partido),
                                                 "autores": {}})
        suceso["autores"][autor] = None if prob is None else round(prob, 4)

    salida = []
    for mercado in NOMBRES:
        if mercado not in por_suceso:
            continue
        s = por_suceso[mercado]
        s["mas_cerca"] = _mas_cerca(s["autores"])
        salida.append(s)
    return salida


def _que_paso(mercado: str, valor: str, partido: dict) -> str:
    local, visitante = partido["goles_local"], partido["goles_visitante"]
    if mercado == "1x2":
        return ("gana " + partido["local"] if local > visitante
                else "gana " + partido["visitante"] if visitante > local else "empate")
    if mercado == "mas_2_5":
        return f"{'sí' if local + visitante > 2 else 'no'} ({local + visitante} goles)"
    if mercado == "ambos_marcan":
        return "sí" if local and visitante else "no"
    if mercado in ("corners", "tarjetas"):
        linea = 9.5 if mercado == "corners" else 3.5
        with suppress(ValueError):
            return f"{'sí' if float(valor) > linea else 'no'} ({valor})"
    return valor


def _mas_cerca(autores: dict[str, float | None]) -> str | None:
    """Nosotros o el mercado: quién le dio más a lo que pasó. Los agentes se ven, pero
    la pregunta que importa es esa."""
    from .registro import AUTOR_CALCULO, AUTOR_MERCADO

    nuestra, suya = autores.get(AUTOR_CALCULO), autores.get(AUTOR_MERCADO)
    if nuestra is None and suya is None:
        return None
    if suya is None:
        return "sin mercado"
    if nuestra is None:
        return "el mercado"
    if abs(nuestra - suya) < EMPATE:
        return "igual"
    return "nosotros" if nuestra > suya else "el mercado"


def _aciertos(salida: dict, predicciones: list[dict], partido: dict) -> dict:
    """Las cuatro cosas que uno mira primero: favorito, marcador, goles y pick."""
    from .registro import AUTOR_CALCULO, AUTOR_MERCADO

    marcador = salida["marcador"]
    nuestras = [f for f in predicciones if f["autor"] == AUTOR_CALCULO]
    uno = {f["seleccion"]: f["probabilidad"] for f in nuestras if f["mercado"] == "1x2"}
    mercado_uno = {f["seleccion"]: f["probabilidad"] for f in predicciones
                   if f["autor"] == AUTOR_MERCADO and f["mercado"] == "1x2"}
    local, visitante = partido["goles_local"], partido["goles_visitante"]
    gano = "local" if local > visitante else "visitante" if visitante > local else "empate"
    top = next((f["seleccion"] for f in nuestras if f["mercado"] == "marcador"), None)
    exacto = {f["seleccion"]: f["probabilidad"] for f in nuestras
              if f["mercado"] == "marcador_exacto"}
    orden = sorted(exacto, key=lambda m: -exacto[m])
    return {
        "favorito_nuestro": max(uno, key=uno.get) if uno else None,
        "favorito_mercado": max(mercado_uno, key=mercado_uno.get) if mercado_uno else None,
        "gano": gano,
        "marcador_mas_probable": top,
        "acerto_marcador": top == marcador if top else None,
        # En qué puesto de nuestra lista estaba el marcador que salió: un 1-1 que
        # era nuestro segundo más probable no es lo mismo que uno que era el vigésimo.
        "puesto_del_marcador": orden.index(marcador) + 1 if marcador in orden else None,
        "prob_del_marcador": exacto.get(marcador),
        "picks": [{"suceso": p["suceso"], "cuota": p["cuota"], "acerto": p["acerto"],
                   "beneficio": p["beneficio"]} for p in salida["picks"] if p["resuelto"]],
    }


def _lectura(s: dict) -> str:
    if not s["jugado"]:
        if not s["apuntado"] and not s["briefing"]:
            return ("No se jugó todavía y no hay nada apuntado de él. Lo que se dice antes "
                    "se apunta al hacer el briefing o la guardia de su día.")
        return "Aún no se ha jugado: aquí se verá, cuando acabe, lo dicho frente a lo que pase."
    if not s["apuntado"]:
        return ("No se apuntó nada antes del partido, así que no hay con qué comparar. "
                "Para que se apunte, tiene que pasar por el briefing o la guardia de su día.")
    cerca = [x["mas_cerca"] for x in s.get("sucesos") or []
             if x["mas_cerca"] in ("nosotros", "el mercado")]
    nuestros, suyos = cerca.count("nosotros"), cerca.count("el mercado")
    partes = [f"Acabó {s['marcador']}."]
    if cerca:
        partes.append(f"En {nuestros} de {len(cerca)} sucesos le dimos más probabilidad que "
                      f"el mercado a lo que pasó; en {suyos}, él a nosotros.")
    ac = s.get("aciertos") or {}
    if ac.get("puesto_del_marcador"):
        partes.append(f"El {s['marcador']} era nuestro marcador número "
                      f"{ac['puesto_del_marcador']} ({ac['prob_del_marcador']:.0%}).")
    partes.append("Un partido suelto no dice si el modelo es bueno: eso lo dice el backtest.")
    return " ".join(partes)


def texto(r: dict) -> list[str]:
    """La retrospectiva en líneas, para la terminal y para el modelo."""
    from .registro import nombre_de_autor

    if not r.get("disponible"):
        return [r.get("nota") or "Sin datos."]
    p = r["partido"]
    lineas = [f"{p['local']} {r['marcador'] or 'vs'} {p['visitante']} · {p['competicion']} · "
              f"{p['fecha']}", ""]
    b = r.get("briefing")
    if b:
        lineas.append(f"LO QUE DIJO EL BRIEFING (del {b['del_dia']})")
        pron = b.get("pronostico") or {}
        if pron.get("disponible"):
            uno = pron["1x2"]
            lineas.append(f"  Nuestro 1X2: {uno['local']:.0%} · {uno['empate']:.0%} · "
                          f"{uno['visitante']:.0%}"
                          + (" · marcadores " + ", ".join(
                              f"{m['marcador']} ({m['probabilidad']:.0%})"
                              for m in (pron.get("marcadores") or [])[:3])
                             if pron.get("marcadores") else ""))
        elif pron:
            lineas.append(f"  Sin pronóstico: {pron.get('nota')}")
        if b.get("mercado"):
            m = b["mercado"]
            lineas.append(f"  Mercado: {m.get('local', 0):.0%} · {m.get('empate', 0):.0%} · "
                          f"{m.get('visitante', 0):.0%}")
        for d in b.get("discrepancias") or []:
            if d.get("nuestra") is not None and d.get("mercado") is not None:
                lineas.append(f"  Discrepábamos en {d['suceso']}: nosotros {d['nuestra']:.0%}, "
                              f"mercado {d['mercado']:.0%}")
        if b.get("pick"):
            lineas.append(f"  Pick: {b['pick'].get('suceso')} a {b['pick'].get('cuota')}")
        lineas.append("")
    elif r["jugado"]:
        lineas += ["No hay briefing guardado de ese día.", ""]
    if r.get("sucesos"):
        lineas.append("A LO QUE PASÓ, CUÁNTO LE DIO CADA UNO")
        for s in r["sucesos"]:
            quienes = " · ".join(f"{nombre_de_autor(a)} {'—' if v is None else f'{v:.0%}'}"
                                 for a, v in s["autores"].items())
            lineas.append(f"  {s['suceso']:<20} pasó: {s['paso']:<22} {quienes}"
                          + (f"  → {s['mas_cerca']}" if s.get("mas_cerca") else ""))
        lineas.append("")
    for pk in r.get("picks") or []:
        estado = ("pendiente" if not pk["resuelto"] else
                  f"{'acertado' if pk['acerto'] else 'fallado'} ({pk['beneficio']:+.2f} u)")
        lineas.append(f"Pick {pk['nivel']}: {pk['suceso']} a {pk['cuota']} → {estado}")
    if r.get("dictamen"):
        lineas += ["", f"EL ANALISTA, ANTES DEL SAQUE ({r['dictamen']['modelo'] or '?'})",
                   r["dictamen"]["resumen"]]
    if lineas[-1]:
        lineas.append("")
    lineas.append(r["lectura"])
    return lineas


__all__ = ["comparar", "del_briefing", "retrospectiva", "texto"]
