"""El HTTPS que alguien abre por el camino.

Esto nace de un error que llegó al usuario y que no se entiende leyéndolo:

    No llego a Telegram: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
    certificate verify failed: self-signed certificate in certificate chain>

No era el bot ni Telegram: era algo en su ordenador poniéndose en medio. Lo que
se prueba aquí es que eso se detecte, se diga con palabras y se pueda arreglar
sin bajar la guardia por defecto.

Nada de esto toca la red: el certificado se fabrica aquí mismo y el servidor
TLS se levanta en un hilo, en localhost.
"""

from __future__ import annotations

import socket
import ssl
import threading

import pytest

from cancha import tls

# ------------------------------------------------------------ de dónde salen

def test_manda_lo_que_se_pide_a_mano(monkeypatch):
    monkeypatch.setenv("CANCHA_CA_BUNDLE", "/de/la/variable.pem")
    assert tls.ruta_ca("/a/mano.pem") == "/a/mano.pem"


def test_luego_la_variable_propia(monkeypatch):
    monkeypatch.setenv("CANCHA_CA_BUNDLE", "/propia.pem")
    monkeypatch.setenv("SSL_CERT_FILE", "/de/siempre.pem")
    assert tls.ruta_ca() == "/propia.pem"


def test_y_luego_las_de_siempre(monkeypatch):
    """Quien tiene un proxy de empresa suele tenerlas puestas ya para pip."""
    monkeypatch.delenv("CANCHA_CA_BUNDLE", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", "/de/siempre.pem")
    assert tls.ruta_ca() == "/de/siempre.pem"


def test_sin_nada_no_hay_nada(monkeypatch):
    for nombre in (tls.ENV_CA, *tls.ENV_OTRAS):
        monkeypatch.delenv(nombre, raising=False)
    assert tls.ruta_ca() == ""


# ---------------------------------------------------------------- el contexto

def test_sin_nada_que_decir_no_se_monta_contexto(monkeypatch):
    """Devolver None es lo que deja a cada cliente con su camino de siempre."""
    for nombre in (tls.ENV_CA, *tls.ENV_OTRAS):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setattr(tls, "hay_truststore", lambda: False)
    assert tls.contexto() is None


def test_un_fichero_que_no_esta_se_dice(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    with pytest.raises(FileNotFoundError) as fallo:
        tls.contexto("/esto/no/existe.pem")
    assert "no está" in str(fallo.value)
    assert tls.ENV_CA in str(fallo.value), "tiene que decir de dónde salía"


def test_con_un_fichero_de_verdad_se_usa(certificado):
    contexto = tls.contexto(str(certificado["ca"]))
    assert contexto is not None
    assert contexto.verify_mode == ssl.CERT_REQUIRED, "esto no baja la guardia"


def test_sin_verificar_es_explicito_y_lo_baja_todo():
    contexto = tls.contexto(sin_verificar=True)
    assert contexto.verify_mode == ssl.CERT_NONE
    assert contexto.check_hostname is False


# ------------------------------------------------------- reconocer el fallo

def test_reconoce_el_error_que_llego_al_usuario():
    assert tls.es_de_certificado(
        "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify "
        "failed: self-signed certificate in certificate chain (_ssl.c:1081)>")


def test_reconoce_el_del_emisor_que_falta():
    assert tls.es_de_certificado("unable to get local issuer certificate")


def test_no_confunde_otros_fallos_de_red():
    assert not tls.es_de_certificado("[Errno 111] Connection refused")
    assert not tls.es_de_certificado("timed out")


def test_la_explicacion_dice_qué_hacer():
    texto = tls.explicar("api.telegram.org")
    assert "api.telegram.org" in texto
    assert "antivirus" in texto
    assert "truststore" in texto, "el arreglo que funciona sin tocar nada"
    assert "red.ca_bundle" in texto
    assert "cancha doctor --tls" in texto


def test_la_explicacion_viene_ya_partida():
    """La imprimen tres sitios; partirla en cada uno descolocaba la numeración."""
    lineas = tls.explicar("x", ancho=60).splitlines()
    assert max(len(x) for x in lineas) <= 60
    assert any(x.startswith("  1. ") for x in lineas)
    assert any(x.startswith("     ") for x in lineas), "la continuación va sangrada"


# ----------------------------------------------- quién se ha puesto en medio

def test_dice_quien_firma_el_certificado(servidor_tls, certificado):
    """El caso entero, contra un TLS de verdad con un certificado nuestro."""
    host, puerto = servidor_tls
    datos = tls.inspeccionar(host, puerto)
    assert datos["interceptado"] is True, "el certificado no lo firma nadie conocido"
    assert datos["quien"] == certificado["quien"]
    assert certificado["quien"] in datos["nota"]


def test_con_el_certificado_bueno_no_hay_nadie_en_medio(servidor_tls, certificado):
    host, puerto = servidor_tls
    datos = tls.inspeccionar(host, puerto)
    assert datos["interceptado"] is True

    # Y ahora confiando en quien lo firma, que es el arreglo del usuario.
    import os
    os.environ["CANCHA_CA_BUNDLE"] = str(certificado["ca"])
    try:
        datos = tls.inspeccionar(host, puerto)
    finally:
        del os.environ["CANCHA_CA_BUNDLE"]
    assert datos["interceptado"] is False
    assert "Nadie se ha puesto en medio" in datos["nota"]


def test_un_fichero_de_certificados_roto_se_dice(tmp_path, monkeypatch):
    vacio = tmp_path / "vacio.pem"
    vacio.write_text("")
    monkeypatch.setenv("CANCHA_CA_BUNDLE", str(vacio))
    datos = tls.inspeccionar("localhost", 1)
    assert datos["interceptado"] is None
    assert "no vale" in datos["nota"], datos["nota"]


def test_si_no_se_llega_no_se_inventa_nada():
    datos = tls.inspeccionar("localhost", 1, timeout=2)
    assert datos["interceptado"] is None
    assert "No llego a localhost" in datos["nota"]


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def certificado(tmp_path_factory):
    """Un certificado autofirmado, hecho aquí. Sin dependencias ni red.

    Es exactamente lo que presenta un antivirus o un proxy que abre el HTTPS:
    un certificado para el host que pidas, firmado por alguien que tu sistema
    no conoce.
    """
    import subprocess

    carpeta = tmp_path_factory.mktemp("tls")
    quien = "Antivirus de Prueba CA"
    clave, cert = carpeta / "clave.pem", carpeta / "cert.pem"
    orden = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(clave), "-out", str(cert), "-days", "2",
        "-subj", f"/CN={quien}", "-addext", "subjectAltName=DNS:localhost",
    ]
    hecho = subprocess.run(orden, capture_output=True)
    if hecho.returncode != 0:
        pytest.skip(f"sin openssl para fabricar el certificado: {hecho.stderr[:200]}")
    return {"clave": clave, "cert": cert, "ca": cert, "quien": quien}


@pytest.fixture(scope="module")
def servidor_tls(certificado):
    """Un TLS mínimo en localhost que presenta ese certificado."""
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(str(certificado["cert"]), str(certificado["clave"]))
    escucha = socket.socket()
    escucha.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    escucha.bind(("127.0.0.1", 0))
    escucha.listen(8)
    puerto = escucha.getsockname()[1]
    parar = threading.Event()

    def atender() -> None:
        while not parar.is_set():
            try:
                cliente, _ = escucha.accept()
            except OSError:
                return
            try:
                with contexto.wrap_socket(cliente, server_side=True) as tls_sock:
                    tls_sock.recv(1024)
            except OSError:
                pass  # al cliente solo le interesa el certificado, no la charla
            finally:
                cliente.close()

    hilo = threading.Thread(target=atender, daemon=True)
    hilo.start()
    yield "localhost", puerto
    parar.set()
    escucha.close()


# ------------------------------------------- que llegue a donde tiene que llegar

def test_el_transporte_explica_el_fallo_en_vez_de_soltar_el_de_openssl():
    """«self-signed certificate in certificate chain» no dice qué hacer."""
    import urllib.error

    from cancha.errors import TransportError
    from cancha.transport import UrllibTransport

    def revienta(*_a, **_k):
        raise urllib.error.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "self-signed certificate in certificate chain")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = revienta
    try:
        with pytest.raises(TransportError) as fallo:
            UrllibTransport().request("GET", "https://api.sofascore.com/x", {})
    finally:
        urllib.request.urlopen = original
    dicho = str(fallo.value)
    assert "api.sofascore.com" in dicho
    assert "antivirus" in dicho, "hay que decir qué es lo que pasa"
    assert "truststore" in dicho, "y cómo se arregla"


