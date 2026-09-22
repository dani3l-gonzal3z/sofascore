"""Todos los mercados de un partido, no solo el 1X2, y con su historia.

Hasta aquí de las cuotas se guardaba el 1X2 y nada más, en **una fila por
partido que se sobrescribía**: la de apertura y la de cierre eran la misma fila,
y la primera se perdía. Con eso no se puede saber hacia dónde se ha movido el
mercado, ni medir el cierre contra lo que dijimos, ni comparar nada que no sea
quién gana.

Esto guarda **cada mercado, cada casa y cada vez que se mira**:

    1x2 · doble oportunidad · más/menos goles (cada línea) · marcan los dos ·
    hándicap asiático · córners · tarjetas · primera parte · **marcador exacto**

y lo deja en un formato largo —una fila por selección— que entiende el resto del
programa sin saber de qué casa vino.

El marcador exacto es el mercado más interesante de todos: es la distribución
completa de lo que el mercado cree que va a pasar. Con ella se ve **qué
resultados** cree más probables, y se puede medir contra la nuestra partido a
partido. Ver :func:`distribucion_de_marcadores`.

Sobre quitar el margen. Una casa cobra repartiendo su margen entre todas las
selecciones, pero no a partes iguales: carga más a las improbables (el sesgo del
favorito). En un 1X2 da casi igual cómo se quite; en un marcador exacto con
veinte resultados, no. Por eso aquí hay dos métodos, y el de potencia es el que
se usa cuando hay muchas selecciones.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .cuotas import fraccion_a_decimal

#: Nombres de mercado de Sofascore → nombre corto nuestro. Lo que no esté aquí
#: se guarda igual, con su nombre convertido en clave: no se tira nada que la
#: fuente mande, solo se deja de entender.
MERCADOS_SOFASCORE = {
    "full time": "1x2",
    "1x2": "1x2",
    "match winner": "1x2",
    "double chance": "doble_oportunidad",
    "1st half": "1x2_primera_parte",
    "first half": "1x2_primera_parte",
    "draw no bet": "empate_no_accion",
    "both teams to score": "ambos_marcan",
    "match goals": "goles",
    "total goals": "goles",
    "asian handicap": "handicap_asiatico",
    "corners 2-way": "corners",
    "match corners": "corners",
    "total corners": "corners",
    "cards in match": "tarjetas",
    "total cards": "tarjetas",
    "correct score": "marcador",
    "first team to score": "primero_en_marcar",
    "half time/full time": "descanso_final",
}

#: Y las selecciones, para que «Over», «O» y «Más de» sean lo mismo.
SELECCIONES = {
    "1": "local", "x": "empate", "2": "visitante",
    "home": "local", "draw": "empate", "away": "visitante",
    "1x": "1x", "x2": "x2", "12": "12",
    "yes": "si", "no": "no",
    "over": "mas", "under": "menos",
}

#: Por encima de estas selecciones, el margen se quita con el método de
#: potencia. En un 1X2 los dos métodos dan casi lo mismo; en un marcador exacto
#: el proporcional infla los resultados raros y desinfla los probables.
MUCHAS_SELECCIONES = 4

_MARCADOR = re.compile(r"^\s*(\d{1,2})\s*[-:]\s*(\d{1,2})\s*$")


def clave(texto: Any) -> str:
    """Un nombre de mercado cualquiera convertido en clave estable."""
    plano = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore")
    return re.sub(r"[^a-z0-9]+", "_", plano.decode().lower()).strip("_")


def seleccion(texto: Any) -> str:
    """El nombre de una selección, normalizado. Un marcador queda como «2-1»."""
    crudo = str(texto or "").strip()
    marcador = _MARCADOR.match(crudo)
    if marcador:
        return f"{int(marcador.group(1))}-{int(marcador.group(2))}"
    return SELECCIONES.get(crudo.lower(), clave(crudo))


# ------------------------------------------------------------------- leerlos

def de_sofascore(datos: Any) -> list[dict]:
    """Todas las selecciones de una respuesta de Sofascore, en formato largo.

    Acepta ``odds/1/all`` (``{"markets": [...]}``) y ``odds/1/featured``. De cada
    selección se guarda la cuota de ahora **y la de apertura**, que Sofascore
    manda en la misma respuesta y hasta ahora se tiraba: con las dos se ve hacia
    dónde se ha movido el mercado sin tener que haber mirado antes.
    """
    mercados = []
    if isinstance(datos, dict):
        if isinstance(datos.get("markets"), list):
            mercados = datos["markets"]
        elif isinstance(datos.get("featured"), dict):
            mercados = [m for m in datos["featured"].values() if isinstance(m, dict)]
        elif "choices" in datos:
            mercados = [datos]
    filas = []
    for mercado in mercados:
        if not isinstance(mercado, dict) or mercado.get("isLive"):
            continue
        nombre = str(mercado.get("marketName") or "")
        suyo = MERCADOS_SOFASCORE.get(nombre.strip().lower(), clave(nombre))
        linea = str(mercado.get("choiceGroup") or "").strip()
        casa = f"sofascore#{mercado.get('sourceId') or 1}"
        for eleccion in mercado.get("choices") or []:
            cuota = fraccion_a_decimal(eleccion.get("fractionalValue"))
            if not cuota or cuota <= 1:
                continue
            filas.append({
                "casa": casa, "mercado": suyo, "linea": linea,
                "seleccion": seleccion(eleccion.get("name")),
                "cuota": round(cuota, 3),
                "cuota_inicial": _redondea(fraccion_a_decimal(
                    eleccion.get("initialFractionalValue"))),
                "suspendido": bool(mercado.get("suspended")),
            })
    return con_probabilidades(filas)


def _redondea(valor: float | None) -> float | None:
    return round(valor, 3) if valor else None


# --------------------------------------------------------------- el margen

def sin_margen(cuotas: dict[str, float], metodo: str = "") -> dict[str, float]:
    """Las probabilidades de un mercado, quitándole el margen de la casa.

    ``metodo`` vacío decide solo: proporcional con pocas selecciones y de
    potencia con muchas. El de potencia busca el exponente ``k`` que hace que
    ``Σ (1/cuota)^k = 1``; como una potencia mayor que uno aplasta más lo pequeño
    que lo grande, le quita más margen a los resultados raros, que es donde la
    casa lo carga.
    """
    implicitas = {s: 1 / c for s, c in cuotas.items() if c and c > 1}
    if not implicitas:
        return {}
    metodo = metodo or ("potencia" if len(implicitas) > MUCHAS_SELECCIONES
                        else "proporcional")
    suma = sum(implicitas.values())
    if metodo == "proporcional" or suma <= 1:
        return {s: p / suma for s, p in implicitas.items()}
    abajo, arriba = 1.0, 10.0
    for _ in range(60):
        k = (abajo + arriba) / 2
        if sum(p ** k for p in implicitas.values()) > 1:
            abajo = k
        else:
            arriba = k
    k = (abajo + arriba) / 2
    crudas = {s: p ** k for s, p in implicitas.items()}
    total = sum(crudas.values())
    return {s: p / total for s, p in crudas.items()}


def margen(cuotas: dict[str, float]) -> float | None:
    """Lo que se queda la casa en ese mercado: 0,05 es un 5 %."""
    implicitas = [1 / c for c in cuotas.values() if c and c > 1]
    return round(sum(implicitas) - 1, 4) if implicitas else None


def con_probabilidades(filas: list[dict]) -> list[dict]:
    """Le pone a cada fila su probabilidad sin margen, dentro de su mercado.

    El «mercado» a efectos del margen es la casa + el mercado + la línea: el
    más/menos 2,5 de una casa es un mercado, y su más/menos 3,5 es otro.
    """
    grupos: dict[tuple, list[dict]] = {}
    for fila in filas:
        grupos.setdefault((fila["casa"], fila["mercado"], fila["linea"]), []).append(fila)
    for grupo in grupos.values():
        probs = sin_margen({f["seleccion"]: f["cuota"] for f in grupo})
        cobra = margen({f["seleccion"]: f["cuota"] for f in grupo})
        for fila in grupo:
            fila["prob"] = round(probs.get(fila["seleccion"], 0.0), 5) or None
            fila["margen"] = cobra
    return filas


# --------------------------------------------------------- el marcador exacto

def distribucion_de_marcadores(filas: list[dict], casa: str | None = None) -> dict:
    """Lo que el mercado cree de cada marcador, sin margen.

    Las casas suelen cerrar el mercado con «cualquier otro resultado»: esa
    probabilidad se enseña aparte, porque repartirla entre marcadores concretos
    sería inventarse a cuál va.
    """
    suyas = [f for f in filas if f.get("mercado") == "marcador"
             and (casa is None or f.get("casa") == casa)]
    if not suyas:
        return {"disponible": False,
                "nota": "Esta casa no tiene mercado de marcador exacto para este "
                        "partido, o no se ha pedido todavía."}
    # Si hay varias casas, se queda con la que más resultados cubre.
    por_casa: dict[str, list[dict]] = {}
    for fila in suyas:
        por_casa.setdefault(fila["casa"], []).append(fila)
    elegida = max(por_casa, key=lambda c: len(por_casa[c]))
    probs = sin_margen({f["seleccion"]: f["cuota"] for f in por_casa[elegida]})
    marcadores = {s: p for s, p in probs.items() if _MARCADOR.match(s)}
    otros = sum(p for s, p in probs.items() if not _MARCADOR.match(s))
    return {
        "disponible": True, "casa": elegida,
        "marcadores": dict(sorted(marcadores.items(), key=lambda x: -x[1])),
        "otros": round(otros, 4),
        "margen": margen({f["seleccion"]: f["cuota"] for f in por_casa[elegida]}),
    }


def comparar_marcadores(nuestra: dict[str, float], suya: dict[str, float],
                        cuantos: int = 6) -> dict:
    """Nuestra distribución de marcadores contra la del mercado, en un partido.

    Se enseñan las dos listas de los más probables y **dónde discrepan más**,
    que es lo que interesa: si los dos dicen que el 1-1 es lo más probable, eso
    no dice nada; si nosotros le damos al 2-0 el doble que el mercado, eso sí.
    """
    todos = set(nuestra) | set(suya)
    diferencias = sorted(
        ({"marcador": m, "nuestra": round(nuestra.get(m, 0.0), 4),
          "mercado": round(suya.get(m, 0.0), 4),
          "diferencia": round(nuestra.get(m, 0.0) - suya.get(m, 0.0), 4)}
         for m in todos),
        key=lambda d: -abs(d["diferencia"]))
    arriba_nuestro = sorted(nuestra, key=lambda m: -nuestra[m])[:cuantos]
    arriba_suyo = sorted(suya, key=lambda m: -suya[m])[:cuantos]
    # Distancia de Hellinger: 0 es que dicen lo mismo, 1 que no se parecen nada.
    hellinger = (sum((nuestra.get(m, 0.0) ** 0.5 - suya.get(m, 0.0) ** 0.5) ** 2
                     for m in todos) / 2) ** 0.5
    return {
        "mas_probables_nuestros": [(m, round(nuestra[m], 4)) for m in arriba_nuestro],
        "mas_probables_mercado": [(m, round(suya[m], 4)) for m in arriba_suyo],
        "coinciden_en_el_primero": bool(arriba_nuestro and arriba_suyo
                                        and arriba_nuestro[0] == arriba_suyo[0]),
        "donde_discrepan": diferencias[:cuantos],
        "distancia": round(hellinger, 4),
    }


# ------------------------------------------------------------- refrescarlos

#: Cada cuánto se vuelve a mirar el mercado, según lo que falte para el saque.
#: Lejos del partido las cuotas apenas se mueven; en las últimas horas es cuando
#: entran las alineaciones y el dinero de verdad, y cuando el precio dice más.
CADA_CUANTO = ((3, 0.25), (24, 1.0), (72, 6.0), (10_000, 12.0))


def toca_refrescar(almacen, partido_id: int, horas_hasta: float | None) -> bool:
    """¿Hace falta volver a pedir el mercado de este partido?

    Antes la respuesta era «nunca»: si había cuotas guardadas, se usaban, y un
    partido visto tres días antes se quedaba con la cuota de apertura hasta el
    saque. El mercado del briefing estaba viejo, y el «cierre» con el que se mide
    si acertamos antes que el mercado, también.
    """
    if horas_hasta is not None and horas_hasta < -2:
        return False          # ya se ha jugado: lo último que hay es el cierre
    filas = almacen.consulta(
        "SELECT MAX(visto_en) AS ultima FROM cuotas_mercado WHERE partido_id = ?",
        (partido_id,))
    ultima = filas[0]["ultima"] if filas else None
    if not ultima:
        return True
    from datetime import datetime, timezone

    hace = (datetime.now(timezone.utc)
            - datetime.fromisoformat(ultima)).total_seconds() / 3600
    falta = horas_hasta if horas_hasta is not None else 10_000
    limite = next(cada for hasta, cada in CADA_CUANTO if falta <= hasta)
    return hace >= limite


def refrescar(cliente, almacen, evento, forzar: bool = False) -> dict:
    """Pide todos los mercados de un partido y guarda la foto, si toca.

    Guarda también el 1X2 en la tabla vieja de `cuotas`, para que todo lo que ya
    la lee —la previa, el pronóstico, el registro— tenga el precio de ahora y no
    el del primer día que se miró.
    """
    from .errors import SofascoreError

    horas = None
    if getattr(evento, "start_timestamp", None):
        from datetime import datetime, timezone

        horas = (evento.start_timestamp - datetime.now(timezone.utc).timestamp()) / 3600
    if not forzar and not toca_refrescar(almacen, evento.id, horas):
        return {"refrescado": False, "motivo": "reciente"}
    crudo = None
    for seccion in ("odds", "odds_featured"):
        try:
            crudo = cliente.section(seccion, evento.id, ttl=600)
        except SofascoreError:
            continue
        if crudo:
            break
    filas = de_sofascore(crudo)
    if not filas:
        return {"refrescado": False, "motivo": "la fuente no trae cuotas"}
    almacen.guardar_evento(evento)
    guardadas = almacen.guardar_mercados(evento.id, filas, fuente="sofascore")
    almacen.guardar_cuotas(evento.id, crudo)
    almacen._conexion.commit()
    return {"refrescado": True, "filas": guardadas,
            "mercados": sorted({f["mercado"] for f in filas})}


# ----------------------------------------------------- nosotros contra ellos

#: Los sucesos que se comparan, con cómo se llaman en cada lado: (etiqueta,
#: dónde está en nuestro pronóstico, (mercado, línea, selección) en las casas).
COMPARABLES = (
    ("Gana el local", ("1x2", "local"), ("1x2", "", "local")),
    ("Empate", ("1x2", "empate"), ("1x2", "", "empate")),
    ("Gana el visitante", ("1x2", "visitante"), ("1x2", "", "visitante")),
    ("Más de 2,5 goles", ("mas_de", "2.5"), ("goles", "2.5", "mas")),
    ("Marcan los dos", ("ambos_marcan", None), ("ambos_marcan", "", "si")),
    ("Más de 9,5 córners", ("corners", "9.5"), ("corners", "9.5", "mas")),
    ("Más de 3,5 tarjetas", ("tarjetas", "3.5"), ("tarjetas", "3.5", "mas")),
)

#: A partir de esta diferencia entre lo nuestro y lo del mercado se marca como
#: discrepancia. Por debajo es ruido: ni nuestro modelo ni el mercado aciertan al
#: punto porcentual.
DISCREPANCIA = 0.05


def _nuestro(pronostico: dict, donde: tuple) -> float | None:
    goles = pronostico.get("goles") or {}
    bloque, clave_ = donde
    if bloque == "1x2":
        return (goles.get("1x2") or {}).get(clave_)
    if bloque == "mas_de":
        return (goles.get("mas_de") or {}).get(clave_)
    if bloque == "ambos_marcan":
        return goles.get("ambos_marcan")
    otro = pronostico.get(bloque) or {}
    if otro.get("disponible"):
        return (otro.get("mas_de") or {}).get(clave_)
    return None


def frente_al_mercado(almacen, partido_id: int, pronostico: dict | None = None) -> dict:
    """Todo lo que dice el mercado de un partido, al lado de lo que decimos nosotros.

    De cada suceso se coge la casa que menos cobra, que es la que más se acerca a
    lo que el mercado de verdad cree. Se enseña su margen y cuántas casas hay,
    porque un precio de una sola casa con un 9 % de margen no dice lo mismo que el
    de cinco casas con un 3 %.
    """
    filas = almacen.mercados_de(partido_id)
    if not filas:
        return {"disponible": False,
                "nota": "No hay cuotas guardadas de este partido todavía."}
    mejor: dict[tuple, dict] = {}
    casas: dict[tuple, set] = {}
    for fila in filas:
        llave = (fila["mercado"], fila["linea"], fila["seleccion"])
        casas.setdefault(llave, set()).add(fila["casa"])
        if llave not in mejor or (fila["margen"] or 9) < (mejor[llave]["margen"] or 9):
            mejor[llave] = fila

    sucesos = []
    for etiqueta, en_nuestro, en_casa in COMPARABLES:
        suya = mejor.get(en_casa)
        nuestra = _nuestro(pronostico or {}, en_nuestro)
        if not suya and nuestra is None:
            continue
        diferencia = (round(nuestra - suya["prob"], 4)
                      if suya and suya.get("prob") and nuestra is not None else None)
        sucesos.append({
            "suceso": etiqueta,
            "nuestra": round(nuestra, 4) if nuestra is not None else None,
            "mercado": round(suya["prob"], 4) if suya and suya.get("prob") else None,
            "cuota": suya["cuota"] if suya else None,
            "casa": suya["casa"] if suya else None,
            "casas": len(casas.get(en_casa, ())),
            "diferencia": diferencia,
            "discrepa": diferencia is not None and abs(diferencia) >= DISCREPANCIA,
        })

    exacto = distribucion_de_marcadores(filas)
    marcadores = None
    nuestros = ((pronostico or {}).get("goles") or {}).get("todos_los_marcadores")
    if exacto.get("disponible") and nuestros:
        marcadores = {**comparar_marcadores(nuestros, exacto["marcadores"]),
                      "casa": exacto["casa"], "margen": exacto["margen"],
                      "otros_mercado": exacto["otros"]}
    return {
        "disponible": True,
        "sucesos": sucesos,
        "movimiento": almacen.movimiento_de(partido_id),
        "marcador_exacto": marcadores or exacto,
        "casas": sorted({f["casa"] for f in filas}),
        "visto_en": max(f["visto_en"] for f in filas),
        "como_leerlo": (
            "De cada suceso, el precio de la casa que menos cobra y su probabilidad "
            "ya sin margen. Donde nuestro número se separa del mercado más de cinco "
            "puntos se marca: ahí o sabemos algo que el mercado no, o —más a "
            "menudo— al revés. El registro dirá cuál de las dos con el tiempo."),
    }


__all__ = ["CADA_CUANTO", "COMPARABLES", "MERCADOS_SOFASCORE", "clave",
           "comparar_marcadores", "frente_al_mercado",
           "con_probabilidades", "de_sofascore", "distribucion_de_marcadores",
           "margen", "refrescar", "seleccion", "sin_margen", "toca_refrescar"]
