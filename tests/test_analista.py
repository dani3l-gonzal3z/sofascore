"""El analista local: el bucle de herramientas contra Ollama, y LangChain.

Aquí no hay ningún Ollama: se le pasa un ``pedir`` de mentira que devuelve las
respuestas que tocan. Lo que se comprueba es el bucle —que ejecute lo que le
piden, que le devuelva el resultado, que pare cuando debe— y que las
instrucciones digan lo que tienen que decir, porque de eso depende que el
modelo no se invente cifras.
"""

from __future__ import annotations

import json

import pytest
from conftest import EVENT_ID

from cancha.analista import (
    ALTERNATIVOS,
    INSTRUCCIONES,
    MODELO_POR_DEFECTO,
    Analista,
    OllamaNoDisponible,
    Paso,
    texto_de_paso,
)
from cancha.sesion import Sesion


def _mensaje(contenido="", llamadas=None):
    mensaje = {"role": "assistant", "content": contenido}
    if llamadas:
        mensaje["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in llamadas]
    return {"message": mensaje, "done": True}


def _falso(guion, tags=None):
    """Un Ollama de mentira: devuelve el guion, respuesta a respuesta."""
    pedidas = []

    def pedir(ruta, cuerpo=None):
        pedidas.append((ruta, cuerpo))
        if ruta == "/api/tags":
            return {"models": tags if tags is not None else
                    [{"name": "hermes3:8b", "size": 4700000000,
                      "details": {"parameter_size": "8B", "family": "llama"}}]}
        return guion.pop(0) if guion else _mensaje("se acabó el guion")

    pedir.pedidas = pedidas
    return pedir


@pytest.fixture
def sesion(cliente, tmp_path):
    from cancha.match import build_report

    conexion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "a.db"))
    conexion.almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    try:
        yield conexion
    finally:
        conexion.close()


# ------------------------------------------------------------- lo que dice

def test_las_instrucciones_prohiben_lo_que_hay_que_prohibir():
    """Si esto se relaja, el modelo empieza a redondear de memoria."""
    for exigencia in ("sin muestra", "tasa base", "No estimes", "castellano"):
        assert exigencia in INSTRUCCIONES, exigencia
    assert "99" in INSTRUCCIONES, "tiene que decir que no existe la apuesta segura"


def test_un_paso_se_cuenta_en_una_linea():
    assert texto_de_paso(Paso("herramienta", nombre="x", argumentos={"a": 1}).as_dict()) \
        == "  → x(a=1)"
    assert "1200" in texto_de_paso(Paso("resultado", nombre="x", caracteres=1200).as_dict())
    assert texto_de_paso(Paso("respuesta", texto="hola").as_dict()) == ""


# --------------------------------------------------------------- comprobar

def test_comprobar_dice_lo_que_hay(sesion):
    analista = Analista(sesion=sesion, pedir=_falso([]))
    estado = analista.comprobar()
    assert estado["disponible"] and estado["instalado"]
    assert estado["modelos"][0]["parametros"] == "8B"
    assert "funciones" in estado["aviso_herramientas"]


def test_comprobar_sugiere_otro_si_el_pedido_no_esta(sesion):
    analista = Analista(sesion=sesion, modelo="no-existe",
                        pedir=_falso([], tags=[{"name": "qwen3:8b", "details": {}}]))
    estado = analista.comprobar()
    assert estado["instalado"] is False
    assert estado["sugerido"] == "qwen3:8b"
    assert "no está instalado" in estado["nota"]


def test_sin_ollama_lo_dice_con_lo_que_hay_que_hacer(sesion):
    def roto(ruta, cuerpo=None):
        raise OllamaNoDisponible("No hay nadie escuchando en http://localhost:11434.")

    estado = Analista(sesion=sesion, pedir=roto).comprobar()
    assert estado["disponible"] is False
    assert "ollama pull" in estado["como"]


def test_el_modelo_por_defecto_es_uno_que_sabe_llamar_funciones():
    assert MODELO_POR_DEFECTO == "hermes3"
    assert MODELO_POR_DEFECTO in ALTERNATIVOS


# ------------------------------------------------------------------ el bucle

def test_sin_herramientas_contesta_y_para(sesion):
    pedir = _falso([_mensaje("El Madrid perdió 0-4.")])
    salida = Analista(sesion=sesion, pedir=pedir).preguntar("¿qué pasó?")
    assert salida["respuesta"] == "El Madrid perdió 0-4."
    assert salida["vueltas"] == 1
    assert [p["tipo"] for p in salida["pasos"]] == ["respuesta"]


