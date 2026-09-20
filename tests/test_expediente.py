"""El expediente y el dictamen: darle todo a un modelo de una vez.

Lo que se comprueba: que el documento traiga lo que tiene que traer, que una
parte rota no se lleve el resto, que no se cuele nada posterior al partido, y
—lo que más— que hablar con la nube no filtre la clave ni mienta sobre dónde
están yendo los datos.
"""

from __future__ import annotations

import pytest
from conftest import EVENT_ID

from cancha.almacen import Almacen
from cancha.analista import URL_NUBE, Analista
from cancha.expediente import a_texto, expediente
from cancha.match import build_report


@pytest.fixture
def base(cliente):
    with Almacen(":memory:") as almacen:
        almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
        yield almacen


# ---------------------------------------------------------------- el documento

def test_el_expediente_trae_las_partes_que_importan(base, cliente):
    datos = expediente(base, EVENT_ID, cliente=cliente)
    assert datos["disponible"] is True
    for parte in ("partido", "pronostico", "previa", "ultimos_partidos",
                  "entre_ellos", "casi_seguro", "tamano"):
        assert parte in datos, parte
    assert datos["partido"]["local"] == "Real Madrid"


def test_el_texto_lleva_los_apartados_y_lo_que_no_sabe(base, cliente):
    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente))
    for titulo in ("# Real Madrid contra Barcelona", "## Cómo juega cada uno",
                   "## Últimos partidos", "## Árbitro",
                   "## Lo que casi siempre pasa", "## Lo que este expediente NO sabe"):
        assert titulo in texto, titulo
    assert "alineaciones" in texto.lower(), "tiene que decir lo que no sabe"


def test_dice_cuanto_ocupa_antes_de_que_lo_mandes(base, cliente):
    """Si lo vas a mandar a un sitio donde se paga, es lo primero que quieres."""
    datos = expediente(base, EVENT_ID, cliente=cliente)
    assert datos["tamano"]["caracteres"] > 200
    assert datos["tamano"]["tokens_aprox"] == datos["tamano"]["caracteres"] // 4


def test_una_parte_rota_no_se_lleva_el_expediente(base, cliente, monkeypatch):
    """Sin árbitro guardado el expediente sigue valiendo; sin expediente, no."""
    import cancha.pronostico as modulo

    monkeypatch.setattr(modulo, "pronostico",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("roto")))
    datos = expediente(base, EVENT_ID, cliente=cliente)
    assert datos["disponible"] is True
    assert datos["pronostico"]["disponible"] is False
    assert "roto" in datos["pronostico"]["nota"]
    assert "## Cómo juega cada uno" in a_texto(datos), "el resto sigue ahí"


def test_sin_el_partido_lo_dice(base):
    datos = expediente(base, "un partido que no existe 12345")
    assert datos["disponible"] is False
    assert a_texto(datos) == datos["nota"]


def test_no_se_cuelan_partidos_posteriores(base, cliente):
    """Meter en el expediente algo que aún no había pasado es mirar el futuro."""
    from cancha.previa import _resolver

    evento = _resolver(base, EVENT_ID, cliente)
    datos = expediente(base, EVENT_ID, cliente=cliente)
    for lado in ("local", "visitante"):
        for partido in (datos["ultimos_partidos"].get(lado) or {}).get("partidos", []):
            assert partido["fecha"] < evento.date, partido
    for partido in datos["entre_ellos"]["partidos"]:
        assert partido["fecha"] < evento.date


# ------------------------------------------------------------------ dictamen

class Falso:
    """Se hace pasar por Ollama y apunta lo que se le manda."""

    def __init__(self):
        self.cuerpos = []

    def __call__(self, ruta, cuerpo=None):
        self.cuerpos.append(cuerpo)
        return {"message": {"content": "El local llega mejor."},
                "prompt_eval_count": 2500, "eval_count": 140}


