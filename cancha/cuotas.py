"""Cuotas: lo que el mercado pensaba antes del partido.

No es para apostar. Es para saber **quién era favorito**, que es la variable
que más confunde cualquier análisis de rendimiento: un jugador se mide a
bloques bajos sobre todo cuando su equipo es favorito, y a presiones altas
cuando no lo es. Sin esto, «rinde peor contra bloque bajo» y «rinde peor
cuando su equipo es favorito» son la misma frase dicha de dos formas.

Las cuotas se convierten a probabilidades **quitando el margen** de la casa:
tres cuotas de 2.00 no son un 50 % cada una, son un 33 %. Lo que queda es la
estimación del mercado, que es la mejor previsión pública que existe de un
partido, mejor que cualquier Elo.

Sofascore las sirve en ``/event/{id}/odds/1/featured`` (el mercado principal)
y en ``/event/{id}/odds/1/all``. Las dos vienen en formato fraccionario
(``13/10``), que aquí se traduce.
"""

from __future__ import annotations

from typing import Any

#: A partir de qué probabilidad un equipo cuenta como favorito.
UMBRAL_FAVORITO = 0.45
#: Y a partir de cuál es un favorito claro.
UMBRAL_CLARO = 0.60

NOMBRES_1X2 = {"1": "local", "X": "empate", "2": "visitante"}


def fraccion_a_decimal(texto: Any) -> float | None:
    """``"13/10"`` → ``2.3``. Una cuota decimal (``2.3``) se devuelve tal cual."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 1 else None
    partes = str(texto).strip().split("/")
    try:
        if len(partes) == 2:
            numerador, denominador = float(partes[0]), float(partes[1])
            if denominador <= 0:
                return None
            return round(1 + numerador / denominador, 4)
        valor = float(partes[0])
        return valor if valor > 1 else None
    except ValueError:
        return None


def probabilidades(cuotas: dict[str, float | None]) -> dict[str, float]:
    """Probabilidades implícitas sin el margen de la casa.

    La probabilidad bruta de cada resultado es ``1/cuota``; las tres suman más
    de uno (ese exceso es lo que gana la casa), así que se reparte a
    prorrata. Es el método más simple y para lo que esto se usa —saber quién
    era favorito— es más que suficiente.
    """
    brutas = {k: 1 / v for k, v in cuotas.items() if v and v > 1}
    total = sum(brutas.values())
    if not brutas or total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in brutas.items()}


def extraer_1x2(datos: Any) -> dict | None:
    """Saca el mercado 1X2 de lo que devuelve la API, venga como venga.

    Acepta la respuesta de ``odds/1/featured`` (``{"featured": {"default":
    {...}}}``), la de ``odds/1/all`` (``{"markets": [...]}``) o un mercado
    suelto. Devuelve ``None`` si no encuentra un 1X2 con sus tres cuotas.
    """
    for mercado in _mercados(datos):
        elecciones = mercado.get("choices") or []
        cuotas: dict[str, float | None] = {}
        for eleccion in elecciones:
            lado = NOMBRES_1X2.get(str(eleccion.get("name", "")).strip().upper())
            if lado:
                cuotas[lado] = fraccion_a_decimal(
                    eleccion.get("fractionalValue") or eleccion.get("initialFractionalValue"))
        if len(cuotas) == 3 and all(cuotas.values()):
            return {
                "mercado": mercado.get("marketName") or "Full time",
                "casa": mercado.get("sourceId"),
                "cuotas": cuotas,
                "probabilidades": probabilidades(cuotas),
            }
    return None


def _mercados(datos: Any) -> list[dict]:
    if not isinstance(datos, dict):
        return []
    if "featured" in datos:
        bloque = datos["featured"]
        if isinstance(bloque, dict):
            return [m for m in bloque.values() if isinstance(m, dict)]
    if "markets" in datos and isinstance(datos["markets"], list):
        return [m for m in datos["markets"] if isinstance(m, dict)]
    if "choices" in datos:
        return [datos]
    return []


def favorito(probs: dict[str, float]) -> dict:
    """Quién era favorito, y cuánto.

    ``lado`` es ``local``, ``visitante`` o ``None`` (partido parejo);
    ``claridad`` es ``claro`` por encima del 60 %, ``ligero`` entre el 45 y el
    60, y ``None`` si nadie llega al 45.
    """
    local = probs.get("local") or 0
    visitante = probs.get("visitante") or 0
    lado, valor = ("local", local) if local >= visitante else ("visitante", visitante)
    if valor < UMBRAL_FAVORITO:
        return {"lado": None, "probabilidad": round(max(local, visitante), 3),
                "claridad": None, "lectura": "partido parejo según el mercado"}
    claridad = "claro" if valor >= UMBRAL_CLARO else "ligero"
    return {"lado": lado, "probabilidad": round(valor, 3), "claridad": claridad,
            "lectura": f"{lado} favorito {claridad} ({valor:.0%})"}


def desde_fila(fila: dict | None) -> dict | None:
    """Reconstruye el bloque de cuotas desde una fila de la tabla ``cuotas``."""
    if not fila or fila.get("prob_local") is None:
        return None
    probs = {"local": fila["prob_local"], "empate": fila.get("prob_empate"),
             "visitante": fila["prob_visitante"]}
    return {
        "mercado": fila.get("mercado"),
        "cuotas": {"local": fila.get("local"), "empate": fila.get("empate"),
                   "visitante": fila.get("visitante")},
        "probabilidades": {k: v for k, v in probs.items() if v is not None},
        "favorito": favorito(probs),
    }


__all__ = ["fraccion_a_decimal", "probabilidades", "extraer_1x2", "favorito",
           "desde_fila", "UMBRAL_FAVORITO", "UMBRAL_CLARO"]