def test_llama_a_una_herramienta_y_usa_el_resultado(sesion):
    pedir = _falso([
        _mensaje(llamadas=[("resumen_partido", {"partido": str(EVENT_ID)})]),
        _mensaje("Ganó el Barcelona 0-4."),
    ])
    pasos = []
    salida = Analista(sesion=sesion, pedir=pedir).preguntar("¿quién ganó?", al_paso=pasos.append)

    assert salida["respuesta"] == "Ganó el Barcelona 0-4."
    assert [p.tipo for p in pasos] == ["herramienta", "resultado", "respuesta"]
    assert pasos[0].nombre == "resumen_partido"
    assert pasos[1].caracteres > 100

    # Y al modelo le llegó el resultado de verdad, no un resumen inventado.
    segunda = pedir.pedidas[-1][1]
    tool = [m for m in segunda["messages"] if m["role"] == "tool"]
    assert len(tool) == 1 and "Real Madrid" in tool[0]["content"]
    assert tool[0]["name"] == "resumen_partido"


def test_varias_herramientas_en_una_misma_vuelta(sesion):
    pedir = _falso([
        _mensaje(llamadas=[("resumen_partido", {"partido": str(EVENT_ID)}),
                           ("estado_de_la_memoria", {})]),
        _mensaje("listo"),
    ])
    salida = Analista(sesion=sesion, pedir=pedir).preguntar("dos cosas")
    nombres = [p["nombre"] for p in salida["pasos"] if p["tipo"] == "herramienta"]
    assert nombres == ["resumen_partido", "estado_de_la_memoria"]


def test_los_argumentos_en_texto_tambien_valen(sesion):
    """Algunos modelos mandan los argumentos como cadena JSON en vez de objeto."""
    pedir = _falso([
        _mensaje(llamadas=[("resumen_partido", json.dumps({"partido": str(EVENT_ID)}))]),
        _mensaje("vale"),
    ])
    salida = Analista(sesion=sesion, pedir=pedir).preguntar("x")
    tool = [m for m in pedir.pedidas[-1][1]["messages"] if m["role"] == "tool"]
    assert "Real Madrid" in tool[0]["content"]
    assert salida["respuesta"] == "vale"


def test_unos_argumentos_ilegibles_no_tumban_la_conversacion(sesion):
    pedir = _falso([_mensaje(llamadas=[("resumen_partido", "{roto")]), _mensaje("ya")])
    salida = Analista(sesion=sesion, pedir=pedir).preguntar("x")
    assert salida["respuesta"] == "ya"


def test_una_herramienta_que_no_existe_se_le_devuelve_como_error(sesion):
    pedir = _falso([_mensaje(llamadas=[("inventada", {})]), _mensaje("pues nada")])
    Analista(sesion=sesion, pedir=pedir).preguntar("x")
    tool = [m for m in pedir.pedidas[-1][1]["messages"] if m["role"] == "tool"]
    assert "No existe la herramienta" in tool[0]["content"]
    assert "disponibles" in tool[0]["content"], "el modelo tiene que poder corregirse"


def test_no_da_vueltas_para_siempre(sesion):
    """Un modelo que solo pide datos acaba teniendo que contestar."""
    pedir = _falso([_mensaje(llamadas=[("estado_de_la_memoria", {})]) for _ in range(20)])
    salida = Analista(sesion=sesion, pedir=pedir, max_vueltas=3).preguntar("x")
    assert salida["vueltas"] == 3 and salida.get("agotado")
    assert salida["pasos"][-1]["tipo"] == "aviso"


def test_en_la_ultima_vuelta_se_le_quitan_las_herramientas(sesion):
    pedir = _falso([_mensaje(llamadas=[("estado_de_la_memoria", {})]) for _ in range(5)])
    Analista(sesion=sesion, pedir=pedir, max_vueltas=3).preguntar("x")
    cuerpos = [c for r, c in pedir.pedidas if r == "/api/chat"]
    assert "tools" in cuerpos[0] and "tools" not in cuerpos[-1]


def test_el_sistema_va_primero_y_una_sola_vez(sesion):
    pedir = _falso([_mensaje("uno"), _mensaje("dos")])
    analista = Analista(sesion=sesion, pedir=pedir)
    primera = analista.preguntar("¿?")
    segunda = analista.preguntar("¿y?", historial=primera["historial"])
    mensajes = segunda["historial"]
    assert mensajes[0]["role"] == "system"
    assert sum(1 for m in mensajes if m["role"] == "system") == 1
    assert [m["content"] for m in mensajes if m["role"] == "user"] == ["¿?", "¿y?"]


def test_la_conversacion_encadena_el_hilo(sesion):
    analista = Analista(sesion=sesion, pedir=_falso([_mensaje("a"), _mensaje("b")]))
    salidas = list(analista.conversar(iter(["uno", "dos"])))
    assert [s["respuesta"] for s in salidas] == ["a", "b"]
    assert len(salidas[1]["historial"]) > len(salidas[0]["historial"])


def test_las_respuestas_se_recortan_para_que_quepan(sesion):
    pedir = _falso([_mensaje(llamadas=[("tiros_partido", {"partido": str(EVENT_ID)})]),
                    _mensaje("ya está")])
    Analista(sesion=sesion, pedir=pedir, max_chars=300).preguntar("tiros")
    tool = [m for m in pedir.pedidas[-1][1]["messages"] if m["role"] == "tool"]
    assert len(tool[0]["content"]) < 900