def test_un_fallo_de_red_normal_no_se_explica_de_mas():
    import urllib.error

    from cancha.errors import TransportError
    from cancha.transport import UrllibTransport

    def revienta(*_a, **_k):
        raise urllib.error.URLError("[Errno 111] Connection refused")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = revienta
    try:
        with pytest.raises(TransportError) as fallo:
            UrllibTransport().request("GET", "https://api.sofascore.com/x", {})
    finally:
        urllib.request.urlopen = original
    assert "antivirus" not in str(fallo.value)


def test_el_transporte_recibe_el_contexto(certificado):
    """Que el ajuste llegue de verdad al sitio donde se usa."""
    from cancha.transport import UrllibTransport, build_transport

    transporte = build_transport("urllib", ca_bundle=str(certificado["ca"]))
    assert isinstance(transporte, UrllibTransport)
    assert transporte.contexto is not None
    assert transporte.contexto.verify_mode == ssl.CERT_REQUIRED


def test_curl_no_recibe_un_contexto_sino_una_ruta(monkeypatch, certificado):
    """curl_cffi lleva sus propios certificados y no entiende un SSLContext."""
    from cancha import transport as modulo

    vistos = {}
    monkeypatch.setattr(modulo.CurlTransport, "__init__",
                        lambda self, timeout=15.0, impersonate=None, session=None,
                        verificar=None: vistos.update(verificar=verificar))
    modulo.build_transport("curl", ca_bundle=str(certificado["ca"]))
    assert vistos["verificar"] == str(certificado["ca"])


