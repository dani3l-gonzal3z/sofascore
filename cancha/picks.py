"""Los picks: una regla fija, el precio al que se dio, y un historial que no se toca.

Esto es la parte que se puede vender, y conviene decir primero lo que **no** es:
no es «la apuesta segura del día». No existe. Quien la vende o se equivoca o
miente, y el cliente lo descubre en dos semanas. Lo que sí se puede vender —y es
lo único que aguanta— es esto:

1. **Una regla escrita antes**, igual para todos los días: qué tiene que pasar
   para que un suceso sea pick. No se elige a ojo ni se cambia según vaya el mes.
2. **El precio al que se dio**, apuntado antes del saque. Un acierto a 1,30 y uno
   a 2,40 no valen lo mismo, y un historial sin precios es un historial que no se
   puede comprobar.
3. **Un historial que nadie puede reescribir**, con lo que de verdad dice si
   alguien sabe algo: el rendimiento al precio tomado, con su intervalo, y el
   **CLV** —si la cuota se movió después hacia nuestro lado—, que es lo que mejor
   predice si alguien va a ganar a largo plazo, mucho antes que el acierto.

Y los días en que nada pasa la regla, **no hay pick**. Eso no es un fallo del
producto: es lo que lo hace creíble. Un servicio que da un pick todos los días
pase lo que pase está vendiendo volumen, no criterio.

Dos niveles:

* **gratis**: el mejor pick del día, si lo hay.
* **premium**: todos los que pasan la regla, con su partido abierto al detalle.

Cada nivel lleva su propio historial, porque son dos productos distintos y se
tienen que poder juzgar por separado.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

#: La regla. Cambiarla es cambiar de producto: por eso lleva versión, y cada pick
#: la apunta. Mezclar en un historial los picks de dos reglas es mezclar dos
#: productos.
REGLA = {
    #: regla-2: la probabilidad ya no es la del modelo a secas, sino su mezcla con
    #: el mercado con el peso que haya validado el backtest (ver `mezclar`).
    "version": "regla-2",
    #: Entre estas cuotas. Por debajo de 1,50 el margen de la casa se come casi
    #: toda la ventaja posible; por encima de 3,50 la varianza es tanta que un
    #: historial de cien picks no dice nada.
    "cuota_minima": 1.50,
    "cuota_maxima": 3.50,
    #: Cuánto tiene que ganar de esperanza al precio que se da: un 5 %.
    "valor_minimo": 0.05,
    #: Y cuánto tiene que separarse nuestra probabilidad de la del mercado. Las
    #: dos cosas a la vez: mucho valor con poca separación es un precio raro de
    #: una sola casa, no una opinión nuestra.
    "separacion_minima": 0.04,
    #: Partidos guardados de cada equipo para que el pronóstico cuente.
    "partidos_minimos": 8,
    #: Un mercado donde la casa cobra más que esto no es un mercado, es un peaje.
    "margen_maximo": 0.08,
    #: Uno por partido como mucho: dos picks del mismo partido son la misma
    #: apuesta dos veces, y duplicarían lo que se gana o se pierde con un error.
    "por_partido": 1,
}

#: Lo que se compara, con cómo se llama en nuestro pronóstico, en las casas y en
#: el registro (para resolverlo con las mismas reglas que todo lo demás).
SUCESOS = (
    # etiqueta, nuestra: (bloque, clave, complemento), casa: (mercado, línea, sel), registro
    ("Gana el local", ("1x2", "local", False), ("1x2", "", "local"), ("1x2", "local")),
    ("Empate", ("1x2", "empate", False), ("1x2", "", "empate"), ("1x2", "empate")),
    ("Gana el visitante", ("1x2", "visitante", False), ("1x2", "", "visitante"),
     ("1x2", "visitante")),
    ("Más de 2,5 goles", ("mas_de", "2.5", False), ("goles", "2.5", "mas"),
     ("mas_2_5", "si")),
    ("Menos de 2,5 goles", ("mas_de", "2.5", True), ("goles", "2.5", "menos"),
     ("mas_2_5", "no")),
    ("Marcan los dos", ("ambos_marcan", None, False), ("ambos_marcan", "", "si"),
     ("ambos_marcan", "si")),
    ("No marcan los dos", ("ambos_marcan", None, True), ("ambos_marcan", "", "no"),
     ("ambos_marcan", "no")),
    ("Más de 9,5 córners", ("corners", "9.5", False), ("corners", "9.5", "mas"),
     ("corners", "mas_9_5")),
    ("Menos de 9,5 córners", ("corners", "9.5", True), ("corners", "9.5", "menos"),
     ("corners", "menos_9_5")),
    ("Más de 3,5 tarjetas", ("tarjetas", "3.5", False), ("tarjetas", "3.5", "mas"),
     ("tarjetas", "mas_3_5")),
    ("Menos de 3,5 tarjetas", ("tarjetas", "3.5", True), ("tarjetas", "3.5", "menos"),
     ("tarjetas", "menos_3_5")),
)

#: Una bolsa (Betfair) no da un precio al que se pueda apostar tal cual: su
#: precio justo es el punto medio entre comprar y vender. Sirve de referencia de
#: lo que cree el mercado, pero no como «la cuota a la que se da el pick».
NO_APOSTABLES = ("betfair-exchange",)


def mezcla_guardada(almacen) -> dict | None:
    """Lo que dijo el último backtest sobre cuánto pesa nuestro modelo, si lo hay."""
    import json

    crudo = almacen.nota("mezcla")
    return json.loads(crudo) if crudo else None


def mezclar(nuestra: float, mercado: float, peso: float | None) -> float:
    """La probabilidad que se usa para decidir: el mercado con un poco de lo nuestro.

    Por qué no la nuestra a secas: casi toda la distancia entre un modelo y el
    mercado es **error del modelo**, no información. Elegir picks con el modelo
    solo es elegir sus errores más grandes y apostar a ellos. El backtest mide
    cuánto de lo nuestro mejora al mercado en partidos que no ha visto, y ese es
    el peso que se usa. Sin backtest (``None``), el modelo a secas y se avisa;
    con un backtest que dice que no aporta, el peso es cero: la probabilidad es la
    del mercado, el valor nunca es positivo, y no hay picks. Es incómodo y es lo
    honesto.
    """
    if peso is None:
        return nuestra
    n = min(max(nuestra, 1e-4), 1 - 1e-4)
    m = min(max(mercado, 1e-4), 1 - 1e-4)
    logit = peso * math.log(n / (1 - n)) + (1 - peso) * math.log(m / (1 - m))
    return 1 / (1 + math.exp(-logit))


def _nuestra(pronostico: dict, donde: tuple) -> float | None:
    bloque, clave, complemento = donde
    goles = pronostico.get("goles") or {}
    if bloque == "1x2":
        valor = (goles.get("1x2") or {}).get(clave)
    elif bloque == "mas_de":
        valor = (goles.get("mas_de") or {}).get(clave)
    elif bloque == "ambos_marcan":
        valor = goles.get("ambos_marcan")
    else:
        otro = pronostico.get(bloque) or {}
        valor = (otro.get("mas_de") or {}).get(clave) if otro.get("disponible") else None
    if valor is None:
        return None
    return 1 - valor if complemento else valor


def candidatos(almacen, partido_id: int, pronostico: dict, regla: dict = REGLA,
               peso: float | None = None) -> list[dict]:
    """Todos los sucesos de un partido, con su valor y si pasan la regla o por qué no.

    Se devuelven también los que no pasan, con el motivo: para el que quiera
    entender por qué hoy no hay pick, y para comprobar que la regla hace lo que
    dice.
    """
    if not pronostico.get("disponible"):
        return []
    fuerzas = (pronostico.get("goles") or {}).get("fuerzas") or {}
    muestra = min((fuerzas.get(lado) or {}).get("partidos") or 0
                  for lado in ("local", "visitante"))
    filas = almacen.mercados_de(partido_id)
    salida = []
    for etiqueta, en_nuestro, en_casa, en_registro in SUCESOS:
        nuestra = _nuestra(pronostico, en_nuestro)
        suyas = [f for f in filas if (f["mercado"], f["linea"], f["seleccion"]) == en_casa]
        if nuestra is None or not suyas:
            continue
        referencia = min(suyas, key=lambda f: f["margen"] if f["margen"] is not None else 9)
        apostables = [f for f in suyas if f["casa"] not in NO_APOSTABLES] or suyas
        mejor = max(apostables, key=lambda f: f["cuota"])
        cuota = mejor["cuota"]
        del_modelo = nuestra
        nuestra = mezclar(del_modelo, referencia["prob"] or 0.5, peso)
        valor = nuestra * cuota - 1
        separacion = nuestra - (referencia["prob"] or 0)
        motivos = []
        if muestra < regla["partidos_minimos"]:
            motivos.append(f"muestra corta ({muestra} partidos)")
        if not regla["cuota_minima"] <= cuota <= regla["cuota_maxima"]:
            motivos.append(f"cuota {cuota} fuera de {regla['cuota_minima']}–"
                           f"{regla['cuota_maxima']}")
        if valor < regla["valor_minimo"]:
            motivos.append(f"valor {valor:+.1%}")
        if separacion < regla["separacion_minima"]:
            motivos.append(f"solo {separacion:+.1%} sobre el mercado")
        if (referencia["margen"] or 0) > regla["margen_maximo"]:
            motivos.append(f"la casa cobra un {referencia['margen']:.1%}")
        salida.append({
            "partido_id": partido_id, "suceso": etiqueta,
            "mercado": en_registro[0], "seleccion": en_registro[1],
            "prob_nuestra": round(nuestra, 4),
            "prob_modelo": round(del_modelo, 4),
            "prob_mercado": round(referencia["prob"] or 0, 4),
            "cuota": cuota, "casa": mejor["casa"],
            "valor": round(valor, 4), "separacion": round(separacion, 4),
            "muestra": muestra, "pasa": not motivos, "por_que_no": motivos,
        })
    return sorted(salida, key=lambda c: -c["valor"])


def del_dia(almacen, cliente, fecha: str | None = None,
            grupos: list[str] | None = None, regla: dict = REGLA) -> dict:
    """Los picks de un día: los que pasan la regla, del de más valor al de menos.

    El primero es el pick gratis; todos, el premium. Si ninguno pasa, se dice, y
    se enseña qué ha estado más cerca y por qué no: eso también es información, y
    es la que hace creíble el día que sí hay pick.
    """
    from .barrido import agenda
    from .pronostico import pronostico

    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mezcla = mezcla_guardada(almacen)
    peso = mezcla["peso"] if mezcla else None
    elegidos, casi = [], []
    for evento in agenda(cliente, dia, grupos):
        if evento.is_finished:
            continue
        datos = pronostico(almacen, evento, cliente=cliente)
        suyos = candidatos(almacen, evento.id, datos, regla, peso=peso)
        for c in suyos:
            c["partido"] = f"{evento.home.name} - {evento.away.name}"
            c["competicion"] = evento.tournament
            c["hora_utc"] = evento.kickoff.strftime("%H:%M") if evento.kickoff else None
        buenos = [c for c in suyos if c["pasa"]][:regla["por_partido"]]
        elegidos += buenos
        casi += [c for c in suyos if not c["pasa"]][:1]
    elegidos.sort(key=lambda c: -c["valor"])
    casi.sort(key=lambda c: -c["valor"])
    if mezcla and mezcla.get("peso") == 0:
        nota = ("El último backtest dice que el modelo no sabe nada que el mercado no "
                "sepa, así que no hay picks: la probabilidad que se usa es la del "
                "mercado, y contra el mercado nunca hay valor.")
    elif not elegidos:
        nota = ("Hoy nada pasa la regla. No hay pick: un día sin pick no es un fallo, "
                "es lo que hace creíble el día que sí lo hay.")
    else:
        nota = ""
    return {
        "fecha": dia, "regla": regla["version"],
        "gratis": elegidos[:1], "premium": elegidos,
        "casi": casi[:5], "nota": nota,
        "validada": bool(mezcla), "peso": peso,
    }


def apuntados(almacen, fecha: str) -> dict | None:
    """Los picks ya apuntados de un día, con la forma de `del_dia`. None si no hay.

    Es lo que se enseña primero: lo apuntado es lo que cuenta, con el precio de
    cuando se apuntó. Volver a calcularlo daría otros precios, y enseñar esos como
    «el pick de hoy» sería enseñar algo distinto de lo que se juzga después.
    """
    filas = almacen.consulta(
        """SELECT k.*, m.local || ' - ' || m.visitante AS partido, m.liga AS competicion
           FROM picks k LEFT JOIN partidos m ON m.id = k.partido_id
           WHERE k.fecha = ? ORDER BY k.valor DESC""", (fecha,))
    if not filas:
        return None
    return {"fecha": fecha, "regla": filas[0]["regla"], "apuntado": True,
            "gratis": [f for f in filas if f["nivel"] == "gratis"],
            "premium": [f for f in filas if f["nivel"] == "premium"], "casi": [],
            "nota": ""}


# ------------------------------------------------------------------ apuntarlos

def apuntar(almacen, dia: dict) -> dict:
    """Apunta los picks del día, cada uno con el precio al que se da. Una vez.

    No se pisa nada: el primero que se apunta es el que cuenta. Un historial que
    se puede reescribir no vale nada, y en un producto de pago todavía menos.
    """
    from .previa import _resolver
    from .registro import _horas_hasta

    guardados = 0
    for nivel, lista in (("gratis", dia["gratis"]), ("premium", dia["premium"])):
        for pick in lista:
            evento = _resolver(almacen, pick["partido_id"], None)
            cursor = almacen._conexion.execute(
                """INSERT OR IGNORE INTO picks
                   (fecha, nivel, partido_id, suceso, mercado, seleccion, prob_nuestra,
                    prob_mercado, cuota, casa, valor, regla, horas_antes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (dia["fecha"], nivel, pick["partido_id"], pick["suceso"],
                 pick["mercado"], pick["seleccion"], pick["prob_nuestra"],
                 pick["prob_mercado"], pick["cuota"], pick["casa"], pick["valor"],
                 dia["regla"], _horas_hasta(evento) if evento else None))
            guardados += cursor.rowcount or 0
    almacen._conexion.commit()
    return {"apuntados": guardados}


