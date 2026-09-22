"""Hablar de un partido con un modelo que ya sabe de qué partido se habla.

Lo que se prueba: que arranca con el partido fijado y una ficha corta —no el
expediente entero, que no cabe en un modelo de casa—, que lo hablado se guarda
con el partido, y que mientras el modelo piensa el servidor no se queda
congelado.
"""

from __future__ import annotations

import json
import threading

from conftest import EVENT_ID
from test_web import _pedir, servidor  # noqa: F401 - el fixture se usa por nombre

from cancha.analista import Analista
from cancha.charla import DENTRO_DEL_PARTIDO, SUGERIDAS, ficha, sistema


def test_el_sistema_lleva_el_partido_fijado(servidor):  # noqa: F811
    inicio = sistema(servidor.sesion.almacen, servidor.sesion.cliente, str(EVENT_ID))
    assert inicio["partido_id"] == EVENT_ID
    assert f"Id del partido: {EVENT_ID}" in inicio["sistema"]
    assert "ESTÁS DENTRO DE UN PARTIDO" in inicio["sistema"]
    assert "No lo busques" in inicio["sistema"]


def test_la_ficha_es_corta_y_el_expediente_se_pide_aparte(servidor):  # noqa: F811
    """Con un modelo de 16k, el expediente entero no deja sitio a la tercera
    pregunta y Ollama recorta por lo viejo, que es donde están las instrucciones."""
    corta = sistema(servidor.sesion.almacen, servidor.sesion.cliente, str(EVENT_ID))
    larga = sistema(servidor.sesion.almacen, servidor.sesion.cliente, str(EVENT_ID),
                    profundidad="expediente")
    assert corta["tamano"] < larga["tamano"]
    assert "expediente_partido" in corta["sistema"], "y se le dice cómo pedirlo"


def test_la_ficha_no_se_cae_si_un_bloque_falla(servidor, monkeypatch):  # noqa: F811
    import cancha.pronostico as modulo

    def revienta(*a, **k):
        raise RuntimeError("sin fuerzas")

    monkeypatch.setattr(modulo, "pronostico", revienta)
    from cancha.previa import _resolver

    evento = _resolver(servidor.sesion.almacen, str(EVENT_ID), servidor.sesion.cliente)
    texto = ficha(servidor.sesion.almacen, servidor.sesion.cliente, evento)
    assert "no disponible" in texto
    assert texto.startswith("FICHA")


def test_un_partido_que_no_existe_se_dice(servidor):  # noqa: F811
    assert "error" in sistema(servidor.sesion.almacen, None, "999999999")


def test_las_preguntas_sugeridas_no_estan_vacias():
    assert len(SUGERIDAS) >= 4 and all(s.endswith("?") for s in SUGERIDAS)
    assert "{id}" in DENTRO_DEL_PARTIDO


# ------------------------------------------------------------ en el servidor

def _modelo_falso(respuesta="El local llega mejor."):
    """Ollama de mentira: apunta lo que le mandan y contesta siempre lo mismo."""
    visto = []

    def pedir(ruta, cuerpo=None):
        visto.append(cuerpo)
        return {"message": {"role": "assistant", "content": respuesta},
                "model": (cuerpo or {}).get("model"),
                "prompt_eval_count": 10, "eval_count": 5}
    return pedir, visto


def _flujo(app, cuerpo):
    """Una pregunta al analista, leyendo su respuesta línea a línea (NDJSON)."""
    from http.client import HTTPConnection

    conexion = HTTPConnection("127.0.0.1", app.puerto, timeout=10)
    conexion.request("POST", "/api/analista", body=json.dumps(cuerpo).encode(),
                     headers={"Content-Type": "application/json"})
    texto = conexion.getresponse().read().decode()
    conexion.close()
    return [json.loads(x) for x in texto.splitlines() if x.strip()]


def test_preguntar_dentro_de_un_partido_guarda_la_charla(servidor):  # noqa: F811
    pedir, visto = _modelo_falso()
    servidor.analista().pedir = pedir

    eventos = _flujo(servidor, {"pregunta": "¿Qué ves?", "partido": str(EVENT_ID)})
    assert any("fin" in e for e in eventos)
    sistema_mandado = visto[0]["messages"][0]["content"]
    assert f"Id del partido: {EVENT_ID}" in sistema_mandado

    _, _, guardada = _pedir(servidor, "POST", "/api/charla", {"partido": str(EVENT_ID)})
    assert guardada["mensajes"][0]["pregunta"] == "¿Qué ves?"
    assert guardada["mensajes"][0]["respuesta"] == "El local llega mejor."


def test_la_charla_se_borra(servidor):  # noqa: F811
    servidor.sesion.almacen.guardar_charla(EVENT_ID, "¿Y?", "Pues eso.")
    _, _, salida = _pedir(servidor, "POST", "/api/charla/borrar",
                          {"partido": str(EVENT_ID)})
    assert salida["borrados"] == 1
    _, _, despues = _pedir(servidor, "POST", "/api/charla", {"partido": str(EVENT_ID)})
    assert despues["mensajes"] == []


def test_sin_partido_la_pregunta_no_se_guarda_en_ninguno(servidor):  # noqa: F811
    pedir, _ = _modelo_falso()
    servidor.analista().pedir = pedir
    _flujo(servidor, {"pregunta": "¿Qué hay hoy?"})
    assert servidor.sesion.almacen.consulta("SELECT * FROM charlas") == []


# ------------------------------------------------------------------ el cerrojo

def test_mientras_el_modelo_piensa_la_memoria_queda_libre():
    """Antes el servidor sostenía el cerrojo durante toda la respuesta: con un
    modelo de casa, minutos de página congelada."""
    cerrojo = threading.Lock()
    libre_mientras_piensa = []

    def pedir(ruta, cuerpo=None):
        libre_mientras_piensa.append(not cerrojo.locked())
        return {"message": {"role": "assistant", "content": "ya"}}

    Analista(modelo="x", pedir=pedir, cerrojo=cerrojo).preguntar("hola")
    assert libre_mientras_piensa == [True]


def test_al_ejecutar_una_herramienta_si_se_coge_el_cerrojo(monkeypatch):
    """Es cuando se toca la memoria, y la memoria la comparte todo el servidor."""
    import cancha.herramientas as modulo

    cerrojo = threading.Lock()
    cogido = []

    def ejecutar(nombre, argumentos, sesion=None, max_chars=0):
        cogido.append(cerrojo.locked())
        return {"ok": True}

    monkeypatch.setattr(modulo, "ejecutar", ejecutar)
    guion = [{"message": {"role": "assistant", "content": "",
                          "tool_calls": [{"function": {"name": "estado_de_la_memoria",
                                                       "arguments": {}}}]}},
             {"message": {"role": "assistant", "content": "listo"}}]
    Analista(modelo="x", pedir=lambda r, c=None: guion.pop(0),
             cerrojo=cerrojo).preguntar("hola")
    assert cogido == [True]
