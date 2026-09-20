"""Cómo se lanza esto, que resultó ser la mitad de los problemas reales.

Los dos que llegaron al usuario, los dos en Windows y los dos sin ser errores
del programa:

* ``python cancha doctor`` —lo que sale escribir cuando tienes la carpeta
  delante— reventaba con «attempted relative import with no known parent
  package», que no dice absolutamente nada de lo que hay que hacer.
* ``cancha.bat`` se hace su propio entorno en ``.venv``, así que un
  ``pip install truststore`` escrito en PowerShell iba al Python del sistema y
  el programa no lo veía. El ``.bat`` tiene que instalar lo que hace falta él,
  y completar el entorno que ya estuviera hecho.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _lanzar(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *argumentos, "--help"],
                          capture_output=True, text=True, cwd=RAIZ, timeout=120)


def test_como_modulo():
    hecho = _lanzar("-m", "cancha")
    assert hecho.returncode == 0, hecho.stderr
    assert "cancha" in hecho.stdout


def test_como_carpeta():
    """`python cancha` es lo que se escribe teniendo la carpeta delante."""
    hecho = _lanzar("cancha")
    assert hecho.returncode == 0, hecho.stderr
    assert "attempted relative import" not in hecho.stderr
    assert "cancha" in hecho.stdout


def test_como_fichero_suelto():
    hecho = _lanzar(str(Path("cancha") / "__main__.py"))
    assert hecho.returncode == 0, hecho.stderr
    assert "cancha" in hecho.stdout


# ------------------------------------------------------------------ el .bat

def _bat() -> str:
    return (RAIZ / "cancha.bat").read_text(encoding="utf-8", errors="replace")


def test_el_bat_instala_los_certificados_del_sistema():
    """`truststore` es el arreglo del HTTPS interceptado, y esto es Windows."""
    contenido = _bat()
    assert '-e ".[curl,tls]"' in contenido, "el entorno tiene que traerlo hecho"


def test_el_bat_completa_un_entorno_que_ya_existiera():
    """Sin esto, quien ya tenía el .venv hecho se queda sin lo nuevo y no lo sabe."""
    contenido = _bat()
    assert "SELLO" in contenido and "MARCA" in contenido
    assert ".cancha-extras" in contenido
    # El sello tiene que nombrar lo que se instala, o no sirve de nada.
    assert "set \"SELLO=curl+tls\"" in contenido
    assert '".[curl,tls]"' in contenido


def test_el_bat_avisa_de_que_pip_va_a_otro_python():
    contenido = _bat()
    assert "Python del sistema" in contenido
    assert ".venv\\Scripts\\python.exe -m pip install" in contenido


def test_el_bat_pasa_los_argumentos_tal_cual():
    contenido = _bat()
    assert "-m cancha %COMANDO% %*" in contenido


# ------------------------------------------ qué Python es, que no es evidente

def test_el_diagnostico_dice_que_python_esta_usando():
    """`pip install algo` y «lo ve cancha» no son lo mismo, y hay que poder verlo."""
    from cancha.diagnostico import estado_tls

    assert estado_tls()["python"] == sys.executable


def test_el_doctor_lo_imprime(capsys):
    from cancha import cli

    cli.main(["doctor", "--tls", "--host", "localhost"])
    assert sys.executable in capsys.readouterr().out
