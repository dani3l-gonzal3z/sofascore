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

#: Los dos concursantes que no son agentes. El cálculo es el Poisson de
#: siempre; el mercado son las cuotas. Están para que se pueda saber si un
#: agente aporta algo: sin ellos se corona al mejor de varios malos.
#:
#: Sin tilde, y esto no es descuido. Un autor viaja por `--autor` en el terminal,
#: por `?autor=` en una petición, por una orden del bot y por JavaScript, y la
#: comparación de SQLite es byte a byte: `'cálculo' = 'calculo'` da **falso**.
#: Quien escribiera `cancha resultados --autor calculo` se llevaría cero filas y
#: ninguna explicación, y dos formas Unicode de la misma tilde se ven iguales y
#: no lo son. Lo que se guarda es un nombre corto de teclado; lo que se lee en
#: pantalla sale de `NOMBRES_DE_AUTOR`.
AUTOR_CALCULO = "calculo"
AUTOR_MERCADO = "mercado"

#: Cómo se llaman los concursantes fijos cuando hay que enseñarlos. Un agente se
#: llama como lo haya llamado su dueño, así que no está aquí.
NOMBRES_DE_AUTOR = {AUTOR_CALCULO: "el cálculo", AUTOR_MERCADO: "el mercado"}


def nombre_de_autor(autor: str) -> str:
    """Cómo se enseña un autor. Los fijos tienen nombre; un agente es su clave."""
    return NOMBRES_DE_AUTOR.get(autor, autor)


def anotar(almacen: Almacen, partido: Any, pronostico: dict | None = None,
           cliente=None, version: str = VERSION_MODELO,
           autor: str = AUTOR_CALCULO, con_mercado: bool = True,
           probabilidades: dict | None = None) -> dict:
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
    filas = (list(_de_un_dict(probabilidades, mercado)) if probabilidades is not None
             else list(_del_pronostico(datos, mercado)))
    guardadas = 0
    for mercado_nombre, seleccion, probabilidad, prob_mercado in filas:
        guardadas += _insertar(almacen, evento, autor, mercado_nombre, seleccion,
                               probabilidad, prob_mercado, horas, version)

    # El mercado, apuntado como un concursante más. Es gratis —las cuotas ya
    # están— y es el listón contra el que se mide todo lo demás. Solo se apunta
    # una vez por partido, no una por cada agente que opine.
    del_mercado = 0
    if con_mercado and mercado:
        for lado in ("local", "empate", "visitante"):
            valor = _sacar(mercado, lado)
            if valor is not None:
                del_mercado += _insertar(almacen, evento, AUTOR_MERCADO, "1x2", lado,
                                         valor, valor, horas, "cuotas")
    almacen._conexion.commit()
    return {"partido_id": evento.id, "fecha": evento.date, "autor": autor,
            "guardadas": guardadas, "ya_estaban": len(filas) - guardadas,
            "del_mercado": del_mercado, "version": version, "horas_antes": horas}


def _de_un_dict(probabilidades: dict, mercado: dict):
    """Las predicciones que vienen ya dadas —las de un agente— validadas.

    Un agente contesta con un JSON; aquí se comprueba que lo que dice sean
    probabilidades y no cualquier cosa. Lo que no cuadre se descarta en vez de
    guardarse: una fila con un 1,4 de probabilidad envenena la calibración de
    todo el registro, y además no se ve venir.
    """
    uno = (probabilidades.get("1x2") or {})
    en_porcentaje = _son_porcentajes(uno)
    for lado in ("local", "empate", "visitante"):
        valor = _probabilidad(uno.get(lado), en_porcentaje)
        if valor is not None:
            yield "1x2", lado, valor, _sacar(mercado, lado)
    for clave, seleccion in (("mas_2_5", "si"), ("ambos_marcan", "si"),
                             ("corners", "mas_9_5"), ("tarjetas", "mas_3_5")):
        valor = _probabilidad(probabilidades.get(clave), en_porcentaje)
        if valor is not None:
            yield clave, seleccion, valor, None
    marcador = probabilidades.get("marcador") or {}
    if isinstance(marcador, dict):
        cual = str(marcador.get("marcador") or "").strip()
        valor = _probabilidad(marcador.get("probabilidad"), en_porcentaje)
        if cual and valor is not None:
            yield "marcador", cual, valor, None


