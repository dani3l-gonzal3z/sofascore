"""El registro: lo que se predijo, y cómo acabó.

Un pronóstico que nadie apunta no se puede juzgar, y uno que se puede reescribir
después no vale nada. Aquí cada predicción se escribe **antes** del partido —con
su fecha, su probabilidad, la del mercado en ese momento y la versión del cálculo
que la hizo— y no se vuelve a tocar. Lo único que se rellena luego es el
resultado.

**Por qué el acierto es la peor forma de medirse.** «Acerté 7 de 10» no dice
nada: si las diez eran favoritos claros, acertar 7 es malo. Lo que se mide aquí,
en este orden:

* **Calibración.** De las veces que dijiste 70 %, ¿pasó el 70 %? Es lo que
  separa a un pronóstico de una opinión, y es lo que miden los que se juegan
  algo —viene de la meteorología, no de las apuestas—. Se enseña por tramos, con
  su número de casos.
* **Brier.** El error cuadrático medio de una probabilidad: ``(p − resultado)²``.
  Cuanto más bajo mejor; 0,25 es lo que saca quien dice 50 % a todo. Se compara
  siempre contra esa referencia, porque un Brier suelto no significa nada.
* **CLV** (*closing line value*): si dijiste 45 % y el mercado acabó en 52 %, el
  mercado se movió hacia ti. Es el único indicio de ventaja que no depende de
  haber acertado, y por eso es el que miran los que viven de esto. Aquí es una
  resta entre la probabilidad del mercado cuando se predijo y la última vista.
* Y el **acierto**, el último, con su intervalo de Wilson al lado.

Lo que **no** hay, a propósito: ni unidades, ni bankroll, ni ROI, ni consejos de
apuesta. Esto mide si el cálculo describe bien el fútbol. Lo que alguien haga con
eso es cosa suya.

    from cancha.registro import anotar, resolver, balance

    anotar(almacen, partido, pronostico(almacen, partido))   # antes del partido
    resolver(almacen)                                        # al día siguiente
    balance(almacen)                                         # qué tal lo hace
"""

from __future__ import annotations

import math
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from .almacen import Almacen

#: Cambia cuando cambie la forma de calcular. Sirve para no mezclar peras con
#: manzanas: un balance que junta dos modelos distintos no mide ninguno.
VERSION_MODELO = "poisson-encogido-1"

#: Los tramos de la curva de calibración. Diez son demasiados para las muestras
#: que hay aquí; cinco se leen y tienen casos dentro.
TRAMOS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))

#: Con menos de esto, un balance no se publica como conclusión. No es un número
#: mágico: es el orden de magnitud por debajo del cual la diferencia entre un
#: pronóstico bueno y uno malo no se distingue del azar.
MINIMO_PARA_JUZGAR = 50

#: Qué se apunta de cada partido. La clave es el mercado; el valor, cómo se saca
#: del pronóstico y cómo se resuelve con el partido ya jugado.
MERCADOS = ("1x2", "mas_2_5", "ambos_marcan", "corners", "tarjetas", "marcador")


# ------------------------------------------------------------------ apuntar

def anotar(almacen: Almacen, partido: Any, pronostico: dict | None = None,
           cliente=None, version: str = VERSION_MODELO) -> dict:
    """Apunta lo que se predice de un partido. No pisa lo ya apuntado.

    Que no pise es la mitad del asunto: si se pudiera volver a escribir encima,
    el registro diría siempre lo que convenga. La primera predicción es la que
    cuenta, y la que se puntúa.
    """
    from .previa import _resolver
    from .pronostico import pronostico as calcular

    evento = partido if hasattr(partido, "home") else _resolver(almacen, partido, cliente)
    if evento is None:
        return {"guardadas": 0, "nota": "No encuentro ese partido."}
    datos = pronostico if pronostico is not None else calcular(
        almacen, evento, cliente=cliente)
    if not datos.get("disponible"):
        return {"guardadas": 0, "partido_id": evento.id,
                "nota": datos.get("nota", "Sin pronóstico que apuntar.")}

    # El partido tiene que estar en la memoria antes que su predicción: la
    # tabla apunta a él, y además `resolver` lo busca ahí para saber cómo acabó.
    # Guardarlo es idempotente y cuesta nada.
    with suppress(Exception):
        almacen.guardar_evento(evento)

    mercado = ((datos.get("mercado") or {}).get("mercado") or {})
    horas = _horas_hasta(evento)
    filas = list(_del_pronostico(datos, mercado))
    guardadas = 0
    for mercado_nombre, seleccion, probabilidad, prob_mercado in filas:
        guardadas += _insertar(almacen, evento, mercado_nombre, seleccion,
                               probabilidad, prob_mercado, horas, version)
    almacen._conexion.commit()
    return {"partido_id": evento.id, "fecha": evento.date, "guardadas": guardadas,
            "ya_estaban": len(filas) - guardadas, "version": version,
            "horas_antes": horas}


