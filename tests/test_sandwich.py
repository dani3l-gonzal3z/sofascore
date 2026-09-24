"""El reparto de vueltas: el modelo bueno abre y cierra, el de casa va a buscar.

El bucle normal reenvía el historial entero en cada vuelta, así que el expediente
se paga otra vez en cada turno. Aquí se paga dos veces —la primera y la última— y
las de en medio, que son las de ir a por datos, salen gratis.

Lo que se prueba es lo que puede salir mal, que no es el ahorro:

* que la prosa del modelo de en medio **no** llegue al director como si fuera
  suya, porque entonces el modelo bueno defendería el razonamiento del pequeño;
* que al de en medio no se le mande el expediente, porque con una ventana de 16k
  Ollama recorta por lo viejo —las instrucciones— sin avisar;
* y que si el director no pide nada, no se gaste ni una llamada más.
"""

from __future__ import annotations

import json

import pytest

from cancha.analista import Analista


class Ollama:
    """Un Ollama de mentira que apunta quién preguntó qué, y contesta un guion."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas: list[dict] = []

    def __call__(self, ruta, cuerpo=None):
        cuerpo = cuerpo or {}
        self.llamadas.append(cuerpo)
        if not self.guion:
            return {"message": {"role": "assistant", "content": "ya está"},
                    "model": cuerpo.get("model"), "prompt_eval_count": 10,
                    "eval_count": 5}
        siguiente = self.guion.pop(0)
        return {**siguiente, "model": cuerpo.get("model"),
                "prompt_eval_count": siguiente.pop("entrada", 100),
                "eval_count": 20}

    # --- lo que se quiere poder preguntar después ---

    def de(self, modelo: str) -> list[dict]:
        return [c for c in self.llamadas if c.get("model") == modelo]

    def textos(self, modelo: str) -> str:
        return json.dumps([c["messages"] for c in self.de(modelo)],
                          ensure_ascii=False)


def _pide(nombre, **argumentos):
    return {"message": {"role": "assistant", "content": "Necesito el árbitro.",
                        "tool_calls": [{"function": {"name": nombre,
                                                     "arguments": argumentos}}]}}


def _contesta(texto):
    return {"message": {"role": "assistant", "content": texto}}


NUMEROS = ('Lo veo claro.\n\n```json\n{"1x2": {"local": 0.5, "empate": 0.28, '
           '"visitante": 0.22}}\n```')

EXPEDIENTE = ("Girona vs Osasuna\nLaLiga · 2026-09-25\nÁrbitro: Gil Manzano\n"
              "línea 4\n" + "\n".join(f"dato aburrido {n}" for n in range(300)))


@pytest.fixture
def analista():
    def construir(guion, **extra):
        falso = Ollama(guion)
        return Analista(modelo="local", modelo_director="grande", pedir=falso,
                        max_vueltas=4, **extra), falso
    return construir


def test_el_director_abre_y_cierra_y_el_local_hace_el_medio(analista):
    uno, falso = analista([
        _pide("perfil_de_arbitro", arbitro="Gil Manzano"),   # abre el director
        _contesta("listo"),                                  # el medio, sin pedir más
        _contesta(NUMEROS),                                  # cierra el director
    ])
    salida = uno.analizar(EXPEDIENTE)

    assert salida["sandwich"] is True
    assert salida["modelo"] == "grande"
    assert len(falso.de("grande")) == 2, "el bueno paga dos llamadas, no más"
    assert len(falso.de("local")) == 1, "y el de casa se encarga del medio"
    assert salida["probabilidades"]["1x2"]["local"] == 0.5


def test_la_prosa_del_de_en_medio_no_le_llega_al_director(analista):
    """Si llegara, iría como `assistant` y el director la leería como suya.

    Y los modelos se anclan a lo que creen que ya dijeron: habrías pagado por un
    modelo bueno para que defienda el razonamiento de uno peor.
    """
    uno, falso = analista([
        _pide("perfil_de_arbitro", arbitro="Gil Manzano"),
        _contesta("Yo creo que gana el Osasuna clarísimamente, apostaría la casa."),
        _contesta(NUMEROS),
    ])
    uno.analizar(EXPEDIENTE)

    cierre = falso.de("grande")[-1]["messages"]
    entero = json.dumps(cierre, ensure_ascii=False)
    assert "apostaría la casa" not in entero, "su prosa no puede viajar"
    # Pero los datos sí, y el plan del propio director también.
    assert "Necesito el árbitro" in entero, "su propio plan, sí"
    assert any(m["role"] == "tool" for m in cierre), "y los datos recogidos"


def test_al_de_en_medio_no_se_le_manda_el_expediente(analista):
    """Con una ventana de 16k, Ollama recorta por lo viejo y no lo dice.

    Y lo viejo es el sistema: el modelo se queda sin instrucciones en silencio.
    Su trabajo es traer lo que el plan pide, y para eso le basta el partido.
    """
    uno, falso = analista([
        _pide("perfil_de_arbitro", arbitro="Gil Manzano"),
        _contesta("listo"),
        _contesta(NUMEROS),
    ])
    uno.analizar(EXPEDIENTE)

    delmedio = falso.textos("local")
    assert "dato aburrido 200" not in delmedio, "el expediente no viaja al medio"
    assert "Girona vs Osasuna" in delmedio, "pero sí qué partido es"
    assert "Necesito el árbitro" in delmedio, "y el plan del director"


def test_el_medio_recibe_ya_hecho_lo_que_pidio_el_director(analista):
    """El primer encargo lo ejecuta el programa: no hace falta modelo para una lista."""
    uno, falso = analista([
        _pide("estado_de_la_memoria"),
        _contesta("listo"),
        _contesta(NUMEROS),
    ])
    uno.analizar(EXPEDIENTE)
    primera = falso.de("local")[0]["messages"]
    assert any(m["role"] == "tool" for m in primera), \
        "llega con el recado del director ya hecho"


def test_si_el_director_no_pide_nada_no_se_gasta_mas(analista):
    """Con el expediente le bastaba: ni medio ni cierre."""
    uno, falso = analista([_contesta(NUMEROS)])
    salida = uno.analizar(EXPEDIENTE)

    assert salida["sin_recados"] is True
    assert len(falso.llamadas) == 1, "una llamada y a casa"
    assert falso.de("local") == []
    assert salida["probabilidades"] is not None


def test_sin_director_se_comporta_como_siempre(analista):
    """El reparto es opcional, y no tenerlo no cambia nada de lo de antes."""
    falso = Ollama([_contesta(NUMEROS)])
    uno = Analista(modelo="local", pedir=falso, max_vueltas=4)
    salida = uno.analizar(EXPEDIENTE)
    assert not salida.get("sandwich")
    assert falso.de("local") and not falso.de("grande")


# --------------------------------------------------------------- lo que cuesta

def test_se_apunta_lo_que_gasta_cada_modelo(analista):
    """Un ahorro que no se mide es una opinión."""
    uno, _ = analista([
        _pide("perfil_de_arbitro", arbitro="X"),
        _contesta("listo"),
        _contesta(NUMEROS),
    ])
    salida = uno.analizar(EXPEDIENTE)
    por_modelo = salida["tokens"]["por_modelo"]
    assert por_modelo["grande"]["llamadas"] == 2
    assert por_modelo["local"]["llamadas"] == 1
    assert salida["tokens"]["prompt_eval_count"] > 0


def test_el_sandwich_paga_menos_que_hacerlo_todo_arriba():
    """La razón de existir de todo esto, medida en tokens de entrada de verdad.

    El guion es el mismo trabajo en los dos casos —cuatro datos que traer— y lo
    único que cambia es quién paga cada vuelta.
    """
    guion = [_pide(f"herramienta_{n}") for n in range(3)] + [_contesta(NUMEROS)]

    entero = Ollama(list(guion))
    Analista(modelo="grande", pedir=entero, max_vueltas=5).analizar(EXPEDIENTE)
    caro = sum(len(json.dumps(c["messages"], ensure_ascii=False))
               for c in entero.de("grande"))

    partido = Ollama(list(guion))
    Analista(modelo="local", modelo_director="grande", pedir=partido,
             max_vueltas=5).analizar(EXPEDIENTE)
    barato = sum(len(json.dumps(c["messages"], ensure_ascii=False))
                 for c in partido.de("grande"))

    assert barato < caro / 2, f"el bueno debería pagar mucho menos: {barato} vs {caro}"


# --------------------------------------------------------------- el techo

def test_el_techo_de_tokens_corta_aunque_queden_vueltas():
    """`vueltas` cuenta turnos, y un turno sobre un expediente grande cuesta más.

    Seis vueltas no dicen nada del gasto; un techo de tokens sí, y es lo que evita
    que una clave de la nube se convierta en una sorpresa.
    """
    guion = [_pide(f"herramienta_{n}") for n in range(8)]
    falso = Ollama(list(guion))
    uno = Analista(modelo="grande", pedir=falso, max_vueltas=8, techo_tokens=250)
    salida = uno.preguntar("analiza esto")

    assert salida["sin_presupuesto"] is True
    assert salida["vueltas"] < 8, "ha cortado antes de agotar las vueltas"
    assert salida["tokens"]["prompt_eval_count"] >= 250


def test_sin_techo_no_se_corta_por_tokens():
    falso = Ollama([_contesta("ya")])
    salida = Analista(modelo="grande", pedir=falso).preguntar("hola")
    assert not salida.get("sin_presupuesto")


# ------------------------------------------------- la llamada de los números

def test_pedir_los_numeros_no_reenvia_el_expediente():
    """Era la llamada más derrochadora: el expediente entero para sacar seis cifras.

    Los números salen del análisis, no de los datos crudos: si no están en lo que
    ha escrito, tampoco los saca de volver a leerse las tablas.
    """
    falso = Ollama([
        _contesta("Un análisis impecable, pero sin el bloque de números."),
        _contesta('```json\n{"1x2": {"local": 0.4, "empate": 0.3, '
                  '"visitante": 0.3}}\n```'),
    ])
    uno = Analista(modelo="grande", pedir=falso, max_vueltas=3)
    salida = uno.analizar(EXPEDIENTE)

    assert salida["reparado"] is True
    assert salida["probabilidades"]["1x2"]["local"] == 0.4
    reparadora = falso.llamadas[-1]["messages"]
    entero = json.dumps(reparadora, ensure_ascii=False)
    assert "dato aburrido 200" not in entero, "el expediente no se reenvía"
    assert "análisis impecable" in entero, "pero sí lo que había escrito"
