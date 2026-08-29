"""Errores del framework.

Todos heredan de :class:`SofascoreError`, así que un ``except SofascoreError``
captura cualquier fallo previsible de la librería.
"""

from __future__ import annotations


class SofascoreError(Exception):
    """Error base de la librería."""


class TransportError(SofascoreError):
    """Fallo de red: DNS, timeout, conexión cortada..."""


class HTTPError(SofascoreError):
    """La API respondió con un código de error."""

    def __init__(self, status: int, url: str, body: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} en {url}")


class NotFound(HTTPError):
    """404: el recurso no existe (o el partido no tiene esa sección)."""


class RateLimited(HTTPError):
    """429: demasiadas peticiones. Baja ``SOFA_RATE_LIMIT`` y reintenta."""

    def __init__(self, status: int, url: str, body: str = "",
                 retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(status, url, body)


class Blocked(HTTPError):
    """403 desde todos los hosts: no es el dato, es el anti-bot.

    Sofascore está detrás de Cloudflare, que mira la huella del handshake TLS y
    no solo las cabeceras. Una petición de ``urllib`` con cabeceras de Chrome no
    cuela. La salida es hablar TLS como Chrome, que es lo que hace
    ``curl_cffi``.
    """

    def __init__(self, status: int, url: str, body: str = "", transporte: str = "") -> None:
        self.transporte = transporte
        consejo = (
            "Sofascore te está bloqueando (Cloudflare mira la huella TLS, no solo "
            "las cabeceras). La solución es una línea:\n"
            "    pip install curl_cffi\n"
            "El framework lo detecta solo y empieza a usarlo. Si aun así te "
            "bloquea, prueba desde otra red o con SOFA_RATE_LIMIT más bajo."
        )
        if transporte == "CurlTransport":
            consejo = (
                "Sofascore te está bloqueando incluso imitando a Chrome. Prueba "
                "desde otra red, baja SOFA_RATE_LIMIT, o usa un navegador real "
                "como transporte (mira CallableTransport en el README)."
            )
        super().__init__(status, url, body)
        self.args = (f"HTTP {status} en {url}\n\n{consejo}",)


class PlusRequired(SofascoreError):
    """La sección pedida requiere una suscripción Sofascore Plus activa.

    Se lanza cuando la API responde 401/403 a una sección marcada como ``plus``
    y no hay credenciales propias configuradas (o han caducado).
    """

    def __init__(self, section: str, detail: str = "") -> None:
        self.section = section
        self.detail = detail
        msg = f"La sección '{section}' requiere Sofascore Plus (usa tus propias credenciales)."
        if detail:
            msg = f"{msg} {detail}"
        super().__init__(msg)


class MatchNotFound(SofascoreError):
    """No se ha encontrado ningún partido para la consulta dada."""


class AmbiguousMatch(SofascoreError):
    """La consulta encaja con varios partidos y no hay forma de desempatar."""

    def __init__(self, query: str, candidates: list) -> None:
        self.query = query
        self.candidates = candidates
        listado = "\n".join(f"  - {c}" for c in candidates[:10])
        super().__init__(
            f"'{query}' encaja con {len(candidates)} partidos. Afina con --date "
            f"o pasa el id/URL directamente:\n{listado}"
        )


class OfflineError(SofascoreError):
    """Modo offline activo: no se permiten peticiones de red."""