def _del_pronostico(datos: dict, mercado: dict):
    """Las predicciones que salen de un pronóstico, una a una.

    Cada una es un suceso **binario** con su probabilidad: así se puede medir la
    calibración, que con un «gana el local» a secas no se puede.
    """
    goles = datos.get("goles") or {}
    uno = goles.get("1x2") or {}
    for lado in ("local", "empate", "visitante"):
        if uno.get(lado) is not None:
            yield "1x2", lado, float(uno[lado]), _sacar(mercado, lado)

    mas_de = goles.get("mas_de") or {}
    if "2.5" in mas_de:
        yield "mas_2_5", "si", float(mas_de["2.5"]), None
    if goles.get("ambos_marcan") is not None:
        yield "ambos_marcan", "si", float(goles["ambos_marcan"]), None

    corners = datos.get("corners") or {}
    if corners.get("disponible") and "9.5" in (corners.get("mas_de") or {}):
        yield "corners", "mas_9_5", float(corners["mas_de"]["9.5"]), None

    tarjetas = datos.get("tarjetas") or {}
    if tarjetas.get("disponible") and "3.5" in (tarjetas.get("mas_de") or {}):
        yield "tarjetas", "mas_3_5", float(tarjetas["mas_de"]["3.5"]), None

    marcadores = goles.get("marcadores") or []
    if marcadores:
        primero = marcadores[0]
        yield "marcador", str(primero["marcador"]), float(primero["probabilidad"]), None


def _sacar(mercado: dict, lado: str) -> float | None:
    valor = mercado.get(lado)
    return float(valor) if isinstance(valor, (int, float)) else None


def _horas_hasta(evento) -> float | None:
    cuando = evento.kickoff
    if cuando is None:
        return None
    return round((cuando - datetime.now(timezone.utc)).total_seconds() / 3600, 2)


def _insertar(almacen: Almacen, evento, mercado: str, seleccion: str,
              probabilidad: float, prob_mercado: float | None,
              horas: float | None, version: str) -> int:
    cursor = almacen._conexion.execute(
        """INSERT OR IGNORE INTO predicciones
           (partido_id, fecha, horas_antes, version, mercado, seleccion,
            probabilidad, prob_mercado)
           VALUES (?,?,?,?,?,?,?,?)""",
        (evento.id, evento.date, horas, version, mercado, seleccion,
         round(float(probabilidad), 6),
         None if prob_mercado is None else round(float(prob_mercado), 6)))
    return int(cursor.rowcount or 0)


# ----------------------------------------------------------------- resolver

def resolver(almacen: Almacen, fecha: str | None = None, limite: int = 500) -> dict:
    """Puntúa las predicciones cuyos partidos ya se han jugado.

    Se apoya en lo que hay en la memoria: si el partido no está barrido todavía,
    su predicción se queda sin resolver y se resolverá otro día. Eso es correcto
    y es mejor que inventarse el resultado.
    """
    donde = "WHERE p.resuelto = 0"
    parametros: tuple = ()
    if fecha:
        donde += " AND p.fecha = ?"
        parametros = (fecha,)
    pendientes = almacen.consulta(
        f"""SELECT p.*, m.goles_local, m.goles_visitante, m.estado
            FROM predicciones p JOIN partidos m ON m.id = p.partido_id
            {donde} ORDER BY p.fecha LIMIT ?""", (*parametros, limite))

    resueltas, sin_jugar = 0, 0
    for fila in pendientes:
        real = _resultado_de(almacen, fila)
        if real is None:
            sin_jugar += 1
            continue
        acerto, valor = real
        almacen._conexion.execute(
            """UPDATE predicciones
               SET resuelto = 1, acerto = ?, valor_real = ?, prob_cierre = ?,
                   resuelto_el = ?
               WHERE id = ?""",
            (1 if acerto else 0, valor, _cierre(almacen, fila),
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), fila["id"]))
        resueltas += 1
    almacen._conexion.commit()
    return {"resueltas": resueltas, "sin_jugar_todavia": sin_jugar,
            "miradas": len(pendientes)}