def test_los_esquemas_van_en_el_formato_de_ollama(sesion):
    pedir = _falso([_mensaje("hola")])
    Analista(sesion=sesion, pedir=pedir).preguntar("x")
    herramientas = pedir.pedidas[-1][1]["tools"]
    assert herramientas and herramientas[0]["type"] == "function"
    funcion = herramientas[0]["function"]
    assert {"name", "description", "parameters"} <= set(funcion)
    assert funcion["parameters"]["type"] == "object"
    assert {h["function"]["name"] for h in herramientas} >= {"casi_seguro", "briefing_del_dia"}


def test_la_temperatura_y_el_contexto_llegan(sesion):
    pedir = _falso([_mensaje("x")])
    Analista(sesion=sesion, pedir=pedir, temperatura=0.7, contexto=4096).preguntar("x")
    opciones = pedir.pedidas[-1][1]["options"]
    assert opciones == {"temperature": 0.7, "num_ctx": 4096}


# ---------------------------------------------------------------- por consola

def test_la_consola_comprueba(monkeypatch, capsys, inyectar_cliente, cliente, tmp_path):
    from cancha import cli
    from cancha.comandos import ia

    inyectar_cliente(cliente)
    monkeypatch.setattr(ia, "cmd_analista", ia.cmd_analista)
    import cancha.analista as modulo

    original = modulo.Analista.__post_init__

    def con_falso(self):
        original(self)
        self.pedir = _falso([])

    monkeypatch.setattr(modulo.Analista, "__post_init__", con_falso)
    assert cli.main(["analista", "--comprobar", "--db", str(tmp_path / "x.db")]) == 0
    salida = capsys.readouterr().out
    assert "hermes3:8b" in salida and "contesta" in salida


def test_la_consola_pregunta_y_ensena_los_pasos(monkeypatch, capsys, inyectar_cliente,
                                                cliente, tmp_path):
    import cancha.analista as modulo
    from cancha import cli

    inyectar_cliente(cliente)
    original = modulo.Analista.__post_init__
    guion = [_mensaje(llamadas=[("estado_de_la_memoria", {})]), _mensaje("La memoria está vacía.")]

    def con_falso(self):
        original(self)
        self.pedir = _falso(guion)

    monkeypatch.setattr(modulo.Analista, "__post_init__", con_falso)
    assert cli.main(["analista", "¿qué", "hay?", "--db", str(tmp_path / "y.db")]) == 0
    salida = capsys.readouterr().out
    assert "→ estado_de_la_memoria()" in salida
    assert "La memoria está vacía." in salida


# ----------------------------------------------------------------- langchain

def test_el_adaptador_de_langchain_dice_si_esta():
    from cancha.agentes.langchain import disponible

    estado = disponible()
    assert set(estado) >= {"langchain", "langchain_core", "langchain_ollama", "listo"}
    assert "pip install" in estado["instalar"]


def test_las_herramientas_de_langchain_son_las_de_cancha(sesion):
    pytest.importorskip("langchain_core")
    from cancha.agentes.langchain import herramientas
    from cancha.herramientas import TOOLS

    todas = herramientas(sesion)
    assert len(todas) == len(TOOLS)
    assert {t.name for t in todas} == set(TOOLS)
    for herramienta in todas:
        assert herramienta.description == TOOLS[herramienta.name].description


def test_una_herramienta_de_langchain_ejecuta_de_verdad(sesion):
    pytest.importorskip("langchain_core")
    from cancha.agentes.langchain import herramientas

    resumen = next(h for h in herramientas(sesion) if h.name == "resumen_partido")
    salida = json.loads(resumen.invoke({"partido": str(EVENT_ID)}))
    assert salida["partido"]["home"]["name"] == "Real Madrid"


def test_se_pueden_pedir_solo_unas_cuantas(sesion):
    pytest.importorskip("langchain_core")
    from cancha.agentes.langchain import herramientas

    pocas = herramientas(sesion, solo=["casi_seguro", "estado_de_la_memoria"])
    assert {t.name for t in pocas} == {"casi_seguro", "estado_de_la_memoria"}


def test_el_agente_de_langchain_se_construye(sesion):
    pytest.importorskip("langchain")
    pytest.importorskip("langchain_ollama")
    from cancha.agentes.langchain import agente

    construido = agente(sesion=sesion, solo=["estado_de_la_memoria"])
    assert hasattr(construido, "invoke")


def test_sin_langchain_se_dice_que_instalar(monkeypatch, sesion):
    import sys

    from cancha.agentes.langchain import LangChainNoDisponible, herramientas

    monkeypatch.setitem(sys.modules, "langchain_core.tools", None)
    with pytest.raises(LangChainNoDisponible, match="pip install"):
        herramientas(sesion)
