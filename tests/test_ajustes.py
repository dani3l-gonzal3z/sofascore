"""Los ajustes: decidir una vez y que mande lo que has decidido.

Lo que más importa aquí es el orden —la línea de comandos gana al fichero, y
el fichero a lo de fábrica—, que un fichero roto no te deje sin programa, y que
el token del bot no se enseñe de vuelta ni se borre sin querer.
"""

from __future__ import annotations

import json

import pytest

from cancha import ajustes


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "ajustes.json"


# ------------------------------------------------------------- leer y escribir

def test_sin_fichero_salen_los_de_fabrica(ruta):
    cargados = ajustes.cargar(ruta)
    assert cargados["guardia"]["hora"] == "03:00"
    assert cargados["ligas"] == []
    assert "_error" not in cargados


def test_lo_guardado_gana_a_lo_de_fabrica(ruta):
    ajustes.guardar(ajustes.poner(ajustes.cargar(ruta), "guardia.hora", "02:15"), ruta)
    assert ajustes.cargar(ruta)["guardia"]["hora"] == "02:15"
    # Y lo que no tocaste sigue en su sitio.
    assert ajustes.cargar(ruta)["guardia"]["partidos"] == 12


def test_un_fichero_a_medias_no_pierde_el_resto(ruta):
    """Guardar solo una clave no puede dejar las demás sin valor."""
    ruta.write_text(json.dumps({"modelo": "qwen2.5:7b"}), encoding="utf-8")
    cargados = ajustes.cargar(ruta)
    assert cargados["modelo"] == "qwen2.5:7b"
    assert cargados["guardia"]["hora"] == "03:00"
    assert cargados["web"]["puerto"] == 8765


def test_un_fichero_roto_avisa_pero_no_te_deja_sin_programa(ruta):
    """Si esto tumbara el arranque, no podrías ni entrar a arreglarlo."""
    ruta.write_text("{ esto no es json", encoding="utf-8")
    cargados = ajustes.cargar(ruta)
    assert "_error" in cargados and "No he podido leer" in cargados["_error"]
    assert cargados["guardia"]["hora"] == "03:00"


def test_un_json_que_no_es_un_objeto_tambien(ruta):
    ruta.write_text("[1, 2, 3]", encoding="utf-8")
    assert "_error" in ajustes.cargar(ruta)


def test_las_claves_inventadas_no_se_guardan(ruta):
    """Una clave que nadie lee es peor que no tenerla: parece que hace algo."""
    ruta.write_text(json.dumps({"guardia": {"hora": "01:00"}, "invento": 42}),
                    encoding="utf-8")
    cargados = ajustes.cargar(ruta)
    assert cargados["guardia"]["hora"] == "01:00"
    assert "invento" not in cargados


# ------------------------------------------------------------------- poner

@pytest.mark.parametrize("clave,texto,esperado", [
    ("guardia.hora", "02:30", "02:30"),
    ("guardia.partidos", "20", 20),
    ("guardia.activa", "no", False),
    ("guardia.activa", "sí", True),
    ("ligas", "grandes, uefa , laliga", ["grandes", "uefa", "laliga"]),
    ("web.puerto", "9000", 9000),
])
def test_poner_convierte_al_tipo_que_toca(clave, texto, esperado):
    cambiados = ajustes.poner(ajustes.cargar("/no/existe"), clave, texto)
    nodo = cambiados
    for parte in clave.split("."):
        nodo = nodo[parte]
    assert nodo == esperado


def test_una_clave_que_no_existe_se_dice_con_la_lista_de_las_que_si():
    with pytest.raises(ajustes.AjusteDesconocido) as fallo:
        ajustes.poner(ajustes.cargar("/no/existe"), "guardia.horita", "02:00")
    assert "guardia.hora" in str(fallo.value)


def test_un_numero_que_no_es_numero_se_dice():
    with pytest.raises(ajustes.AjusteDesconocido, match="entero"):
        ajustes.poner(ajustes.cargar("/no/existe"), "guardia.partidos", "muchos")


# ------------------------------------------------------------------ revisar

def test_una_hora_imposible_se_detecta():
    malos = ajustes.poner(ajustes.cargar("/no/existe"), "guardia.hora", "las tres")
    assert any("03:00" in p for p in ajustes.revisar(malos))