def _resultado_de(almacen: Almacen, fila: dict) -> tuple[bool, str] | None:
    """¿Acertó? Y con qué resultado. ``None`` si el partido no se puede juzgar."""
    local, visitante = fila.get("goles_local"), fila.get("goles_visitante")
    estado = (fila.get("estado") or "").lower()
    if local is None or visitante is None or estado not in ("finished", "ended", "ft"):
        return None
    mercado, seleccion = fila["mercado"], fila["seleccion"]
    marcador = f"{local}-{visitante}"

    if mercado == "1x2":
        gano = "local" if local > visitante else ("visitante" if visitante > local
                                                  else "empate")
        return seleccion == gano, marcador
    if mercado == "mas_2_5":
        return (local + visitante) > 2.5, marcador
    if mercado == "ambos_marcan":
        return (local > 0 and visitante > 0), marcador
    if mercado == "marcador":
        return seleccion == marcador, marcador
    if mercado in ("corners", "tarjetas"):
        clave = "cornerKicks" if mercado == "corners" else "yellowCards"
        total = _suma_estadistica(almacen, fila["partido_id"], clave)
        if total is None:
            return None
        linea = 9.5 if mercado == "corners" else 3.5
        return total > linea, f"{total:g}"
    return None


def _suma_estadistica(almacen: Almacen, partido_id: int, clave: str) -> float | None:
    filas = almacen.consulta(
        """SELECT local, visitante FROM estadisticas
           WHERE partido_id = ? AND clave = ? AND periodo = 'ALL'""",
        (partido_id, clave))
    if not filas:
        return None
    fila = filas[0]
    if fila["local"] is None or fila["visitante"] is None:
        return None
    return float(fila["local"]) + float(fila["visitante"])


def _cierre(almacen: Almacen, fila: dict) -> float | None:
    """La probabilidad del mercado en la última cuota vista de ese partido.

    No es el cierre exacto —para eso habría que guardar el historial entero de
    cuotas— sino la última que se llegó a ver, y la fila dice a cuántas horas del
    saque fue. Es lo que hay, y se dice lo que es.
    """
    if fila["mercado"] != "1x2":
        return None
    cuotas = almacen.cuotas_de(fila["partido_id"]) or {}
    probabilidades = cuotas.get("probabilidades") or {}
    valor = probabilidades.get(fila["seleccion"])
    return round(float(valor), 6) if isinstance(valor, (int, float)) else None


# ------------------------------------------------------------------ balance

def brier(predicciones: list[dict]) -> float | None:
    """Error cuadrático medio de las probabilidades. Menos es mejor."""
    if not predicciones:
        return None
    return round(sum((p["probabilidad"] - p["acerto"]) ** 2
                     for p in predicciones) / len(predicciones), 4)


def log_loss(predicciones: list[dict], recorte: float = 1e-6) -> float | None:
    """Castiga mucho más equivocarse con aplomo. Menos es mejor."""
    if not predicciones:
        return None
    total = 0.0
    for p in predicciones:
        probabilidad = min(max(p["probabilidad"], recorte), 1 - recorte)
        total += -(math.log(probabilidad) if p["acerto"]
                   else math.log(1 - probabilidad))
    return round(total / len(predicciones), 4)


