"""Capa de transporte HTTP.

Solo biblioteca estándar (``urllib``), para que el framework funcione nada más
descargarlo. El transporte es intercambiable: cualquier objeto con un método
``request(method, url, headers) -> Response`` sirve, lo que permite tests sin
red (:class:`FakeTransport`) o un backend con ``httpx``/``requests`` si lo
prefieres.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import TransportError


@dataclass
class Response:
    """Respuesta HTTP mínima."""

    status: int
    url: str
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError(f"Respuesta no-JSON de {self.url}: {exc}") from exc

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Transport(Protocol):
    """Contrato que debe cumplir cualquier transporte."""

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:  # pragma: no cover
        ...


class UrllibTransport:
    """Transporte por defecto, basado en ``urllib.request`` (sin dependencias)."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        peticion = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                return Response(
                    status=respuesta.status,
                    url=url,
                    body=respuesta.read(),
                    headers={k.lower(): v for k, v in respuesta.headers.items()},
                )
        except urllib.error.HTTPError as exc:  # 4xx / 5xx: es una respuesta válida
            cuerpo = b""
            try:
                cuerpo = exc.read()
            except Exception:  # noqa: BLE001 - el cuerpo del error es opcional
                pass
            return Response(
                status=exc.code,
                url=url,
                body=cuerpo,
                headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            )
        except urllib.error.URLError as exc:
            raise TransportError(f"No se pudo conectar con {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TransportError(f"Timeout ({self.timeout}s) pidiendo {url}") from exc


class HttpxTransport:
    """Transporte opcional sobre ``httpx`` (HTTP/2, conexiones reutilizadas)."""

    def __init__(self, timeout: float = 15.0, client: Any = None) -> None:
        if client is None:
            import httpx  # import perezoso: httpx es opcional

            client = httpx.Client(timeout=timeout, follow_redirects=True, http2=False)
        self._client = client

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        import httpx

        try:
            r = self._client.request(method, url, headers=headers)
        except httpx.HTTPError as exc:
            raise TransportError(f"No se pudo conectar con {url}: {exc}") from exc
        return Response(
            status=r.status_code,
            url=url,
            body=r.content,
            headers={k.lower(): v for k, v in r.headers.items()},
        )

    def close(self) -> None:
        self._client.close()


class CurlTransport:
    """Transporte que imita el handshake TLS de Chrome (``curl_cffi``).

    Sofascore está detrás de Cloudflare, y Cloudflare no mira solo las
    cabeceras: mira la **huella del handshake TLS**. Una petición de ``urllib``
    con cabeceras de Chrome canta muchísimo —el TLS es de Python— y se lleva un
    403 aunque las cabeceras sean perfectas.

    ``curl_cffi`` habla TLS *como* Chrome, así que la huella cuadra con lo que
    dicen las cabeceras. Es el mismo camino que toman todas las librerías que
    hablan con esta API: ``pysofascore`` usa esto mismo, ``soccerdata`` usa
    ``tls_requests``, y ``ScraperFC`` y ``sofascore-wrapper`` llegan a levantar
    un navegador entero.

    Es una dependencia **opcional**: ``pip install curl_cffi``. Sin ella el
    framework sigue funcionando con ``urllib``, que sirve de sobra si pides
    desde una red que no esté bloqueada.
    """

    #: Perfil de navegador a imitar. ``chrome`` sigue al último Chrome estable.
    DEFAULT_IMPERSONATE = "chrome"

    def __init__(self, timeout: float = 15.0, impersonate: str | None = None,
                 session: Any = None) -> None:
        self.timeout = timeout
        self.impersonate = impersonate or self.DEFAULT_IMPERSONATE
        if session is None:
            from curl_cffi import requests as curl_requests  # import perezoso

            session = curl_requests.Session(impersonate=self.impersonate, timeout=timeout)
        self._session = session

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        # El User-Agent lo pone el perfil imitado: mandar el nuestro lo
        # contradiría y volvería a delatarnos.
        limpias = {k: v for k, v in headers.items() if k.lower() != "user-agent"}
        try:
            r = self._session.request(method, url, headers=limpias)
        except Exception as exc:  # noqa: BLE001 - curl_cffi tiene su propia jerarquía
            raise TransportError(f"No se pudo conectar con {url}: {exc}") from exc
        return Response(
            status=r.status_code,
            url=url,
            body=r.content,
            headers={k.lower(): v for k, v in dict(r.headers).items()},
        )

    def close(self) -> None:
        cerrar = getattr(self._session, "close", None)
        if callable(cerrar):
            cerrar()


class CallableTransport:
    """Envuelve cualquier función ``(method, url, headers) -> (status, bytes)``.

    Es la puerta de atrás para los casos duros: si algún día Sofascore te
    responde 403 desde los dos hosts, aquí puedes enchufar lo que sea que sí
    pase —``curl_cffi`` imitando a Chrome, una sesión de ``playwright``, un
    proxy tuyo— sin tocar nada más del framework::

        from curl_cffi import requests as cr

        sesion = cr.Session(impersonate="chrome")
        transporte = CallableTransport(
            lambda m, url, h: (sesion.request(m, url, headers=h).status_code,
                               sesion.request(m, url, headers=h).content)
        )
        cliente = SofascoreClient(transport=transporte)

    Esas librerías son dependencias opcionales tuyas: el framework sigue sin
    necesitar ninguna.
    """

    def __init__(self, fn) -> None:
        self._fn = fn

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        try:
            estado, cuerpo = self._fn(method, url, headers)
        except Exception as exc:  # noqa: BLE001 - lo que falle ahí es cosa del transporte
            raise TransportError(f"No se pudo conectar con {url}: {exc}") from exc
        if isinstance(cuerpo, str):
            cuerpo = cuerpo.encode("utf-8")
        return Response(status=int(estado), url=url, body=cuerpo or b"")


class FakeTransport:
    """Transporte de mentira para tests y demos sin red.

    ``routes`` mapea *fragmentos* de URL a la carga útil que debe devolverse.
    Gana el fragmento más largo que encaje, para que ``/event/1`` no se coma las
    peticiones a ``/event/1/statistics``. El valor puede ser un dict/lista (se
    serializa a JSON), un código de estado, un :class:`Response` o un callable
    ``(url) -> Response``.
    """

    def __init__(self, routes: dict[str, Any] | None = None, default_status: int = 404) -> None:
        self.routes: dict[str, Any] = routes or {}
        self.default_status = default_status
        #: Historial de URLs pedidas, útil para asertar en tests.
        self.calls: list[str] = []

    def add(self, fragmento: str, payload: Any) -> "FakeTransport":
        self.routes[fragmento] = payload
        return self

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        self.calls.append(url)
        encajes = [f for f in self.routes if f in url]
        if encajes:
            mejor = max(encajes, key=len)
            return self._build(url, self.routes[mejor])
        return Response(status=self.default_status, url=url, body=b'{"error":"not found"}')

    @staticmethod
    def _build(url: str, payload: Any) -> Response:
        if isinstance(payload, Response):
            return payload
        if isinstance(payload, int):
            return Response(status=payload, url=url, body=b"{}")
        if callable(payload):
            resultado = payload(url)
            return resultado if isinstance(resultado, Response) else Response(
                status=200, url=url, body=json.dumps(resultado).encode("utf-8")
            )
        return Response(status=200, url=url, body=json.dumps(payload).encode("utf-8"))


#: Orden de preferencia de ``auto``: primero el que más lejos llega.
AUTO_ORDER = ("curl", "httpx", "urllib")


def transport_disponible(kind: str) -> bool:
    """¿Está instalado lo que hace falta para ese transporte?"""
    modulos = {"curl": "curl_cffi", "httpx": "httpx", "urllib": None}
    modulo = modulos.get(kind, "")
    if modulo is None:
        return True
    if not modulo:
        return False
    try:
        __import__(modulo)
    except ImportError:
        return False
    return True


def build_transport(kind: str = "auto", timeout: float = 15.0) -> Transport:
    """Devuelve el transporte pedido: ``curl``, ``httpx``, ``urllib`` o ``auto``.

    ``auto`` coge el mejor de los que estén instalados. ``curl`` va primero
    porque es el único que atraviesa el anti-bot de Cloudflare: imita el
    handshake TLS de Chrome, no solo sus cabeceras.
    """
    constructores = {
        "curl": lambda: CurlTransport(timeout=timeout),
        "httpx": lambda: HttpxTransport(timeout=timeout),
        "urllib": lambda: UrllibTransport(timeout=timeout),
    }
    if kind in constructores:
        return constructores[kind]()
    if kind != "auto":
        raise ValueError(
            f"Transporte desconocido: '{kind}'. Usa: auto, {', '.join(constructores)}"
        )
    for candidato in AUTO_ORDER:
        if transport_disponible(candidato):
            return constructores[candidato]()
    return UrllibTransport(timeout=timeout)


__all__ = [
    "Response",
    "Transport",
    "UrllibTransport",
    "HttpxTransport",
    "CurlTransport",
    "CallableTransport",
    "transport_disponible",
    "AUTO_ORDER",
    "FakeTransport",
    "build_transport",
]
