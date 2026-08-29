"""Sacar la cookie de lo que copies del navegador.

Buscarla a mano entre cientos de peticiones, en las cabeceras de solicitud (no
las de respuesta), es donde se atasca todo el mundo. Estos casos son los tres
formatos que da el navegador de un clic.
"""

from __future__ import annotations

import pytest

from sofascore import cli
from sofascore.auth import cookie_desde_navegador

CURL_BASH = (
    "curl 'https://api.sofascore.com/api/v1/event/16416311' \\\n"
    "  -H 'accept: */*' \\\n"
    "  -H 'accept-language: es-ES,es;q=0.9' \\\n"
    "  -H 'cookie: _ga=GA1.1.998; sofa_session=abc123; _cc_id=zz' \\\n"
    "  -H 'referer: https://www.sofascore.com/'"
)

CURL_CMD = (
    'curl "https://api.sofascore.com/api/v1/event/1" ^\n'
    '  -H "accept: */*" ^\n'
    '  -H "Cookie: _ga=GA1.1.998; sofa_session=abc123" ^\n'
    '  -H "referer: https://www.sofascore.com/"'
)

POWERSHELL = (
    '$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession\n'
    '$session.Cookies.Add((New-Object System.Net.Cookie("_ga", "GA1.1.998", "/", '
    '".sofascore.com")))\n'
    '$session.Cookies.Add((New-Object System.Net.Cookie("sofa_session", "abc123", "/", '
    '".sofascore.com")))'
)


def test_curl_de_bash():
    assert cookie_desde_navegador(CURL_BASH) == "_ga=GA1.1.998; sofa_session=abc123; _cc_id=zz"


def test_curl_de_cmd_con_sus_acentos_circunflejos():
    assert cookie_desde_navegador(CURL_CMD) == "_ga=GA1.1.998; sofa_session=abc123"


def test_powershell_las_añade_una_a_una():
    assert cookie_desde_navegador(POWERSHELL) == "_ga=GA1.1.998; sofa_session=abc123"


def test_document_cookie_pegado_tal_cual():
    pegado = "_ga=GA1.1.5; sofa_session=zzz"
    assert cookie_desde_navegador(pegado) == pegado


def test_curl_con_la_bandera_corta():
    assert cookie_desde_navegador("curl https://x -b 'a=1; b=2'") == "a=1; b=2"


def test_no_se_confunde_con_otras_cabeceras():
    curl = "curl https://x -H 'referer: https://www.sofascore.com/' -H 'cookie: real=si'"
    assert cookie_desde_navegador(curl) == "real=si"


@pytest.mark.parametrize("texto", ["", "   ", None, "no hay nada de esto aquí",
                                   "curl https://x -H 'accept: */*'"])
def test_sin_cookie_devuelve_vacio(texto):
    assert cookie_desde_navegador(texto) == ""


# ------------------------------------------------------------------ el comando

def test_el_comando_la_encuentra_y_la_enseña(tmp_path, capsys):
    fichero = tmp_path / "copiado.txt"
    fichero.write_text(CURL_BASH, encoding="utf-8")
    assert cli.main(["cookie", "--file", str(fichero)]) == 0
    salida = capsys.readouterr().out
    assert "3 valores" in salida
    assert "SOFA_PLUS_COOKIE=_ga=GA1.1.998; sofa_session=abc123; _cc_id=zz" in salida


def test_el_comando_la_escribe_en_el_env(tmp_path, capsys):
    fichero = tmp_path / "copiado.txt"
    fichero.write_text(CURL_BASH, encoding="utf-8")
    destino = tmp_path / ".env"
    assert cli.main(["cookie", "--file", str(fichero), "--save", "--env", str(destino)]) == 0
    assert "SOFA_PLUS_COOKIE=_ga=GA1.1.998" in destino.read_text(encoding="utf-8")
    assert "añadida" in capsys.readouterr().out


def test_guardar_no_se_lleva_por_delante_lo_que_ya_habia(tmp_path):
    fichero = tmp_path / "copiado.txt"
    fichero.write_text(CURL_BASH, encoding="utf-8")
    destino = tmp_path / ".env"
    destino.write_text(
        "SOFA_RATE_LIMIT=2\nSOFA_PLUS_COOKIE=vieja=si\nSOFA_LANGUAGE=es\n", encoding="utf-8"
    )
    assert cli.main(["cookie", "--file", str(fichero), "--save", "--env", str(destino)]) == 0
    contenido = destino.read_text(encoding="utf-8")
    assert "SOFA_RATE_LIMIT=2" in contenido
    assert "SOFA_LANGUAGE=es" in contenido
    assert "vieja=si" not in contenido
    assert contenido.count("SOFA_PLUS_COOKIE=") == 1


def test_si_no_hay_cookie_explica_las_tres_formas(tmp_path, capsys):
    fichero = tmp_path / "copiado.txt"
    fichero.write_text("esto no es una petición", encoding="utf-8")
    assert cli.main(["cookie", "--file", str(fichero)]) == 1
    salida = capsys.readouterr().out
    assert "Copiar como cURL" in salida
    assert "document.cookie" in salida
