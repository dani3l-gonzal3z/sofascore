"""Cuando algo abre tu HTTPS por el camino.

Un día el bot dice esto y no se entiende nada:

    No llego a Telegram: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
    certificate verify failed: self-signed certificate in certificate chain>

No es un fallo del bot ni de Telegram. Es que **algo entre tu ordenador y la
red está abriendo el HTTPS**: se pone en medio, descifra, vuelve a cifrar con
un certificado suyo y te lo presenta. Un antivirus que «revisa webs seguras»
(Kaspersky, ESET, Avast, Bitdefender), el proxy de una empresa o un colegio
(Zscaler, Netskope), o un cliente de VPN. Python mira quién firma el
certificado, no lo conoce, y corta. Y hace bien: eso es exactamente lo que
tiene que hacer cuando alguien se pone en medio.

Así que aquí hay tres cosas:

* **Averiguar quién es.** ``inspeccionar`` se asoma al certificado que te están
  presentando y saca el nombre de quien lo firma. Casi siempre te dice el
  nombre del antivirus o del proxy en su primera línea, y con eso ya se sabe
  qué hacer.
* **Poder confiar en él a propósito.** ``contexto`` acepta un fichero de
  certificados —el de tu empresa, el de tu antivirus— y, si está instalado
  ``truststore``, usa directamente el almacén de certificados de Windows o de
  macOS, que es donde esos programas dejan el suyo.
* **Explicarlo.** ``explicar`` escribe en castellano qué ha pasado y qué se
  puede hacer, que es lo que se quiere leer a las once de la noche.

Lo que **no** se hace es desactivar la comprobación por nuestra cuenta. Hay un
ajuste para eso, porque a veces no hay otra, pero lo tienes que poner tú y va
con su aviso cada vez.
"""

from __future__ import annotations

import os
import socket
import ssl
import textwrap

#: Un fichero de certificados propio, sin tocar los ajustes.
ENV_CA = "CANCHA_CA_BUNDLE"
#: Las de toda la vida, que ya usan pip, requests y media internet. Si las
#: tienes puestas para lo demás, aquí valen igual.
ENV_OTRAS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
#: «Todavía no lo he montado», que no es lo mismo que «no hay ninguno»: el
#: contexto por defecto **es** ``None``, así que hace falta un tercer valor
#: para poder montarlo tarde y una sola vez.
SIN_MONTAR = object()
#: Lo que dice OpenSSL cuando alguien se ha puesto en medio.
PISTAS = ("CERTIFICATE_VERIFY_FAILED", "self-signed certificate",
          "unable to get local issuer", "self signed certificate")


def ruta_ca(dada: str | None = None) -> str:
    """El fichero de certificados que hay que usar, o vacío si no hay ninguno.

    Manda lo que se pida a mano; luego ``CANCHA_CA_BUNDLE``; luego las
    variables de siempre, porque quien tiene un proxy de empresa suele tenerlas
    ya puestas para que funcione pip.
    """
    if dada and str(dada).strip():
        return str(dada).strip()
    for nombre in (ENV_CA, *ENV_OTRAS):
        valor = (os.environ.get(nombre) or "").strip()
        if valor:
            return valor
    return ""


def hay_truststore() -> bool:
    """¿Está instalado ``truststore``?

    Es el arreglo bueno en Windows y en macOS: hace que Python use el almacén
    de certificados **del sistema**, que es donde el antivirus o el proxy de la
    empresa han dejado el suyo al instalarse. Con eso, lo que el sistema ya
    considera de fiar pasa a serlo también aquí, sin tener que exportar nada.
    """
    try:
        import truststore  # noqa: F401
    except Exception:  # noqa: BLE001 - no estar instalado es lo normal
        return False
    return True


def contexto(ca_bundle: str | None = None,
             sin_verificar: bool = False) -> ssl.SSLContext | None:
    """El contexto TLS con el que habla este programa.

    Devuelve ``None`` cuando no hay nada que cambiar, para que cada cliente use
    su camino de siempre y esto no altere nada donde no hace falta.
    """
    if sin_verificar:
        flojo = ssl.create_default_context()
        flojo.check_hostname = False
        flojo.verify_mode = ssl.CERT_NONE
        return flojo
    ruta = ruta_ca(ca_bundle)
    if ruta:
        if not os.path.exists(ruta):
            raise FileNotFoundError(
                f"El fichero de certificados «{ruta}» no está. Es el que dice el "
                f"ajuste red.ca_bundle o la variable {ENV_CA}.")
        return ssl.create_default_context(cafile=ruta)
    if hay_truststore():
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return None


# ------------------------------------------------------- quién se ha puesto ahí

#: Los identificadores de «nombre común» y «organización» dentro de un
#: certificado, en DER. Buscarlos a pelo es un atajo, pero es un atajo cerrado:
#: el nombre de quien firma va **antes** que el del titular en el certificado
#: (así lo manda el formato), así que el primero que aparece es el que
#: buscamos. Y si algo no cuadra, se devuelve vacío y se dice que no se sabe:
#: esto es para explicarle algo a alguien, no para decidir en qué confiar.
OID_CN = bytes.fromhex("0603550403")
OID_O = bytes.fromhex("060355040A")


def _texto_tras(der: bytes, oid: bytes) -> str:
    """El texto que sigue a un identificador dentro del DER, si se puede leer."""
    donde = der.find(oid)
    if donde < 0:
        return ""
    i = donde + len(oid)
    if i + 2 > len(der):
        return ""
    largo = der[i + 1]
    if largo & 0x80 or i + 2 + largo > len(der):  # longitud larga: no nos metemos
        return ""
    try:
        return der[i + 2:i + 2 + largo].decode("utf-8").strip()
    except UnicodeDecodeError:
        return ""


