"""El backtest: rehacer cada pronóstico del pasado con lo que se sabía entonces.

Hasta aquí la única forma de saber si el modelo o la regla de picks valen algo
era esperar: apuntar cada día y mirar dentro de seis meses. Con la historia
traída (`cancha historia`), la memoria ya tiene miles de partidos jugados con sus
cuotas de cierre. Esto rehace el pronóstico de cada uno **usando solo lo jugado
antes de él**, y contesta tres preguntas:

1. **¿El modelo sabe algo que el mercado no sabe?** No «¿acierta mucho?», que
   depende de qué partidos mires, sino: si a la probabilidad del mercado le
   mezclas un poco de la nuestra, ¿mejora? Si el mejor peso para lo nuestro es
   cero, el modelo no aporta nada que las casas no tengan ya, y hay que decirlo.
2. **¿La regla de picks habría ganado?** Simulada partido a partido, a la cuota
   de cierre.
3. **¿Quién acierta más en marcador exacto?** Cuando la fuente tenía ese mercado.

Lo que lo hace honesto y no un anuncio:

* **Sin mirar el futuro.** Las fuerzas de cada equipo y las medias de la liga se
  cortan en la fecha del partido. Antes la media de la liga no se cortaba y el
  pronóstico «sabía» cómo había ido el resto de la temporada.
* **El peso de la mezcla se elige con la primera mitad y se mide en la
  segunda.** Elegirlo y medirlo sobre los mismos partidos garantiza que salga
  algo mejor que cero aunque el modelo no sirva para nada.
* **A la cuota de cierre**, que es la más difícil de batir: ya lleva dentro las
  alineaciones y el dinero. En la vida real se apuesta antes, a una cuota que
  puede ser mejor o peor. Aquí no se presume de lo que no se sabe.

Y lo que no puede quitar: el backtest solo ve partidos **con cuotas guardadas**,
y si alguien retoca la regla hasta que el backtest salga bonito, el backtest deja
de valer. Por eso la regla lleva versión, y por eso se dice.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timezone

#: Por debajo de esto, el backtest se hace pero no se concluye nada.
MINIMO_PARTIDOS = 300

#: Los pesos que se prueban para lo nuestro al mezclarlo con el mercado. 0 es el
#: mercado solo; 1, nuestro modelo solo.
PESOS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0)

#: Los sucesos binarios que se comparan con el mercado, como en el registro.
BINARIOS = (("mas_2_5", "si", "Más de 2,5 goles"),
            ("ambos_marcan", "si", "Marcan los dos"),
            ("corners", "mas_9_5", "Más de 9,5 córners"),
            ("tarjetas", "mas_3_5", "Más de 3,5 tarjetas"))

LADOS = ("local", "empate", "visitante")


def _nuestras(pron: dict) -> dict[tuple, float]:
    """Las probabilidades de nuestro pronóstico, con las claves del registro."""
    g = pron.get("goles") or {}
    salida = {("1x2", lado): p for lado, p in (g.get("1x2") or {}).items()}
    if (g.get("mas_de") or {}).get("2.5") is not None:
        salida[("mas_2_5", "si")] = g["mas_de"]["2.5"]
    if g.get("ambos_marcan") is not None:
        salida[("ambos_marcan", "si")] = g["ambos_marcan"]
    for bloque, linea, suceso in (("corners", "9.5", "mas_9_5"),
                                  ("tarjetas", "3.5", "mas_3_5")):
        b = pron.get(bloque) or {}
        if b.get("disponible") and (b.get("mas_de") or {}).get(linea) is not None:
            salida[(bloque, suceso)] = b["mas_de"][linea]
    return salida


def _mezcla(nuestra: dict[str, float], mercado: dict[str, float], peso: float) -> dict:
    """Mezcla geométrica de dos repartos del 1X2: el mercado con un poco de lo nuestro.

    Geométrica y no una media simple porque es la que respeta que las dos cosas
    son opiniones con información propia: una probabilidad muy baja de uno de los
    dos pesa de verdad, en vez de diluirse.
    """
    crudas = {s: max(nuestra[s], 1e-4) ** peso * max(mercado[s], 1e-4) ** (1 - peso)
              for s in LADOS}
    total = sum(crudas.values())
    return {s: p / total for s, p in crudas.items()}


def _log_loss_1x2(filas: list[dict], peso: float) -> float:
    return -sum(math.log(max(_mezcla(f["nuestra"], f["mercado"], peso)[f["real"]], 1e-6))
                for f in filas) / len(filas)


def _intervalo(diferencias: list[float]) -> tuple[float, float, float]:
    """Media e intervalo al 95 % de unas diferencias emparejadas."""
    n = len(diferencias)
    media = sum(diferencias) / n
    if n < 2:
        return media, float("-inf"), float("inf")
    desvio = math.sqrt(sum((d - media) ** 2 for d in diferencias) / (n - 1))
    margen = 1.96 * desvio / math.sqrt(n)
    return media, media - margen, media + margen


def backtest(almacen, desde: str | None = None, hasta: str | None = None,
             liga_id: int | None = None, regla: dict | None = None,
             avisar: Callable[[str], None] | None = None,
             puede_seguir: Callable[[], bool] | None = None,
             limite: int = 0) -> dict:
    """Rehace los pronósticos de los partidos jugados que tienen cuotas, y los mide."""
    from .mercados import distribucion_de_marcadores
    from .picks import REGLA
    from .previa import _evento_desde_fila
    from .pronostico import pronostico
    from .registro import _en_casillas, _resultado_de, precios_del_mercado

    regla = regla or REGLA
    decir = avisar or (lambda _t: None)
    sigue = puede_seguir or (lambda: True)
    condiciones = ["p.estado = 'finished'", "p.goles_local IS NOT NULL",
                   "(EXISTS (SELECT 1 FROM cuotas_mercado c WHERE c.partido_id = p.id)"
                   " OR EXISTS (SELECT 1 FROM cuotas c WHERE c.partido_id = p.id))"]
    parametros: list = []
    for campo, valor, operador in (("p.fecha", desde, ">="), ("p.fecha", hasta, "<="),
                                   ("p.liga_id", liga_id, "=")):
        if valor:
            condiciones.append(f"{campo} {operador} ?")
            parametros.append(valor)
    filas = almacen.consulta(
        f"SELECT p.* FROM partidos p WHERE {' AND '.join(condiciones)} "
        "ORDER BY p.momento" + (f" LIMIT {int(limite)}" if limite else ""),
        tuple(parametros))
    decir(f"{len(filas)} partidos jugados con cuotas. Rehaciendo cada pronóstico con "
          "solo lo que se sabía antes…")

    unox2, binarios, exactos, picks = [], {b[0]: [] for b in BINARIOS}, [], []
    guardados: list[tuple[dict, dict]] = []
    sin_muestra = 0
    for numero, fila in enumerate(filas, 1):
        if not sigue():
            decir(f"Parado con {numero - 1} de {len(filas)} mirados.")
            break
        evento = _evento_desde_fila(fila)
        try:
            pron = pronostico(almacen, evento)
        except Exception:  # noqa: BLE001 - un partido raro no para el backtest
            pron = {}
        if not pron.get("disponible"):
            sin_muestra += 1
            continue
        guardados.append((fila, pron))
        precios = precios_del_mercado(almacen, fila["id"])
        nuestras = _nuestras(pron)
        gl, gv = fila["goles_local"], fila["goles_visitante"]
        real = "local" if gl > gv else ("visitante" if gv > gl else "empate")

        if all(("1x2", s) in precios for s in LADOS) and all(("1x2", s) in nuestras
                                                            for s in LADOS):
            total = sum(precios[("1x2", s)] for s in LADOS) or 1
            unox2.append({"fecha": fila["fecha"], "real": real,
                          "nuestra": {s: nuestras[("1x2", s)] for s in LADOS},
                          "mercado": {s: precios[("1x2", s)] / total for s in LADOS}})

        for mercado, seleccion, _ in BINARIOS:
            if (mercado, seleccion) in nuestras and (mercado, seleccion) in precios:
                resultado = _resultado_de(almacen, {
                    **fila, "estado": "finished", "mercado": mercado,
                    "seleccion": seleccion, "partido_id": fila["id"], "autor": ""})
                if resultado is not None:
                    binarios[mercado].append({
                        "nuestra": nuestras[(mercado, seleccion)],
                        "mercado": precios[(mercado, seleccion)],
                        "paso": 1 if resultado[0] else 0})

        todos = (pron.get("goles") or {}).get("todos_los_marcadores")
        dist = distribucion_de_marcadores(almacen.mercados_de(fila["id"]))
        if todos and dist.get("disponible"):
            casillas = set(dist["marcadores"])
            marcador = f"{gl}-{gv}"
            cae = marcador if marcador in casillas else "otro"
            suya = {**dist["marcadores"], "otro": dist["otros"]}
            p_nos = _en_casillas(todos, casillas)[cae]
            p_mdo = _en_casillas(suya, casillas)[cae]
            exactos.append({"nuestra": p_nos, "mercado": p_mdo})

        picks += _simular(almacen, fila, pron, regla, None)
        if numero % 200 == 0:
            decir(f"{numero}/{len(filas)} · {len(unox2)} con 1X2 · {len(picks)} picks")

    aporta = _aporta(unox2)
    # Los picks de la regla de verdad: con el peso elegido en la primera mitad y
    # simulados **solo en la segunda**, que ese peso no ha visto. Es el número que
    # importa; el de arriba, con el modelo a secas, es para ver cuánto de su
    # «ventaja» era error suyo.
    con_mezcla: list[dict] = []
    if aporta.get("peso_elegido") is not None and unox2:
        corte = unox2[len(unox2) // 2]["fecha"]
        for fila, pron in guardados:
            if (fila["fecha"] or "") >= corte:
                con_mezcla += _simular(almacen, fila, pron, regla,
                                       aporta["peso_elegido"])

    salida = {
        "hecho_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "regla": regla["version"],
        "partidos_mirados": len(filas), "sin_muestra": sin_muestra,
        "desde": filas[0]["fecha"] if filas else None,
        "hasta": filas[-1]["fecha"] if filas else None,
        "aporta": aporta,
        "por_mercado": _por_mercado(unox2, binarios),
        "calibracion": _calibracion(unox2),
        "picks": _picks(con_mezcla),
        "picks_modelo_solo": _picks(picks),
        "marcador_exacto": _exactos(exactos),
        "advertencias": _advertencias(len(unox2), con_mezcla),
    }
    decir("Hecho.")
    return salida


def _simular(almacen, fila: dict, pron: dict, regla: dict,
             peso: float | None) -> list[dict]:
    """Los picks que la regla habría dado en un partido, y cómo habrían salido."""
    from .picks import candidatos
    from .registro import _resultado_de

    salida = []
    for candidato in [c for c in candidatos(almacen, fila["id"], pron, regla, peso=peso)
                      if c["pasa"]][:regla["por_partido"]]:
        resultado = _resultado_de(almacen, {
            **fila, "estado": "finished", "mercado": candidato["mercado"],
            "seleccion": candidato["seleccion"], "partido_id": fila["id"], "autor": ""})
        if resultado is None:
            continue
        salida.append({"fecha": fila["fecha"], "liga": fila.get("liga"),
                       "partido": f"{fila['local']} - {fila['visitante']}",
                       "suceso": candidato["suceso"], "cuota": candidato["cuota"],
                       "valor": candidato["valor"], "acerto": resultado[0],
                       "beneficio": candidato["cuota"] - 1 if resultado[0] else -1.0})
    return salida


# ------------------------------------------------ lo que se queda guardado

def guardar_mezcla(almacen, datos: dict) -> dict:
    """Apunta lo que ha dicho el backtest sobre cuánto pesa nuestro modelo.

    Es lo que usan después los picks: si el modelo aporta, se mezcla con el
    mercado con el peso que se ganó en partidos que no se usaron para elegirlo; si
    no aporta, el peso es cero y no hay picks. Guardarlo aquí y no recalcularlo
    cada vez es a propósito: un backtest se decide mirándolo, no a escondidas.
    """
    import json

    aporta = datos.get("aporta") or {}
    mezcla = {"peso": aporta.get("peso_elegido") if aporta.get("veredicto") == "aporta"
              else 0.0,
              "veredicto": aporta.get("veredicto"), "partidos": aporta.get("partidos"),
              "hecho_el": datos.get("hecho_el"), "desde": datos.get("desde"),
              "hasta": datos.get("hasta")}
    almacen.anotar("mezcla", json.dumps(mezcla))
    almacen.anotar("ultimo_backtest", json.dumps(datos, default=str))
    return mezcla


def ultimo(almacen) -> dict | None:
    """El último backtest guardado, entero, para enseñarlo sin rehacerlo."""
    import json

    crudo = almacen.nota("ultimo_backtest")
    return json.loads(crudo) if crudo else None


# -------------------------------------------------- ¿aporta algo el modelo?

def _aporta(filas: list[dict]) -> dict:
    """¿Mezclar lo nuestro con el mercado mejora al mercado solo?

    El peso se elige con la primera mitad (por fecha) y se mide en la segunda.
    Elegirlo y medirlo sobre los mismos partidos garantizaría que saliese algo
    mejor que cero aunque el modelo no sirviera para nada.
    """
    if len(filas) < 40:
        return {"partidos": len(filas), "veredicto": "sin muestra",
                "lectura": "Hacen falta más partidos con 1X2 de los dos lados."}
    mitad = len(filas) // 2
    primera, segunda = filas[:mitad], filas[mitad:]
    por_peso = {peso: round(_log_loss_1x2(primera, peso), 5) for peso in PESOS}
    elegido = min(por_peso, key=por_peso.get)
    mezcla = [-math.log(max(_mezcla(f["nuestra"], f["mercado"], elegido)[f["real"]], 1e-6))
              for f in segunda]
    solo = [-math.log(max(f["mercado"][f["real"]], 1e-6)) for f in segunda]
    solo_nuestro = [-math.log(max(f["nuestra"][f["real"]], 1e-6)) for f in segunda]
    media, abajo, arriba = _intervalo([s - m for s, m in zip(solo, mezcla, strict=True)])
    if elegido == 0.0:
        veredicto = "no aporta"
    elif abajo > 0:
        veredicto = "aporta"
    else:
        veredicto = "no se distingue"
    return {
        "partidos": len(filas), "elegido_con": len(primera), "medido_en": len(segunda),
        "peso_elegido": elegido, "log_loss_por_peso": por_peso,
        "log_loss_mercado": round(sum(solo) / len(solo), 5),
        "log_loss_mezcla": round(sum(mezcla) / len(mezcla), 5),
        "log_loss_modelo_solo": round(sum(solo_nuestro) / len(solo_nuestro), 5),
        "mejora": round(media, 5), "intervalo": [round(abajo, 5), round(arriba, 5)],
        "veredicto": veredicto,
        "lectura": _lectura_aporta(veredicto, elegido, media, len(segunda)),
    }


def _lectura_aporta(veredicto: str, peso: float, mejora: float, n: int) -> str:
    if veredicto == "no aporta":
        return ("El mejor peso para nuestro modelo es cero: mezclado con el mercado lo "
                "empeora. Con estos datos, el modelo no sabe nada que las casas no "
                "sepan ya, y ningún pick debería apoyarse en él.")
    if veredicto == "aporta":
        return (f"Mezclando un {peso:.0%} de lo nuestro con el mercado, la predicción "
                f"mejora en {n} partidos que no se usaron para elegir ese peso, y la "
                "mejora no cabe en el azar. El modelo sabe algo que el mercado no.")
    return (f"El mejor peso fue un {peso:.0%}, pero en los {n} partidos de "
            "comprobación la mejora cabe en el azar. Todavía no se puede decir que el "
            "modelo aporte algo.")


# ------------------------------------------------------------- por mercado

def _por_mercado(unox2: list[dict], binarios: dict) -> list[dict]:
    """Brier nuestro y del mercado, suceso a suceso, sobre los mismos partidos."""
    salida = []
    if unox2:
        for lado in LADOS:
            nos = [(f["nuestra"][lado] - (f["real"] == lado)) ** 2 for f in unox2]
            mdo = [(f["mercado"][lado] - (f["real"] == lado)) ** 2 for f in unox2]
            salida.append(_fila_mercado(f"1X2 · {lado}", nos, mdo))
    for mercado, _, etiqueta in BINARIOS:
        filas = binarios.get(mercado) or []
        if filas:
            nos = [(f["nuestra"] - f["paso"]) ** 2 for f in filas]
            mdo = [(f["mercado"] - f["paso"]) ** 2 for f in filas]
            salida.append(_fila_mercado(etiqueta, nos, mdo))
    return salida


def _fila_mercado(etiqueta: str, nos: list[float], mdo: list[float]) -> dict:
    media, abajo, arriba = _intervalo([m - n for n, m in zip(nos, mdo, strict=True)])
    return {"suceso": etiqueta, "casos": len(nos),
            "brier_nuestro": round(sum(nos) / len(nos), 4),
            "brier_mercado": round(sum(mdo) / len(mdo), 4),
            "ventaja": round(media, 4), "intervalo": [round(abajo, 4), round(arriba, 4)],
            "gana": ("nosotros" if abajo > 0 else "el mercado" if arriba < 0
                     else "no se distingue")}


def _calibracion(unox2: list[dict]) -> list[dict]:
    """De las veces que el modelo dijo X en el 1X2, cuántas pasó."""
    tramos: dict[int, list[tuple[float, int]]] = {}
    for f in unox2:
        for lado in LADOS:
            p = f["nuestra"][lado]
            tramos.setdefault(min(int(p * 10), 9), []).append((p, int(f["real"] == lado)))
    salida = []
    for tramo in sorted(tramos):
        suyos = tramos[tramo]
        if len(suyos) < 20:
            continue
        dijo = sum(p for p, _ in suyos) / len(suyos)
        paso = sum(r for _, r in suyos) / len(suyos)
        salida.append({"tramo": f"{tramo * 10}-{tramo * 10 + 10}%", "casos": len(suyos),
                       "dijo": round(dijo, 3), "paso": round(paso, 3),
                       "desvio": round(paso - dijo, 3)})
    return salida


# --------------------------------------------------------------- los picks

def _picks(picks: list[dict]) -> dict:
    """La regla simulada partido a partido, a la cuota de cierre."""
    if not picks:
        return {"picks": 0, "lectura": "Ningún partido del pasado habría pasado la regla."}
    n = len(picks)
    beneficios = [p["beneficio"] for p in picks]
    media, abajo, arriba = _intervalo(beneficios)
    acumulado, pico, caida, meses = 0.0, 0.0, 0.0, {}
    for p in picks:
        acumulado += p["beneficio"]
        pico, caida = max(pico, acumulado), min(caida, acumulado - pico)
        mes = (p["fecha"] or "")[:7]
        meses[mes] = meses.get(mes, 0.0) + p["beneficio"]
    por_suceso: dict[str, list[float]] = {}
    for p in picks:
        por_suceso.setdefault(p["suceso"], []).append(p["beneficio"])
    return {
        "picks": n, "aciertos": sum(1 for p in picks if p["acerto"]),
        "cuota_media": round(sum(p["cuota"] for p in picks) / n, 2),
        "unidades": round(sum(beneficios), 2), "rendimiento": round(media, 4),
        "intervalo": ([round(abajo, 4), round(arriba, 4)] if n > 1 else [None, None]),
        "peor_racha": round(caida, 2),
        # Redondeado al final y no en cada suma: redondear sobre la marcha iba
        # acumulando error, y el desglose por mes no cuadraba con el total.
        "por_mes": {mes: round(total, 2) for mes, total in meses.items()},
        "por_suceso": {s: {"picks": len(b), "unidades": round(sum(b), 2)}
                       for s, b in sorted(por_suceso.items(), key=lambda x: -len(x[1]))},
        "ultimos": picks[-20:],
        "lectura": _lectura_picks(n, media, abajo, arriba),
    }


def _lectura_picks(n: int, media: float, abajo: float, arriba: float) -> str:
    base = (f"{n} pick{'s' if n != 1 else ''} a una unidad, a la cuota de cierre: "
            f"rendimiento {media:+.1%}")
    if n < 2:
        return base + ". Con uno solo no se puede decir nada."
    base += f", entre {abajo:+.1%} y {arriba:+.1%} al 95 %. "
    if abajo > 0:
        return base + "El intervalo entero está por encima de cero."
    if arriba < 0:
        return base + ("El intervalo entero está por debajo de cero: esta regla, con "
                       "este modelo, pierde.")
    return base + "El cero cabe en el intervalo: no se distingue de la suerte."


def _exactos(filas: list[dict]) -> dict:
    if not filas:
        return {"partidos": 0,
                "lectura": "La fuente no tenía marcador exacto de ningún partido mirado."}
    difs = [math.log(f["nuestra"]) - math.log(f["mercado"]) for f in filas]
    media, abajo, arriba = _intervalo(difs)
    return {"partidos": len(filas),
            "p_real_nuestra": round(sum(f["nuestra"] for f in filas) / len(filas), 4),
            "p_real_mercado": round(sum(f["mercado"] for f in filas) / len(filas), 4),
            "diferencia_log": round(media, 4), "intervalo": [round(abajo, 4), round(arriba, 4)],
            "gana": ("nosotros" if abajo > 0 else "el mercado" if arriba < 0
                     else "no se distingue")}


def _advertencias(con_1x2: int, picks: list[dict]) -> list[str]:
    avisos = ["A la cuota de cierre, que es la más difícil de batir: en la vida real "
              "se apuesta antes, a un precio que puede ser mejor o peor.",
              "Solo entran partidos con cuotas guardadas: si la fuente no las tenía de "
              "una liga, esa liga no está aquí.",
              "Si se retoca la regla hasta que esto salga bonito, esto deja de valer. "
              "Por eso la regla lleva versión: cambiarla es empezar de cero."]
    if con_1x2 < MINIMO_PARTIDOS:
        avisos.insert(0, f"Solo {con_1x2} partidos con 1X2 de los dos lados: por debajo "
                         f"de {MINIMO_PARTIDOS} esto es un indicio, no un juicio. Trae más "
                         "historia con `cancha historia`.")
    if len(picks) < 100:
        avisos.append(f"Solo {len(picks)} picks simulados: con menos de cien, el "
                      "rendimiento es casi todo varianza.")
    return avisos


__all__ = ["BINARIOS", "MINIMO_PARTIDOS", "PESOS", "backtest", "guardar_mezcla",
           "ultimo"]
