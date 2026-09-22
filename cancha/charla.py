"""Hablar de un partido con un modelo que ya sabe de qué partido se habla.

El analista general empieza cada conversación sin saber nada: hay que decirle el
partido, esperar a que lo busque, y volver a decírselo en cada pregunta. Dentro
de la pantalla de un partido eso sobra. Aquí el modelo arranca con:

* **el partido fijado** —su id—, para que cualquier herramienta que pida usarla
  sepa de qué hablamos sin preguntar;
* **una ficha corta** con lo que casi siempre hace falta —el pronóstico, lo que
  dice el mercado de cada cosa, dónde discrepamos, los marcadores más probables
  de los dos—, para que las preguntas básicas se contesten sin gastar vueltas;
* y **todas las herramientas**, para lo demás: la previa, las alineaciones, el
  árbitro, el expediente entero, cualquier dato de un jugador o de un equipo.

Por qué una ficha y no el expediente entero: el expediente son diez o quince mil
tokens, y un modelo de casa con ventana de 16k se queda sin sitio a la tercera
pregunta. Ollama entonces recorta por lo viejo, que es donde están las
instrucciones, y el modelo sigue contestando sin ellas sin que nadie se entere.
Con un modelo grande o de la nube se puede pedir ``profundidad="expediente"``.

Lo que se pregunta y lo que contesta se guarda con el partido, como los
dictámenes: se vuelve mañana y la conversación sigue ahí.
"""

from __future__ import annotations

from typing import Any

from .analista import INSTRUCCIONES

#: Lo que se le añade al sistema cuando la conversación es de un partido.
DENTRO_DEL_PARTIDO = """

ESTÁS DENTRO DE UN PARTIDO
Toda esta conversación es sobre este partido:

{cabecera}
Id del partido: {id}

Cuando una herramienta pida `partido`, pásale **{id}**. No lo busques por el
nombre: ya sabes cuál es. Si te preguntan por otro partido, dilo y búscalo.

Debajo tienes una FICHA con lo que casi siempre hace falta. Úsala para contestar
lo básico sin llamar a nada. Para todo lo demás —cómo llega cada equipo
(`previa_partido`), cuotas al detalle (`mercados_partido`), el árbitro, las
alineaciones, un jugador, el expediente entero (`expediente_partido`)—, pide lo
que necesites. Si el usuario pregunta algo que la ficha no contesta, no lo
deduzcas de la ficha: pídelo.

{ficha}"""


def ficha(almacen, cliente, evento) -> str:
    """Lo imprescindible de un partido, en unas líneas y con sus números.

    Cada bloque que falla se dice en una línea en vez de tumbar la ficha: un
    partido sin cuotas sigue teniendo pronóstico, y al revés.
    """
    from .mercados import frente_al_mercado
    from .pronostico import pronostico

    lineas = ["FICHA"]
    datos: dict[str, Any] = {}
    try:
        datos = pronostico(almacen, evento, cliente=cliente)
    except Exception as exc:  # noqa: BLE001 - la ficha no se cae por un bloque
        lineas.append(f"Pronóstico: no disponible ({exc}).")
    if datos.get("disponible"):
        g = datos["goles"]
        uno = g["1x2"]
        lineas.append(f"Nuestro 1X2: local {uno['local']:.0%} · empate "
                      f"{uno['empate']:.0%} · visitante {uno['visitante']:.0%}")
        esperados = g.get("esperados") or {}
        if esperados:
            lineas.append(f"Goles esperados: {esperados.get('local')} - "
                          f"{esperados.get('visitante')} (medido en "
                          f"{g.get('medido_en', '?')})")
        lineas.append("Nuestros marcadores más probables: " + ", ".join(
            f"{m['marcador']} {m['probabilidad']:.1%}" for m in g["marcadores"][:5]))
        if (g.get("mas_de") or {}).get("2.5") is not None:
            lineas.append(f"Más de 2,5 goles: {g['mas_de']['2.5']:.0%} · marcan los "
                          f"dos: {g.get('ambos_marcan', 0):.0%}")
    elif datos:
        lineas.append(f"Pronóstico: {datos.get('nota', 'sin muestra suficiente')}.")

    mercado = {}
    try:
        mercado = frente_al_mercado(almacen, evento.id, datos)
    except Exception as exc:  # noqa: BLE001
        lineas.append(f"Mercado: no disponible ({exc}).")
    if mercado.get("disponible"):
        lineas.append("Lo que dice el mercado (casa que menos cobra, sin margen):")
        for s in mercado["sucesos"]:
            if s["mercado"] is None:
                continue
            nuestro = f"{s['nuestra']:.0%}" if s["nuestra"] is not None else "—"
            marca = "  ← discrepamos" if s["discrepa"] else ""
            lineas.append(f"  {s['suceso']}: mercado {s['mercado']:.0%} (cuota "
                          f"{s['cuota']}), nosotros {nuestro}{marca}")
        exacto = mercado.get("marcador_exacto") or {}
        if exacto.get("mas_probables_mercado"):
            lineas.append("Marcadores más probables según el mercado: " + ", ".join(
                f"{m} {p:.1%}" for m, p in exacto["mas_probables_mercado"][:5]))
        movidos = [m for m in mercado.get("movimiento") or []
                   if m.get("cambio") and abs(m["cambio"]) >= 0.05]
        if movidos:
            lineas.append("Movimiento desde la apertura: " + ", ".join(
                f"{m['seleccion']} {m['apertura']}→{m['ahora']}" for m in movidos))
    elif mercado:
        lineas.append(f"Mercado: {mercado.get('nota')}")
    return "\n".join(lineas)


def sistema(almacen, cliente, partido, profundidad: str = "ficha") -> dict:
    """El mensaje de sistema de una conversación dentro de un partido.

    ``profundidad`` es ``ficha`` (lo de siempre, cabe en cualquier modelo) o
    ``expediente`` (el documento entero, para modelos grandes).
    """
    from .expediente import a_texto, cabecera, expediente
    from .previa import _resolver

    evento = partido if hasattr(partido, "home") else _resolver(almacen, partido, cliente)
    if evento is None:
        return {"error": "No encuentro ese partido."}
    if profundidad == "expediente":
        datos = expediente(almacen, evento, cliente=cliente, crudo="tabla")
        cuerpo = a_texto(datos)
        encabezado = cabecera(datos)
    else:
        cuerpo = ficha(almacen, cliente, evento)
        encabezado = f"{evento.home.name} - {evento.away.name} · {evento.tournament}"
    return {
        "partido_id": evento.id,
        "partido": f"{evento.home.name} - {evento.away.name}",
        "sistema": INSTRUCCIONES + DENTRO_DEL_PARTIDO.format(
            cabecera=encabezado, id=evento.id, ficha=cuerpo),
        "tamano": len(cuerpo) // 4,
    }


#: Preguntas para empezar. Están escritas para que cada una tire de una parte
#: distinta de lo que hay, no para que suenen bien.
SUGERIDAS = (
    "¿Qué ves en este partido, en tres frases?",
    "¿Dónde no estamos de acuerdo con el mercado, y quién crees que tiene razón?",
    "¿Qué marcador ves más probable y por qué?",
    "¿Cómo llega cada equipo en sus últimos partidos?",
    "¿Qué dice el árbitro de tarjetas y faltas?",
    "¿Hay algo que haya cambiado en el estilo de alguno de los dos?",
)


__all__ = ["DENTRO_DEL_PARTIDO", "SUGERIDAS", "ficha", "sistema"]