def inspeccionar(host: str = "api.telegram.org", puerto: int = 443,
                 timeout: float = 8.0) -> dict:
    """Quién firma el certificado que te presentan al hablar con ``host``.

    Se mira **sin** verificar nada a propósito: la pregunta no es «¿me fío?»
    —ya sabemos que no— sino «¿quién es?». Que es lo único que hace falta para
    saber si tienes un antivirus revisando webs o algo que no debería estar.
    """
    salida: dict = {"host": host, "interceptado": None, "quien": "", "nota": "",
                    "ca_bundle": ruta_ca(), "truststore": hay_truststore()}
    try:
        seguro = contexto() or ssl.create_default_context()
    except (OSError, ssl.SSLError) as exc:
        # El fichero de certificados no sirve: está vacío, no es un .pem o no
        # se puede leer. Se dice así, porque si no el error que sale es de
        # OpenSSL y no se parece en nada al problema.
        salida["nota"] = (f"El fichero de certificados «{ruta_ca()}» no vale: {exc}. "
                          "Tiene que ser un .pem con uno o más certificados.")
        return salida
    try:
        with socket.create_connection((host, puerto), timeout=timeout) as cruda, \
                seguro.wrap_socket(cruda, server_hostname=host):
            salida["interceptado"] = False
            salida["nota"] = ("El certificado es de quien dice ser. "
                              "Nadie se ha puesto en medio.")
            return salida
    except ssl.SSLCertVerificationError as exc:
        salida["interceptado"] = True
        salida["error"] = str(exc)
    except OSError as exc:
        salida["nota"] = f"No llego a {host}: {exc}"
        return salida

    # Está interceptado: ahora, sin verificar, a ver de quién es la firma.
    try:
        flojo = ssl.create_default_context()
        flojo.check_hostname = False
        flojo.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, puerto), timeout=timeout) as cruda, \
                flojo.wrap_socket(cruda, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True) or b""
    except OSError as exc:
        salida["nota"] = f"Está interceptado, pero no he podido ver el certificado: {exc}"
        return salida
    quien = _texto_tras(der, OID_CN) or _texto_tras(der, OID_O)
    salida["quien"] = quien
    salida["nota"] = (
        f"Quien firma el certificado se llama «{quien}». Eso es lo que está "
        "abriendo tu HTTPS." if quien else
        "No he podido sacar el nombre de quien firma el certificado.")
    return salida


# --------------------------------------------------------------------- decirlo

def es_de_certificado(exc: BaseException | str) -> bool:
    """¿Este fallo es de los de certificado? Para no explicar de más."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    texto = str(exc)
    return any(pista in texto for pista in PISTAS)


def explicar(host: str = "", ancho: int = 72) -> str:
    """Qué ha pasado y qué hacer, ya partido en líneas que se pueden leer.

    Va partido aquí, y no en cada sitio que lo imprime, porque lo imprimen
    tres: el terminal, la página y un mensaje de Telegram. Partirlo en cada uno
    acababa con la numeración descolocada.

    Las órdenes van en su propia línea y **sin** partir: una orden cortada por
    la mitad no se puede copiar, y esto está para copiarlo.
    """
    donde = f" con {host}" if host else ""
    #: (sangría, texto, ¿se puede partir?)
    partes: list[tuple[str, str, bool]] = [
        ("", f"Algo está abriendo tu HTTPS{donde}: se pone en medio, descifra y te "
             "presenta un certificado suyo, y Python no conoce a quien lo firma. "
             "Suele ser un antivirus que «revisa webs seguras», el proxy de una "
             "empresa o de un colegio, o un cliente de VPN.", True),
        ("", "Para saber quién es:", True),
        ("  ", "cancha doctor --tls", False),
        ("  ", "en Windows:  .\\cancha.bat doctor --tls", False),
        ("", "Y para que funcione, de mejor a peor:", True),
        ("  1. ", "pip install truststore", False),
        ("     ", "Hace que Python use el almacén de certificados del sistema, que "
                  "es donde esos programas dejan el suyo al instalarse. Suele "
                  "arreglarlo sin tocar nada más.", True),
        ("  2. ", "Exporta el certificado de quien firma a un fichero .pem y di "
                  "dónde está:", True),
        ("     ", "cancha ajustes red.ca_bundle=C:\\ruta\\al\\certificado.pem", False),
        ("  3. ", "En tu antivirus, quita la revisión de webs seguras: suele "
                  "llamarse «análisis HTTPS» o «escaneo SSL».", True),
        ("  4. ", "Si no hay otra y sabes lo que hay en medio:", True),
        ("     ", "cancha ajustes red.sin_verificar=si", False),
        ("     ", "Deja de comprobar con quién hablas, y eso incluye a quien se "
                  "ponga en medio. Va con aviso cada vez.", True),
    ]
    lineas: list[str] = []
    for sangria, texto, se_parte in partes:
        # Un apartado nuevo empieza sin sangría, o con el número de la lista.
        # Lo que va sangrado a secas es continuación del anterior y va pegado.
        if lineas and (sangria == "" or sangria.endswith(". ")):
            lineas.append("")
        if se_parte:
            lineas += textwrap.wrap(texto, ancho, initial_indent=sangria,
                                    subsequent_indent=" " * len(sangria)) or [""]
        else:
            lineas.append(sangria + texto)
    return "\n".join(lineas)


__all__ = ["ENV_CA", "SIN_MONTAR", "contexto", "es_de_certificado", "explicar",
           "hay_truststore", "inspeccionar", "ruta_ca"]