def calibracion(predicciones: list[dict]) -> list[dict]:
    """La curva: de las veces que dijiste X, cuántas pasó.

    Es **la** medida. Un pronóstico calibrado dice 70 % y acierta el 70 %; uno
    que dice 70 % y acierta el 95 % no es mejor, es otro pronóstico mal escrito.
    """
    salida = []
    for desde, hasta in TRAMOS:
        dentro = [p for p in predicciones if desde <= p["probabilidad"] < hasta
                  or (hasta == 1.0 and p["probabilidad"] == 1.0)]
        if not dentro:
            continue
        aciertos = sum(p["acerto"] for p in dentro)
        dicho = sum(p["probabilidad"] for p in dentro) / len(dentro)
        pasado = aciertos / len(dentro)
        salida.append({
            "tramo": f"{desde:.0%}-{hasta:.0%}",
            "casos": len(dentro),
            "dijiste": round(dicho, 4),
            "paso": round(pasado, 4),
            "desvio": round(pasado - dicho, 4),
        })
    return salida


def balance(almacen: Almacen, desde: str | None = None, hasta: str | None = None,
            mercado: str | None = None, version: str | None = None) -> dict:
    """Qué tal lo hace, con todo lo que hace falta para juzgarlo."""
    from .seguro import wilson

    condiciones = ["resuelto = 1"]
    parametros: list = []
    for campo, valor, operador in (("fecha", desde, ">="), ("fecha", hasta, "<="),
                                   ("mercado", mercado, "="), ("version", version, "=")):
        if valor:
            condiciones.append(f"{campo} {operador} ?")
            parametros.append(valor)
    filas = almacen.consulta(
        "SELECT * FROM predicciones WHERE " + " AND ".join(condiciones)
        + " ORDER BY fecha", tuple(parametros))

    if not filas:
        return {"casos": 0, "nota": "Todavía no hay ninguna predicción resuelta. "
                                    "Se apuntan solas cuando la guardia prepara el "
                                    "día, y se resuelven al día siguiente.",
                "pendientes": _pendientes(almacen)}

    aciertos = sum(f["acerto"] for f in filas)
    suelo, techo = wilson(aciertos, len(filas))
    por_mercado = {}
    for nombre in sorted({f["mercado"] for f in filas}):
        suyas = [f for f in filas if f["mercado"] == nombre]
        por_mercado[nombre] = {
            "casos": len(suyas),
            "aciertos": sum(f["acerto"] for f in suyas),
            "brier": brier(suyas),
            "probabilidad_media": round(
                sum(f["probabilidad"] for f in suyas) / len(suyas), 4),
        }
    return {
        "casos": len(filas),
        "desde": filas[0]["fecha"], "hasta": filas[-1]["fecha"],
        "aciertos": aciertos,
        "acierto": round(aciertos / len(filas), 4),
        "acierto_suelo": round(suelo, 4), "acierto_techo": round(techo, 4),
        "brier": brier(filas),
        # La referencia honesta: lo que saca quien dice 50 % a todo. Un Brier
        # suelto no significa nada.
        "brier_de_no_saber_nada": 0.25,
        "log_loss": log_loss(filas),
        "calibracion": calibracion(filas),
        "clv": _clv(filas),
        "por_mercado": por_mercado,
        "contra_el_mercado": _contra_el_mercado(filas),
        "suficiente": len(filas) >= MINIMO_PARA_JUZGAR,
        "pendientes": _pendientes(almacen),
        "como_leerlo": (
            "Primero la calibración: de las veces que dijo 70 %, ¿pasó el 70 %? "
            f"Después el Brier contra 0,25, que es lo que saca quien no sabe nada. "
            f"El acierto es lo último y va con su intervalo. Con menos de "
            f"{MINIMO_PARA_JUZGAR} casos resueltos esto es un indicio, no un juicio."),
        "lo_que_no_dice": (
            "Esto mide si el cálculo describe bien el fútbol, no si algo es "
            "rentable: aquí no hay cuotas jugadas, ni unidades, ni ROI. Y se mide "
            "sobre los partidos que tú barres, que no son una muestra del fútbol."),
    }


def _pendientes(almacen: Almacen) -> dict:
    filas = almacen.consulta(
        "SELECT COUNT(*) AS n FROM predicciones WHERE resuelto = 0")
    return {"sin_resolver": filas[0]["n"] if filas else 0}