def resolver(almacen) -> dict:
    """Resuelve los picks de partidos ya jugados, con las reglas del registro.

    Y apunta la cuota de cierre: la última que se vio antes del saque, de la misma
    casa. Si el pick se dio a 2,10 y cerró a 1,90, el mercado se movió hacia
    nosotros: eso es CLV, y es lo que mejor dice si esto funciona, mucho antes
    que el acierto.
    """
    from .registro import _resultado_de

    pendientes = almacen.consulta(
        """SELECT k.*, m.goles_local, m.goles_visitante, m.estado, m.momento
           FROM picks k JOIN partidos m ON m.id = k.partido_id
           WHERE k.resuelto = 0""")
    hechos = 0
    for pick in pendientes:
        real = _resultado_de(almacen, {**pick, "autor": "pick"})
        if real is None:
            continue
        acerto, valor_real = real
        cierre = _cuota_de_cierre(almacen, pick)
        almacen._conexion.execute(
            """UPDATE picks SET resuelto = 1, acerto = ?, valor_real = ?,
                   beneficio = ?, cuota_cierre = ?, resuelto_el = ?
               WHERE id = ?""",
            (1 if acerto else 0, valor_real,
             round(pick["cuota"] - 1, 4) if acerto else -1.0, cierre,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), pick["id"]))
        hechos += 1
    almacen._conexion.commit()
    return {"resueltos": hechos, "pendientes": len(pendientes) - hechos}