def test_el_dictamen_va_de_una_sola_vez_y_sin_herramientas(base, cliente):
    """Con un modelo grande lo que se quiere es que vea todo a la vez."""
    falso = Falso()
    analista = Analista(modelo="grande", pedir=falso, sesion=False)
    salida = analista.dictaminar(a_texto(expediente(base, EVENT_ID, cliente=cliente)))
    assert len(falso.cuerpos) == 1, "una llamada, no un bucle"
    cuerpo = falso.cuerpos[0]
    assert "tools" not in cuerpo, "sin herramientas: ya lo tiene todo delante"
    assert [m["role"] for m in cuerpo["messages"]] == ["system", "user"]
    assert "Real Madrid" in cuerpo["messages"][1]["content"]
    assert salida["respuesta"] == "El local llega mejor."
    assert salida["tokens"] == {"prompt_eval_count": 2500, "eval_count": 140}


def test_las_instrucciones_le_prohiben_inventarse_numeros():
    from cancha.analista import INSTRUCCIONES_DICTAMEN

    assert "no inventes" in INSTRUCCIONES_DICTAMEN.lower()
    assert "mercado" in INSTRUCCIONES_DICTAMEN.lower()
    assert "10-12" in INSTRUCCIONES_DICTAMEN, "el aviso del marcador más probable"


# --------------------------------------------------------------------- la nube

def test_con_clave_se_habla_con_la_nube_sin_decirlo_dos_veces():
    analista = Analista(api_key="secreta", pedir=lambda *a, **k: {})
    assert analista.url == URL_NUBE
    assert analista.comprobar.__doc__  # solo para que no se queje el linter


def test_una_url_propia_gana_a_la_nube():
    analista = Analista(api_key="secreta", url="http://mio:1234",
                        pedir=lambda *a, **k: {})
    assert analista.url == "http://mio:1234"


def test_sin_clave_nada_sale_de_tu_maquina():
    from cancha.analista import URL_OLLAMA

    assert Analista(pedir=lambda *a, **k: {}).url == URL_OLLAMA


def test_la_clave_va_en_la_cabecera_y_no_en_el_cuerpo(monkeypatch):
    """Si acabara en el cuerpo se quedaría en cualquier registro de por medio."""
    import cancha.analista as modulo

    vistas = {}

    class RespuestaFalsa:
        def read(self):
            return b'{"message": {"content": "ok"}}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def urlopen_falso(peticion, timeout=None, **_k):
        vistas["cabeceras"] = dict(peticion.header_items())
        vistas["cuerpo"] = peticion.data.decode("utf-8")
        vistas["url"] = peticion.full_url
        return RespuestaFalsa()

    monkeypatch.setattr(modulo.urllib.request, "urlopen", urlopen_falso)
    Analista(api_key="s3cr3ta", modelo="grande").dictaminar("expediente")

    assert vistas["cabeceras"].get("Authorization") == "Bearer s3cr3ta"
    assert "s3cr3ta" not in vistas["cuerpo"], "la clave no puede ir en el cuerpo"
    assert vistas["url"].startswith(URL_NUBE)


def test_una_clave_mala_se_explica_en_vez_de_dar_un_401_a_secas(monkeypatch):
    import urllib.error

    import cancha.analista as modulo

    def urlopen_falso(peticion, timeout=None, **_k):
        raise urllib.error.HTTPError(peticion.full_url, 401, "no", {}, None)

    monkeypatch.setattr(modulo.urllib.request, "urlopen", urlopen_falso)
    with pytest.raises(modulo.OllamaNoDisponible) as fallo:
        Analista(api_key="mala").dictaminar("x")
    assert "API keys" in str(fallo.value), "tiene que decir dónde sacarla"


def test_sin_saldo_tambien_se_explica(monkeypatch):
    import urllib.error

    import cancha.analista as modulo

    def urlopen_falso(peticion, timeout=None, **_k):
        raise urllib.error.HTTPError(peticion.full_url, 402, "no", {}, None)

    monkeypatch.setattr(modulo.urllib.request, "urlopen", urlopen_falso)
    with pytest.raises(modulo.OllamaNoDisponible, match="saldo"):
        Analista(api_key="sinsaldo").dictaminar("x")
