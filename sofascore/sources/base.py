"""La maquinaria común a todas las fuentes de datos.

El framework nació hablando solo con Sofascore. Esto es lo que hace falta para
que hable con varias sin repetir el trabajo, y es justo donde se le puede ganar
a ``soccerdata`` y ``ScraperFC``: ellos tienen un lector por fuente, cada uno
con su sesión, su caché y sus errores. Aquí **todas las fuentes comparten**:

* el transporte (incluido el que imita el TLS de Chrome, que ya nos hizo falta);
* la caché en disco, con su TTL por fuente;
* el limitador de peticiones, **con un ritmo propio para cada una** — FBref
  banea por encima de una cada tres segundos y ClubElo no se inmuta;
* los errores tipados y el modo offline.

Añadir una fuente nueva es heredar de :class:`Fuente` y escribir los métodos
que traen datos. El resto ya está.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from ..cache import Cache, build_cache
from ..config import Settings
from ..errors import HTTPError, NotFound, OfflineError, SofascoreError, TransportError
from ..ratelimit import RateLimiter
from ..transport import Transport, build_transport


class FuenteError(SofascoreError):
    """Algo ha fallado al hablar con una fuente externa."""


@dataclass
class Fuente:
    """Una fuente de datos con su propia URL base, ritmo y caché.

    Es deliberadamente pequeña: sabe pedir, cachear y esperar. Lo que cada
    fuente devuelve y cómo se interpreta vive en su módulo.
    """

    #: Nombre corto con el que se la conoce (``clubelo``, ``understat``).
    nombre: str = ""
    #: Raíz de sus URLs.
    base_url: str = ""
    #: Peticiones por segundo. Cada sitio aguanta lo que aguanta.
    rate_limit: float = 1.0
    #: Segundos que se guarda una respuesta. Los datos históricos no cambian.
    ttl: int = 24 * 3600
    #: Cabeceras propias de la fuente.
    headers: dict[str, str] = field(default_factory=dict)
    #: Qué trae, en una línea, para que se pueda listar (y para la IA).
    descripcion: str = ""

    settings: Settings | None = None
    transport: Transport | None = None
    cache: Cache | None = None
    _limiter: RateLimiter | None = field(default=None, repr=False)
    #: Se pide una vez antes que nada (algunas fuentes exigen cookie de sesión).
    _arrancada: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.settings = self.settings or Settings.from_env()
        self.transport = self.transport or build_transport(
            self.settings.transport, timeout=self.settings.timeout
        )
        if self.cache is None:
            self.cache = build_cache(
                self.settings.cache_dir / "fuentes" if self.settings.cache_dir else None,
                self.ttl,
            )
        self._limiter = self._limiter or RateLimiter(self.rate_limit)

    # --- lo que puede redefinir cada fuente ---

    def arrancar(self) -> None:
        """Lo que haya que hacer antes de la primera petición (cookies, etc.)."""
        return

    def cabeceras(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept-Language": f"{self.settings.language},en;q=0.8",
            "Accept": "*/*",
            **self.headers,
        }

    # --- pedir ---

    def url(self, ruta: str) -> str:
        if ruta.startswith("http"):
            return ruta
        return f"{self.base_url.rstrip('/')}/{ruta.lstrip('/')}"

    def texto(self, ruta: str, ttl: int | None = None) -> str:
        """Pide una ruta y devuelve el cuerpo como texto, con caché."""
        url = self.url(ruta)
        ttl = self.ttl if ttl is None else ttl
        clave = f"{self.nombre}|{url}"

        guardado = self.cache.get(clave, ttl)
        if guardado is not None:
            return guardado

        if self.settings.offline:
            raise OfflineError(f"Modo offline y sin copia en caché de {url}.")

        if not self._arrancada:
            self._arrancada = True
            # Si el arranque falla, se intenta igual: puede que no hiciera falta.
            with suppress(SofascoreError):
                self.arrancar()

        self._limiter.wait()
        try:
            respuesta = self.transport.request("GET", url, self.cabeceras())
        except TransportError as exc:
            raise FuenteError(f"[{self.nombre}] no responde: {exc}") from exc

        if respuesta.status == 404:
            raise NotFound(404, url, respuesta.text()[:200])
        if not respuesta.ok:
            raise HTTPError(respuesta.status, url, respuesta.text()[:200])

        cuerpo = respuesta.text()
        self.cache.set(clave, cuerpo)
        return cuerpo

    def json(self, ruta: str, ttl: int | None = None) -> Any:
        """Lo mismo, ya decodificado."""
        crudo = self.texto(ruta, ttl)
        try:
            return json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise FuenteError(
                f"[{self.nombre}] esperaba JSON en {self.url(ruta)} y no lo era: {exc}"
            ) from exc

    def csv(self, ruta: str, ttl: int | None = None) -> list[dict]:
        """Lo mismo, para las fuentes que sirven CSV (ClubElo, por ejemplo)."""
        crudo = self.texto(ruta, ttl)
        filas = list(csv.DictReader(io.StringIO(crudo)))
        if not filas:
            raise FuenteError(f"[{self.nombre}] devolvió un CSV vacío en {self.url(ruta)}.")
        return filas

    def close(self) -> None:
        cerrar = getattr(self.transport, "close", None)
        if callable(cerrar):
            cerrar()


#: Todas las fuentes registradas, por nombre.
FUENTES: dict[str, type] = {}


def registrar(cls):
    """Apunta una fuente en el registro para que se pueda listar y construir."""
    FUENTES[cls.NOMBRE] = cls
    return cls


def construir(nombre: str, **kwargs) -> Fuente:
    """Crea una fuente por su nombre."""
    if nombre not in FUENTES:
        raise ValueError(
            f"Fuente desconocida: '{nombre}'. Disponibles: {', '.join(sorted(FUENTES))}"
        )
    return FUENTES[nombre](**kwargs)


def _numero(valor: Any) -> Any:
    """Convierte a número lo que lo parezca; deja el resto como está."""
    if valor in (None, "", "None", "NA", "-"):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        pass
    try:
        return float(valor)
    except (TypeError, ValueError):
        return valor


__all__ = ["Fuente", "FuenteError", "FUENTES", "registrar", "construir"]