def _son_porcentajes(uno_x_dos: dict) -> bool:
    """¿Escribe este agente 55 o 0,55? Se decide por la suma del 1X2.

    Es la única señal que no es ambigua. Mirar un número suelto no vale: un 1,4
    puede ser «1,4 %» o una probabilidad mal escrita, y tratarlo como lo primero
    convierte un disparate en un 0,014 que parece razonable y se cuela.
    """
    numeros = [float(v) for v in (uno_x_dos or {}).values()
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return len(numeros) == 3 and 80 <= sum(numeros) <= 120


def _probabilidad(valor: Any, en_porcentaje: bool = False) -> float | None:
    """Un número entre 0 y 1, o nada."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    numero = float(valor) / 100 if en_porcentaje else float(valor)
    return round(numero, 6) if 0 <= numero <= 1 else None


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


def _insertar(almacen: Almacen, evento, autor: str, mercado: str, seleccion: str,
              probabilidad: float, prob_mercado: float | None,
              horas: float | None, version: str) -> int:
    cursor = almacen._conexion.execute(
        """INSERT OR IGNORE INTO predicciones
           (partido_id, fecha, horas_antes, version, autor, mercado, seleccion,
            probabilidad, prob_mercado)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (evento.id, evento.date, horas, version, autor, mercado, seleccion,
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
            mercado: str | None = None, version: str | None = None,
            autor: str | None = None) -> dict:
    """Qué tal lo hace, con todo lo que hace falta para juzgarlo."""
    from .seguro import wilson

    condiciones = ["resuelto = 1"]
    parametros: list = []
    for campo, valor, operador in (("fecha", desde, ">="), ("fecha", hasta, "<="),
                                   ("mercado", mercado, "="), ("version", version, "="),
                                   ("autor", autor, "=")):
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
        "autor": autor,
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


def tabla(almacen: Almacen, desde: str | None = None, hasta: str | None = None,
          minimo: int = MINIMO_PARA_JUZGAR) -> dict:
    """La clasificación: quién predice mejor, y contra qué.

    **Ordena por la ventaja sobre el mercado, no por el Brier a secas**, y el
    motivo importa: un Brier bueno se puede conseguir prediciendo solo partidos
    fáciles. Si un agente solo opina de favoritos claros, acertará mucho y su
    Brier será estupendo sin haber aportado nada. Comparándolo con lo que decía
    el mercado **en esos mismos partidos**, la dificultad se cancela y lo que
    queda es el agente.

    Quien no llegue a ``minimo`` casos resueltos sale aparte, en «todavía sin
    muestra». No es un adorno: con veinte predicciones, el orden de una tabla
    así es casi todo azar.
    """
    autores = [f["autor"] for f in almacen.consulta(
        "SELECT DISTINCT autor FROM predicciones WHERE resuelto = 1 ORDER BY autor")]
    clasificados, sin_muestra = [], []
    for autor in autores:
        suyo = balance(almacen, desde=desde, hasta=hasta, autor=autor)
        if not suyo.get("casos"):
            continue
        contra = suyo.get("contra_el_mercado") or {}
        fila = {
            "autor": autor,
            "casos": suyo["casos"],
            "brier": suyo["brier"],
            "log_loss": suyo["log_loss"],
            "acierto": suyo["acierto"],
            "desvio_de_calibracion": _desvio(suyo["calibracion"]),
            "ventaja_sobre_el_mercado": contra.get("diferencia"),
            "casos_comparables": contra.get("casos", 0),
            "clv": (suyo.get("clv") or {}).get("proporcion_a_favor"),
            "desde": suyo["desde"], "hasta": suyo["hasta"],
            **_a_que_distancia(almacen, autor, desde, hasta),
        }
        (clasificados if suyo["casos"] >= minimo else sin_muestra).append(fila)

    # Los que no se pueden comparar con el mercado van al final, no primeros por
    # tener un None: no haber podido medirse no es una ventaja.
    clasificados.sort(key=lambda f: (f["ventaja_sobre_el_mercado"] is None,
                                     -(f["ventaja_sobre_el_mercado"] or 0)))
    sin_muestra.sort(key=lambda f: -f["casos"])
    return {
        "clasificacion": clasificados,
        "todavia_sin_muestra": sin_muestra,
        "minimo": minimo,
        "como_leerlo": (
            "Ordena la ventaja sobre el mercado: cuánto mejor es su Brier que el "
            "de las cuotas en los mismos partidos. Positivo es ganarle al mercado, "
            "y es raro. El Brier suelto engaña —se mejora prediciendo solo partidos "
            f"fáciles—, y el acierto más todavía. Con menos de {minimo} casos "
            "resueltos nadie entra en la tabla."),
        "avisos": _avisos_de_la_tabla(clasificados + sin_muestra),
    }


def _a_que_distancia(almacen: Almacen, autor: str, desde: str | None,
                     hasta: str | None) -> dict:
    """Dos cifras que dicen si la fila de arriba significa algo.

    `distancia_al_mercado` es la media de |la suya − la del mercado|. No la pide
    nadie y es la más valiosa de la tabla: el expediente **le enseña las cuotas**,
    así que un agente puede limitarse a repetirlas y salir clasificado. Con una
    distancia de 0,01 lo que la tabla mide no es quién analiza mejor, es quién
    copia mejor.

    `horas_antes_media` es la otra trampa, y es de fábrica: el cálculo se apunta
    en la guardia de las tres de la mañana y un agente se corre a mano, a lo mejor
    media hora antes del saque. El que llega tarde tiene **más información**, no
    más talento, y sin esta columna la tabla premia eso.
    """
    filas = almacen.consulta(
        "SELECT probabilidad, prob_mercado, horas_antes FROM predicciones "
        "WHERE autor = ? AND resuelto = 1"
        + (" AND fecha >= ?" if desde else "") + (" AND fecha <= ?" if hasta else ""),
        tuple([autor] + [x for x in (desde, hasta) if x]))
    distancias = [abs(f["probabilidad"] - f["prob_mercado"]) for f in filas
                  if f["prob_mercado"] is not None]
    horas = [f["horas_antes"] for f in filas if f["horas_antes"] is not None]
    return {
        "distancia_al_mercado": round(sum(distancias) / len(distancias), 4)
                                if distancias else None,
        "horas_antes_media": round(sum(horas) / len(horas), 1) if horas else None,
    }


#: Por debajo de esta distancia media al mercado, un autor no está analizando:
#: está copiando el precio con otro decorado.
DISTANCIA_DE_COPIAR = 0.02

#: Y a partir de esta diferencia de horas entre concursantes, la tabla no los está
#: comparando: uno sabía más cosas cuando habló.
HORAS_QUE_DESNIVELAN = 6.0


def _avisos_de_la_tabla(filas: list[dict]) -> list[str]:
    """Lo que hay que decir antes de que alguien se crea el orden de la tabla."""
    avisos = []
    copiones = [nombre_de_autor(f["autor"]) for f in filas
                if f["autor"] != AUTOR_MERCADO
                and f.get("distancia_al_mercado") is not None
                and f["distancia_al_mercado"] < DISTANCIA_DE_COPIAR]
    if copiones:
        avisos.append(
            f"{', '.join(copiones)} apenas se separa del mercado (menos de "
            f"{DISTANCIA_DE_COPIAR:.2f} de media). El expediente le enseña las "
            "cuotas, así que lo más probable es que las esté repitiendo: su puesto "
            "no mide su análisis.")
    horas = [(nombre_de_autor(f["autor"]), f["horas_antes_media"])
             for f in filas
             if f.get("horas_antes_media") is not None]
    if len(horas) > 1:
        pronto = max(horas, key=lambda x: x[1])
        tarde = min(horas, key=lambda x: x[1])
        if pronto[1] - tarde[1] >= HORAS_QUE_DESNIVELAN:
            avisos.append(
                f"{tarde[0]} predice a {tarde[1]:.0f} h del saque y {pronto[0]} a "
                f"{pronto[1]:.0f} h. El que llega más tarde sabe más cosas —quién "
                "juega, cómo se ha movido la cuota—, así que esto no es una "
                "comparación limpia.")
    return avisos


def texto_tabla(datos: dict) -> list[str]:
    """La clasificación en líneas, con las columnas que la hacen honesta."""
    lineas = ["CLASIFICACIÓN", ""]
    filas = datos.get("clasificacion") or []
    if not filas:
        lineas.append(f"Todavía no hay nadie con {datos.get('minimo')} casos "
                      "resueltos, que es lo mínimo para ordenar a alguien.")
    else:
        lineas.append(f"{'#':<3}{'quién':<20}{'casos':>7}{'ventaja':>10}"
                      f"{'brier':>8}{'dist.mdo':>10}{'h.antes':>9}")
        for puesto, fila in enumerate(filas, 1):
            lineas.append(
                f"{puesto:<3}{nombre_de_autor(fila['autor'])[:19]:<20}"
                f"{fila['casos']:>7}"
                f"{_pinta(fila['ventaja_sobre_el_mercado'], '+.2%'):>10}"
                f"{_pinta(fila['brier'], '.4f'):>8}"
                f"{_pinta(fila.get('distancia_al_mercado'), '.3f'):>10}"
                f"{_pinta(fila.get('horas_antes_media'), '.0f'):>9}")
    verdes = datos.get("todavia_sin_muestra") or []
    if verdes:
        lineas += ["", "Todavía sin muestra —se enseñan, pero no tienen puesto:"]
        for fila in verdes:
            faltan = (datos.get("minimo") or 0) - fila["casos"]
            lineas.append(f"    {nombre_de_autor(fila['autor'])}: {fila['casos']} "
                          f"casos, le faltan {faltan}")
    for aviso in datos.get("avisos") or []:
        lineas += ["", f"⚠ {aviso}"]
    return lineas


def _pinta(valor, formato: str) -> str:
    """Un número, o un guion si no hay con qué medirlo. Nunca un cero inventado."""
    return "—" if valor is None else format(valor, formato)


def _desvio(calibracion: list[dict]) -> float | None:
    """Cuánto se aleja la curva de calibración de la diagonal, en media.

    Un número solo para poder ordenar y comparar; la curva entera sigue estando,
    que es donde se ve *dónde* falla: si se pasa de confiado arriba o abajo.
    """
    casos = sum(t["casos"] for t in calibracion)
    if not casos:
        return None
    return round(sum(abs(t["desvio"]) * t["casos"] for t in calibracion) / casos, 4)


def comparar(almacen: Almacen, uno: str, otro: str) -> dict:
    """Dos autores, **sobre los mismos partidos**. Es la comparación que vale.

    Comparar dos balances sueltos es comparar dos exámenes distintos. Esto cruza
    las predicciones por partido, mercado y selección, se queda solo con las que
    hicieron los dos, y ahí sí la diferencia es de ellos y no de a qué partidos
    se presentó cada uno.

    Es lo que contesta «¿el cuaderno de este agente sirve para algo?»: el mismo
    agente con y sin él, sobre los mismos partidos, con el mismo rival enfrente.
    """
    filas = almacen.consulta(
        """SELECT a.mercado, a.seleccion, a.partido_id, a.acerto,
                  a.probabilidad AS p_uno, b.probabilidad AS p_otro
           FROM predicciones a JOIN predicciones b
             ON a.partido_id = b.partido_id AND a.mercado = b.mercado
            AND a.seleccion = b.seleccion
          WHERE a.autor = ? AND b.autor = ? AND a.resuelto = 1 AND b.resuelto = 1""",
        (uno, otro))
    if not filas:
        return {"casos": 0, "uno": uno, "otro": otro,
                "nota": f"«{uno}» y «{otro}» no han predicho todavía nada en común. "
                        "Hasta que no opinen de los mismos partidos, compararlos "
                        "sería comparar dos exámenes distintos."}
    brier_uno = round(sum((f["p_uno"] - f["acerto"]) ** 2 for f in filas) / len(filas), 4)
    brier_otro = round(sum((f["p_otro"] - f["acerto"]) ** 2 for f in filas) / len(filas), 4)
    gana = uno if brier_uno < brier_otro else (otro if brier_otro < brier_uno else "")
    return {
        "uno": uno, "otro": otro, "casos": len(filas),
        "brier_uno": brier_uno, "brier_otro": brier_otro,
        "diferencia": round(brier_otro - brier_uno, 4),
        "gana": gana,
        "suficiente": len(filas) >= MINIMO_PARA_JUZGAR,
        "lectura": (
            f"Sobre los mismos {len(filas)} sucesos: «{uno}» saca {brier_uno} y "
            f"«{otro}», {brier_otro}. " + (f"Gana «{gana}»." if gana else "Empate.")
            + ("" if len(filas) >= MINIMO_PARA_JUZGAR else
               f" Con menos de {MINIMO_PARA_JUZGAR} esto es un indicio, no un juicio.")),
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


__all__ = ["AUTOR_CALCULO", "AUTOR_MERCADO", "MERCADOS", "MINIMO_PARA_JUZGAR",
           "NOMBRES_DE_AUTOR", "TRAMOS", "VERSION_MODELO", "anotar", "balance",
           "brier", "calibracion", "comparar", "log_loss", "nombre_de_autor",
           "resolver", "tabla", "texto",
           "texto_tabla"]