def test_sin_verificar_le_llega_a_curl_como_False(monkeypatch):
    from cancha import transport as modulo

    vistos = {}
    monkeypatch.setattr(modulo.CurlTransport, "__init__",
                        lambda self, timeout=15.0, impersonate=None, session=None,
                        verificar=None: vistos.update(verificar=verificar))
    modulo.build_transport("curl", sin_verificar=True)
    assert vistos["verificar"] is False


def test_el_bot_explica_el_fallo_de_certificado():
    import urllib.error

    from cancha.telegrama import TelegramNoDisponible, _pedir_http

    def revienta(*_a, **_k):
        raise urllib.error.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in "
            "certificate chain")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = revienta
    try:
        with pytest.raises(TelegramNoDisponible) as fallo:
            _pedir_http("https://api.telegram.org/botx/getMe")
    finally:
        urllib.request.urlopen = original
    assert "api.telegram.org" in str(fallo.value)
    assert "truststore" in str(fallo.value)


def test_el_analista_de_la_nube_tambien():
    import urllib.error

    from cancha.analista import OllamaNoDisponible, _pedir_http

    def revienta(*_a, **_k):
        raise urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] bla")

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = revienta
    try:
        with pytest.raises(OllamaNoDisponible) as fallo:
            _pedir_http("https://ollama.com/api/chat", {"x": 1})
    finally:
        urllib.request.urlopen = original
    assert "antivirus" in str(fallo.value)


def test_los_ajustes_avisan_de_lo_que_hay_puesto():
    import copy

    from cancha.ajustes import POR_DEFECTO, poner, revisar

    limpios = copy.deepcopy(POR_DEFECTO)
    assert revisar(limpios) == []

    puestos = poner(limpios, "red.ca_bundle", "/esto/no/existe.pem")
    assert any("no está" in x for x in revisar(puestos))

    flojos = poner(limpios, "red.sin_verificar", "si")
    avisos = revisar(flojos)
    assert any("sin comprobar con quién hablas" in x for x in avisos)
    assert any("token del bot" in x for x in avisos), "hay que decir qué se arriesga"


def test_el_bot_coge_los_certificados_sin_reiniciar(cliente, tmp_path):
    from cancha.sesion import Sesion
    from cancha.telegrama import Bot

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "tls.db"))
    bot = Bot(token="x", sesion=sesion, pedir=lambda *a, **k: {"ok": True})
    try:
        bot.releer = lambda: {"telegram": {"token": "x", "chats": []},
                              "red": {"ca_bundle": "/nuevo.pem", "sin_verificar": False}}
        cambios = bot.refrescar()
        assert bot.ca_bundle == "/nuevo.pem"
        assert any("certificados" in x for x in cambios)
        assert bot._contexto is tls.SIN_MONTAR, "el contexto se rehace en la siguiente"
    finally:
        sesion.close()


# ------------------------------------------------- desde el terminal y el móvil

def test_doctor_tls_dice_lo_que_encuentra(capsys):
    """Contra un puerto donde no hay nadie: ni se inventa nada ni revienta."""
    from cancha import cli

    assert cli.main(["doctor", "--tls", "--host", "localhost"]) == 0
    dicho = capsys.readouterr().out
    assert "localhost" in dicho
    assert "certificados" in dicho


def test_doctor_tls_contra_un_certificado_que_nadie_conoce(servidor_tls, capsys,
                                                           certificado):
    """No hay manera de pasarle el puerto, así que se prueba la función."""
    from cancha.diagnostico import probar_tls

    host, puerto = servidor_tls
    datos = probar_tls(host)          # 443: no hay nadie, y lo dice
    assert datos["interceptado"] is None
    assert "lectura" in datos, "también dice con qué certificados se habla"
    del puerto, certificado, capsys


def test_el_estado_de_los_certificados_se_lee_en_una_linea(monkeypatch):
    from cancha.diagnostico import estado_tls

    for nombre in (tls.ENV_CA, *tls.ENV_OTRAS):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setattr(tls, "hay_truststore", lambda: False)
    d = estado_tls()
    assert d["ca_bundle"] == ""
    assert "truststore" in d["lectura"], "sin nada, se recomienda lo que arregla"

    monkeypatch.setattr(tls, "hay_truststore", lambda: True)
    assert "almacén del sistema" in estado_tls()["lectura"]


def test_sin_verificar_sale_en_el_diagnostico():
    from cancha.config import Settings
    from cancha.diagnostico import estado_tls

    d = estado_tls(Settings(sin_verificar=True))
    assert d["sin_verificar"] is True
    assert "⚠" in d["lectura"]