def _cuota_de_cierre(almacen, pick: dict) -> float | None:
    """La última cuota vista antes del saque, de la misma casa y el mismo suceso."""
    from .registro import EN_EL_MERCADO

    casa = EN_EL_MERCADO.get((pick["mercado"], pick["seleccion"]))
    if pick["mercado"] == "1x2":
        casa = ("1x2", "", pick["seleccion"])
    elif pick["mercado"] in ("corners", "tarjetas") and casa is None:
        linea = "9.5" if pick["mercado"] == "corners" else "3.5"
        casa = (pick["mercado"], linea,
                "mas" if pick["seleccion"].startswith("mas") else "menos")
    if casa is None:
        return None
    filas = almacen.consulta(
        """SELECT cuota FROM cuotas_mercado
           WHERE partido_id = ? AND casa = ? AND mercado = ? AND linea = ?
             AND seleccion = ? AND (horas_antes IS NULL OR horas_antes >= 0)
           ORDER BY visto_en DESC LIMIT 1""",
        (pick["partido_id"], pick["casa"], *casa))
    return filas[0]["cuota"] if filas else None


# ------------------------------------------------------------------ el historial

def historial(almacen, nivel: str = "gratis", desde: str | None = None) -> dict:
    """Lo que se puede enseñar a un cliente: cómo han ido de verdad los picks.

    A una unidad por pick, sin trucos de gestión de banca que maquillen nada. Con
    el rendimiento y su intervalo al 95 %, porque cuarenta picks con un +15 % no
    son un +15 %: son algo entre un −20 % y un +50 %, y hay que decirlo así.
    """
    filas = almacen.consulta(
        "SELECT * FROM picks WHERE nivel = ? AND resuelto = 1"
        + (" AND fecha >= ?" if desde else "") + " ORDER BY fecha, id",
        (nivel, *([desde] if desde else [])))
    pendientes = almacen.consulta(
        "SELECT COUNT(*) AS n FROM picks WHERE nivel = ? AND resuelto = 0",
        (nivel,))[0]["n"]
    if not filas:
        return {"nivel": nivel, "picks": 0, "pendientes": pendientes,
                "nota": "Todavía no hay picks resueltos en este nivel."}
    n = len(filas)
    beneficios = [f["beneficio"] for f in filas]
    total = sum(beneficios)
    media = total / n
    desvio = (sum((b - media) ** 2 for b in beneficios) / (n - 1)) ** 0.5 if n > 1 else 0.0
    margen_ic = 1.96 * desvio / math.sqrt(n) if n > 1 else float("inf")

    acumulado, pico, caida = 0.0, 0.0, 0.0
    for b in beneficios:
        acumulado += b
        pico = max(pico, acumulado)
        caida = min(caida, acumulado - pico)

    con_cierre = [f for f in filas if f["cuota_cierre"]]
    clv = ([f["cuota"] / f["cuota_cierre"] - 1 for f in con_cierre])
    return {
        "nivel": nivel, "picks": n, "pendientes": pendientes,
        "aciertos": sum(f["acerto"] for f in filas),
        "acierto": round(sum(f["acerto"] for f in filas) / n, 3),
        "cuota_media": round(sum(f["cuota"] for f in filas) / n, 2),
        "unidades": round(total, 2),
        "rendimiento": round(media, 4),
        "intervalo": ([round(media - margen_ic, 4), round(media + margen_ic, 4)]
                      if n > 1 else None),
        "peor_racha": round(caida, 2),
        "clv_medio": round(sum(clv) / len(clv), 4) if clv else None,
        "gana_al_cierre": round(sum(1 for c in clv if c > 0) / len(clv), 3) if clv else None,
        "con_cierre": len(con_cierre),
        "desde": filas[0]["fecha"], "hasta": filas[-1]["fecha"],
        "lectura": _lectura(n, media, margen_ic, clv),
    }