def test_una_liga_inventada_se_avisa_pero_no_rompe():
    malos = ajustes.poner(ajustes.cargar("/no/existe"), "ligas", "grandes,liga de mi barrio")
    problemas = ajustes.revisar(malos)
    assert any("liga de mi barrio" in p for p in problemas)


def test_las_ligas_de_verdad_no_se_quejan():
    buenos = ajustes.poner(ajustes.cargar("/no/existe"), "ligas",
                           "grandes,femenino,laliga,premier")
    assert ajustes.revisar(buenos) == []


def test_un_chat_que_no_es_un_numero_se_detecta():
    malos = ajustes.cargar("/no/existe")
    malos["telegram"]["chats"] = ["pepe"]
    assert any("identificador de chat" in p for p in ajustes.revisar(malos))


def test_un_puerto_imposible_se_detecta():
    malos = ajustes.poner(ajustes.cargar("/no/existe"), "web.puerto", "99999")
    assert any("puerto" in p for p in ajustes.revisar(malos))


# ------------------------------------------------------------------ el token

def test_el_token_no_se_devuelve_nunca_entero():
    con_token = ajustes.poner(ajustes.cargar("/no/existe"), "telegram.token",
                              "123456:AAEsecretisimo")
    tapado = ajustes.sin_secretos(con_token)
    assert "secretisimo" not in json.dumps(tapado)
    assert tapado["telegram"]["token"].startswith("•")
    assert tapado["telegram"]["token_puesto"] is True


def test_guardar_desde_la_interfaz_no_borra_el_token_que_no_has_tocado():
    """Abrir los ajustes y darle a guardar no puede dejarte sin bot."""
    con_token = ajustes.poner(ajustes.cargar("/no/existe"), "telegram.token", "123:ABC")
    tapado = ajustes.sin_secretos(con_token)
    # La página devuelve lo que se le enseñó, con el token tapado.
    vuelta = ajustes.aplicar_desde_fuera(con_token, {
        "guardia": {"hora": "04:00"},
        "telegram": {"token": tapado["telegram"]["token"], "chats": [42]}})
    assert vuelta["telegram"]["token"] == "123:ABC", "se ha borrado el token"
    assert vuelta["telegram"]["chats"] == [42]
    assert vuelta["guardia"]["hora"] == "04:00"


def test_un_token_nuevo_desde_la_interfaz_si_se_guarda():
    con_token = ajustes.poner(ajustes.cargar("/no/existe"), "telegram.token", "viejo")
    vuelta = ajustes.aplicar_desde_fuera(con_token, {"telegram": {"token": "nuevo"}})
    assert vuelta["telegram"]["token"] == "nuevo"


def test_sin_token_no_se_finge_que_hay_uno():
    tapado = ajustes.sin_secretos(ajustes.cargar("/no/existe"))
    assert tapado["telegram"]["token"] == ""
    assert tapado["telegram"]["token_puesto"] is False


# ------------------------------------------------------------- quién manda

class Dichos:
    """Un Namespace de mentira, como el que deja argparse."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_la_linea_de_comandos_gana_al_fichero():
    guardados = ajustes.poner(ajustes.cargar("/no/existe"), "guardia.hora", "02:00")
    args = Dichos(a_las="05:30")
    assert ajustes.valor(args, "a_las", guardados["guardia"]["hora"]) == "05:30"


def test_sin_decir_nada_manda_el_fichero():
    guardados = ajustes.poner(ajustes.cargar("/no/existe"), "guardia.hora", "02:00")
    args = Dichos(a_las=None)
    assert ajustes.valor(args, "a_las", guardados["guardia"]["hora"]) == "02:00"


def test_un_cero_de_la_linea_de_comandos_no_se_confunde_con_no_decir_nada():
    """`--max 0` significa «sin tope», no «usa lo del fichero»."""
    args = Dichos(max=0)
    assert ajustes.valor(args, "max", 500) == 0


def test_sin_ligas_elegidas_vale_todo_el_catalogo():
    assert ajustes.grupos_de(ajustes.cargar("/no/existe")) is None
    con = ajustes.poner(ajustes.cargar("/no/existe"), "ligas", "grandes")
    assert ajustes.grupos_de(con) == ["grandes"]
