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
    """Los apartados van numerados y en orden: un informe, no un volcado."""
    from cancha.expediente import APARTADOS

    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente))
    assert texto.startswith("EXPEDIENTE DE PARTIDO — Real Madrid vs Barcelona")
    for numero, titulo in enumerate(APARTADOS, 1):
        assert f"## {numero}. {titulo}" in texto, titulo
    # Y en el orden del índice, que es lo que permite citar «el apartado 3».
    posiciones = [texto.index(f"## {n}. {t}") for n, t in enumerate(APARTADOS, 1)]
    assert posiciones == sorted(posiciones)
    assert "alineaciones" in texto.lower(), "tiene que decir lo que no sabe"


def test_el_texto_explica_su_propia_notacion(base, cliente):
    """Un modelo que no sabe qué es «n=» se inventa la interpretación."""
    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente))
    clave = texto[:texto.index("ÍNDICE")]
    assert "n=X es el número de partidos" in clave
    assert "suelo" in clave and "Wilson" in clave
    assert "fuera de muestra" in clave
    assert "ÍNDICE" in texto, "y un índice, para poder citar apartados"


def test_cada_cifra_de_equipo_lleva_su_muestra(base, cliente):
    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente))
    assert "Medido sobre n=" in texto
    assert "media de su liga: n=" in texto


def test_el_mercado_es_un_apartado_aunque_no_haya_pronostico(base, cliente, monkeypatch):
    """Iba dentro del pronóstico, así que sin pronóstico desaparecía."""
    import cancha.pronostico as modulo

    monkeypatch.setattr(modulo, "pronostico",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("roto")))
    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente))
    assert "## 3. Mercado" in texto


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
    assert "## 4. Perfil de los dos equipos" in a_texto(datos), "el resto sigue ahí"


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


# --------------------------------------------- el prompt, como un encargo real

def test_las_instrucciones_tienen_rol_metodo_reglas_y_formato():
    """«Analiza esto» produce una redacción. Un encargo produce un informe."""
    from cancha.analista import INSTRUCCIONES_DICTAMEN as guion

    for apartado in ("ROL", "ENTRADA", "MÉTODO", "REGLAS QUE NO SE NEGOCIAN",
                     "FORMATO DE SALIDA"):
        assert apartado in guion, apartado
    # El formato de salida nombra los cinco apartados de la respuesta.
    for titulo in ("**Lectura**", "**En qué me apoyo**",
                   "**Dónde el cálculo y el mercado no coinciden**",
                   "**Qué me haría cambiar de opinión**", "**Confianza**"):
        assert titulo in guion, titulo


def test_las_instrucciones_le_prohiben_lo_que_hay_que_prohibirle():
    from cancha.analista import INSTRUCCIONES_DICTAMEN as guion

    assert "no inventes" in guion.lower()
    assert "n<4" in guion, "el suelo de muestra, explícito"
    assert "10-12" in guion, "el aviso del marcador más probable"
    assert "mercado es un rival serio" in guion
    assert "se cae" in guion, "un patrón que no aguanta no se vende como bueno"
    assert "No des consejos de apuesta" in guion


def test_las_instrucciones_explican_la_notacion_del_expediente():
    """Si no sabe qué es «suelo», se lo inventa."""
    from cancha.analista import INSTRUCCIONES_DICTAMEN as guion

    assert "n=X" in guion
    assert "Wilson" in guion
    assert "fuera de muestra" in guion


def test_el_expediente_dice_cuando_se_preparo_y_con_que(base, cliente):
    """Un informe sin fecha ni fuente no es un informe."""
    datos = expediente(base, EVENT_ID, cliente=cliente)
    assert datos["preparado_el"]
    assert datos["partidos_en_memoria"] == 1
    texto = a_texto(datos)
    assert "Preparado por cancha el" in texto
    assert "partidos en memoria" in texto


# ------------------------------------------- los datos en crudo, partido a partido