def _clv(filas: list[dict]) -> dict:
    """Cuánto se movió el mercado hacia donde decíamos, cuando se puede saber."""
    con_las_dos = [f for f in filas
                   if f["prob_mercado"] is not None and f["prob_cierre"] is not None]
    if not con_las_dos:
        return {"casos": 0,
                "nota": "Hacen falta las cuotas de cuando se predijo y las últimas "
                        "vistas. Rellena cuotas en Memoria para tenerlas."}
    movimientos = [f["prob_cierre"] - f["prob_mercado"] for f in con_las_dos]
    a_favor = sum(1 for f, m in zip(con_las_dos, movimientos, strict=True)
                  if (f["probabilidad"] > f["prob_mercado"]) == (m > 0) and m != 0)
    return {
        "casos": len(con_las_dos),
        "movimiento_medio": round(sum(movimientos) / len(movimientos), 4),
        "veces_a_favor": a_favor,
        "proporcion_a_favor": round(a_favor / len(con_las_dos), 4),
        "lectura": (
            "Cuando decíamos que algo valía más de lo que pagaba el mercado, "
            f"el mercado se movió hacia nosotros {a_favor} de {len(con_las_dos)} "
            "veces. Por encima de la mitad es la única señal de ventaja que no "
            "depende de haber acertado."),
    }


def _contra_el_mercado(filas: list[dict]) -> dict:
    """El cálculo contra el mercado, en el único sitio donde se pueden comparar."""
    comparables = [f for f in filas if f["prob_mercado"] is not None]
    if not comparables:
        return {"casos": 0, "nota": "Sin cuotas guardadas no hay con qué comparar."}
    nuestro = brier(comparables)
    suyo = round(sum((f["prob_mercado"] - f["acerto"]) ** 2
                     for f in comparables) / len(comparables), 4)
    return {
        "casos": len(comparables),
        "brier_nuestro": nuestro, "brier_del_mercado": suyo,
        "diferencia": round((suyo or 0) - (nuestro or 0), 4),
        "lectura": ("El cálculo gana al mercado en estos casos."
                    if (nuestro or 1) < suyo else
                    "El mercado gana al cálculo, que es lo normal y lo esperable."),
    }


# -------------------------------------------------------------------- texto

def texto(datos: dict, ancho: int = 72) -> list[str]:
    """El balance en palabras, para el terminal y para el bot."""
    if not datos.get("casos"):
        return [datos.get("nota", "Sin datos.")]
    lineas = [
        f"Registro · {datos['casos']} predicciones resueltas "
        f"({datos['desde']} → {datos['hasta']})",
        "",
        "Calibración (de las veces que dijo X, pasó Y):",
    ]
    for tramo in datos["calibracion"]:
        flecha = "→" if abs(tramo["desvio"]) < 0.05 else ("↑" if tramo["desvio"] > 0
                                                          else "↓")
        lineas.append(f"  {tramo['tramo']:>9}  dijo {tramo['dijiste']:.0%}  "
                      f"{flecha}  pasó {tramo['paso']:.0%}   ({tramo['casos']} casos)")
    lineas += [
        "",
        f"Brier: {datos['brier']} (quien no sabe nada saca 0.25)",
        f"Log loss: {datos['log_loss']}",
        f"Acierto: {datos['acierto']:.0%} "
        f"({datos['aciertos']}/{datos['casos']}, "
        f"entre {datos['acierto_suelo']:.0%} y {datos['acierto_techo']:.0%})",
    ]
    contra = datos.get("contra_el_mercado") or {}
    if contra.get("casos"):
        lineas.append(f"Contra el mercado: {contra['brier_nuestro']} nuestro contra "
                      f"{contra['brier_del_mercado']} suyo ({contra['casos']} casos)")
    clv = datos.get("clv") or {}
    if clv.get("casos"):
        lineas.append(f"CLV: el mercado se movió hacia nosotros "
                      f"{clv['veces_a_favor']} de {clv['casos']} veces")
    if not datos.get("suficiente"):
        lineas += ["", f"⚠ Con {datos['casos']} casos esto es un indicio, no un "
                       f"juicio: hacen falta {MINIMO_PARA_JUZGAR}."]
    del ancho
    return lineas


__all__ = ["MERCADOS", "MINIMO_PARA_JUZGAR", "TRAMOS", "VERSION_MODELO", "anotar",
           "balance", "brier", "calibracion", "log_loss", "resolver", "texto"]
