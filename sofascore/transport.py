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


def build_transport(kind: str = "auto", timeout: float = 15.0) -> Transport:
    """Devuelve el transporte pedido: ``urllib``, ``httpx`` o ``auto``."""
    if kind == "httpx":
        return HttpxTransport(timeout=timeout)
    if kind == "urllib":
        return UrllibTransport(timeout=timeout)
    try:  # "auto": httpx si está instalado, urllib si no
        import httpx  # noqa: F401
    except ImportError:
        return UrllibTransport(timeout=timeout)
    return HttpxTransport(timeout=timeout)


__all__ = [
    "Response",
    "Transport",
    "UrllibTransport",
    "HttpxTransport",
    "FakeTransport",
    "build_transport",
]