def _con_historial(base, cliente):
    """Seis partidos del local, con estadísticas, anteriores al que se analiza."""
    from cancha.models import Event

    for n in range(1, 7):
        identificador = 7000 + n
        base._conexion.execute(
            """INSERT INTO partidos (id,fecha,momento,liga_id,liga,local_id,local,
               visitante_id,visitante,goles_local,goles_visitante,estado)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identificador, f"2024-09-{n:02d}", 1_700_000_000 + n, 8, "LaLiga",
             2829, "Real Madrid", 3000 + n, f"Rival {n}", 2, 1, "finished"))
        for clave, valor in (("expectedGoals", 1.5 + n / 10),
                             ("totalShotsOnGoal", 12 + n),
                             ("cornerKicks", 5 + n), ("ballPossession", 55)):
            base._conexion.execute(
                """INSERT INTO estadisticas (partido_id,periodo,clave,local,visitante)
                   VALUES (?,?,?,?,?)""", (identificador, "ALL", clave, valor, 1))
    base._conexion.commit()
    del Event, cliente


def test_el_expediente_lleva_las_estadisticas_partido_a_partido(base, cliente):
    """Una media de seis esconde justo lo que a veces importa."""
    _con_historial(base, cliente)
    texto = a_texto(expediente(base, EVENT_ID, cliente=cliente, crudo="tabla"))
    assert "## 6. Datos en crudo, partido a partido" in texto
    assert "xG 1.6/1" in texto, "los números de cada partido, no la media"
    assert texto.count("2024-09-") >= 6, "una línea por partido"


def test_el_modo_todo_trae_todas_las_claves(base, cliente):
    _con_historial(base, cliente)
    tabla = a_texto(expediente(base, EVENT_ID, cliente=cliente, crudo="tabla"))
    todo = a_texto(expediente(base, EVENT_ID, cliente=cliente, crudo="todo"))
    assert len(todo) > len(tabla), "todo tiene que traer más que la tabla"
    assert "posesión %:" in todo, "en `todo` cada clave va con su nombre"


def test_se_puede_quitar_el_crudo(base, cliente):
    """Para un modelo pequeño, esto no cabe.

    El apartado se queda igualmente, vacío y diciéndolo: quitarlo dejaba un
    hueco en la numeración —del 5 al 7— y un índice que mentía.
    """
    _con_historial(base, cliente)
    sin = a_texto(expediente(base, EVENT_ID, cliente=cliente, crudo="no"))
    assert "## 6. Datos en crudo, partido a partido" in sin
    apartado = sin[sin.index("## 6."):sin.index("## 7.")]
    assert "No se han incluido" in apartado
    assert "xG" not in apartado, "y sin las estadísticas, que es de lo que se trata"


def test_los_numeros_no_traen_basura_de_coma_flotante():
    """«0.6000000000000001» no es una cifra, es ruido y tokens."""
    from cancha.expediente import _num

    assert _num(0.1 + 0.5) == "0.6"
    assert _num(2.0) == "2"
    assert _num(None) == "—"
    assert _num(56.75) == "56.75"


def test_el_indice_nunca_salta_un_numero(base, cliente):
    """Un índice con un hueco es un índice que miente."""
    from cancha.expediente import APARTADOS

    for modo in ("no", "tabla", "todo"):
        texto = a_texto(expediente(base, EVENT_ID, cliente=cliente, crudo=modo))
        indice = texto[texto.index("ÍNDICE"):texto.index("## 1.")]
        for numero, nombre in enumerate(APARTADOS, 1):
            assert f"{numero}. {nombre}" in indice, (modo, nombre)
            assert f"## {numero}. {nombre}" in texto, (modo, nombre)


# --------------------------------------------- el dictamen se queda guardado

def test_un_dictamen_se_guarda_con_su_partido(base):
    """Cuesta dinero y tiempo: volver mañana y encontrarlo es la mitad del valor."""
    base._conexion.execute(
        "INSERT OR IGNORE INTO partidos (id,fecha) VALUES (?,?)", (EVENT_ID, "2024-10-26"))
    base._conexion.commit()
    identificador = base.guardar_dictamen(
        EVENT_ID, "El local llega mejor.", modelo="grande",
        expediente="EXPEDIENTE…", en_la_nube=True,
        tokens={"prompt_eval_count": 2500, "eval_count": 140})
    assert identificador > 0

    guardados = base.dictamenes_de(EVENT_ID)
    assert len(guardados) == 1
    assert guardados[0]["respuesta"] == "El local llega mejor."
    assert guardados[0]["modelo"] == "grande"
    assert guardados[0]["en_la_nube"] == 1
    assert guardados[0]["tokens_prompt"] == 2500
    assert guardados[0]["hecho_el"], "con su fecha, o no se sabe de cuándo es"
    assert "expediente" not in guardados[0], "no se arrastra si no se pide"
    assert base.dictamenes_de(EVENT_ID, con_expediente=True)[0]["expediente"]


def test_pedir_otro_no_borra_el_anterior(base):
    """Querer otra opinión no es querer olvidar la primera."""
    base._conexion.execute(
        "INSERT OR IGNORE INTO partidos (id,fecha) VALUES (?,?)", (EVENT_ID, "2024-10-26"))
    base._conexion.commit()
    base.guardar_dictamen(EVENT_ID, "Primero", modelo="a")
    base.guardar_dictamen(EVENT_ID, "Segundo", modelo="b")
    guardados = base.dictamenes_de(EVENT_ID)
    assert [d["respuesta"] for d in guardados] == ["Segundo", "Primero"]


def test_se_puede_borrar_uno(base):
    base._conexion.execute(
        "INSERT OR IGNORE INTO partidos (id,fecha) VALUES (?,?)", (EVENT_ID, "2024-10-26"))
    base._conexion.commit()
    identificador = base.guardar_dictamen(EVENT_ID, "Fuera", modelo="a")
    assert base.borrar_dictamen(identificador) is True
    assert base.dictamenes_de(EVENT_ID) == []