#: Por debajo de esto, ningún rendimiento dice nada. Se enseña, pero con el aviso.
MINIMO_PARA_VENDER = 200


def _lectura(n: int, media: float, margen_ic: float, clv: list[float]) -> str:
    partes = [f"{n} picks a una unidad: rendimiento {media:+.1%}"
              + (f", entre {media - margen_ic:+.1%} y {media + margen_ic:+.1%} al 95 %."
                 if n > 1 else ".")]
    if clv:
        a_favor = sum(1 for c in clv if c > 0) / len(clv)
        partes.append(f"En el {a_favor:.0%} de los picks la cuota cerró por debajo de "
                      "la que se dio: el mercado se movió hacia nosotros."
                      if a_favor > 0.5 else
                      f"Solo en el {a_favor:.0%} de los picks el mercado se movió hacia "
                      "nosotros después: mala señal, aunque el rendimiento acompañe.")
    if n < MINIMO_PARA_VENDER:
        partes.append(f"Con menos de {MINIMO_PARA_VENDER} picks esto no demuestra nada "
                      "todavía, en ninguna dirección.")
    elif media - margen_ic > 0:
        partes.append("El intervalo entero está por encima de cero: esto ya no parece "
                      "suerte.")
    return " ".join(partes)


# --------------------------------------------------------------- el boletín

def boletin(dia: dict, nivel: str, historial_nivel: dict | None = None) -> str:
    """El mensaje del día, listo para mandar. En HTML de Telegram."""
    lista = dia["gratis"] if nivel == "gratis" else dia["premium"]
    lineas = [f"<b>{'El pick' if nivel == 'gratis' else 'Los picks'} del {dia['fecha']}</b>",
              ""]
    if not lista:
        lineas += ["Hoy nada pasa la regla, así que hoy no hay pick.",
                   "", "<i>Un día sin pick no es un fallo: es lo que hace creíble el "
                   "día que sí lo hay.</i>"]
    for pick in lista:
        lineas += [
            f"⚽ <b>{_escapar(pick['partido'])}</b> · {pick.get('hora_utc') or ''} UTC",
            f"   {_escapar(pick['suceso'])} a <b>{pick['cuota']}</b> ({pick['casa']})",
            f"   Nosotros {pick['prob_nuestra']:.0%} · mercado {pick['prob_mercado']:.0%}"
            f" · valor {pick['valor']:+.0%}",
            ""]
    if lista and not dia.get("validada", True):
        lineas += ["<i>Regla todavía sin validar con un backtest: estos números son del "
                   "modelo a secas.</i>", ""]
    if historial_nivel and historial_nivel.get("picks"):
        h = historial_nivel
        lineas += [f"<i>Historial: {h['picks']} picks, {h['aciertos']} acertados, "
                   f"{h['unidades']:+.2f} unidades ({h['rendimiento']:+.1%}).</i>"]
        if h["picks"] < MINIMO_PARA_VENDER:
            lineas.append(f"<i>Con menos de {MINIMO_PARA_VENDER} picks esto todavía no "
                          "demuestra nada.</i>")
    lineas += ["", "<i>Una unidad por pick. Nada es seguro: esto es una probabilidad "
               "con su precio, no una promesa. Juega con cabeza, y solo si eres mayor "
               "de edad.</i>"]
    return "\n".join(lineas)


def _escapar(texto: Any) -> str:
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


__all__ = ["MINIMO_PARA_VENDER", "REGLA", "SUCESOS", "apuntados", "apuntar",
           "boletin", "mezcla_guardada", "mezclar",
           "candidatos", "del_dia", "historial", "resolver"]
