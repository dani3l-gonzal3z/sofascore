"""Cliente de la API de Sofascore.

Es la pieza de bajo nivel: sabe hablar HTTP, cachear, reintentar, respetar un
límite de peticiones y traducir códigos de error a excepciones con sentido. Lo
que *agrega* los datos de un partido vive en :mod:`sofascore.match`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .auth import Credentials
from .cache import Cache, build_cache
from .config import Settings
from .endpoints import PLUS, PUBLIC, Section, get_section
from .errors import (
    HTTPError,
    NotFound,
    OfflineError,
    PlusRequired,
    RateLimited,
    TransportError,
)
from .models import Event
from .ratelimit import RateLimiter
from .transport import Transport, build_transport

#: La web pública manda estas cabeceras; sin ellas la API responde peor.
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/",
}


@dataclass
class Stats:
    """Contadores de la sesión: útiles para ``--debug`` y para tests."""

    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    errors: int = 0
    waited: float = 0.0

    def as_dict(self) -> dict:
        return {
            "peticiones": self.requests,
            "aciertos_cache": self.cache_hits,
            "reintentos": self.retries,
            "errores": self.errors,
            "espera_s": round(self.waited, 2),
        }


class SofascoreClient:
    """Cliente HTTP con caché, reintentos y soporte de credenciales propias."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: Transport | None = None,
        cache: Cache | None = None,
        credentials: Credentials | None = None,
        limiter: RateLimiter | None = None,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.transport = transport or build_transport(timeout=self.settings.timeout)
        self.cache = cache if cache is not None else build_cache(
            self.settings.cache_dir, self.settings.cache_ttl
        )
        self.credentials = credentials or Credentials.from_settings(self.settings)
        self.limiter = limiter or RateLimiter(self.settings.rate_limit, sleep=sleep)
        self.stats = Stats()
        self._sleep = sleep

    # --- Contexto ---

    def __enter__(self) -> "SofascoreClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        cerrar = getattr(self.transport, "close", None)
        if callable(cerrar):
            cerrar()

    # --- Propiedades ---

    @property
    def has_plus(self) -> bool:
        """¿Hay credenciales propias cargadas? (no garantiza que sigan válidas)."""
        return self.credentials.present

    # --- Petición ---

    def _url(self, path: str, params: dict | None = None) -> str:
        url = f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            limpios = {k: v for k, v in params.items() if v is not None}
            if limpios:
                url = f"{url}?{urlencode(limpios)}"
        return url

    def _headers(self) -> dict[str, str]:
        cabeceras = {
            "User-Agent": self.settings.user_agent,
            "Accept-Language": f"{self.settings.language},en;q=0.8",
            **BROWSER_HEADERS,
            **self.settings.extra_headers,
        }
        cabeceras.update(self.credentials.headers())
        return cabeceras

    def get(
        self,
        path: str,
        params: dict | None = None,
        ttl: int | None = None,
        scope: str = PUBLIC,
        section_name: str | None = None,
    ) -> Any:
        """Pide ``path`` y devuelve el JSON ya decodificado.

        ``ttl`` sobreescribe el tiempo de caché; ``scope`` decide si un 401/403
        se traduce a :class:`PlusRequired` (sección de pago) o a un HTTPError.
        """
        url = self._url(path, params)
        ttl = self.settings.cache_ttl if ttl is None else ttl
        clave = f"{'auth' if self.has_plus else 'anon'}|{url}"

        en_cache = self.cache.get(clave, ttl)
        if en_cache is not None:
            self.stats.cache_hits += 1
            return en_cache

        if self.settings.offline:
            raise OfflineError(
                f"Modo offline y sin copia en caché de {url}. "
                "Desactiva SOFA_OFFLINE o precalienta la caché."
            )

        datos = self._request_with_retries(url, scope=scope, section_name=section_name)
        self.cache.set(clave, datos)
        return datos

    def _request_with_retries(self, url: str, scope: str, section_name: str | None) -> Any:
        ultimo_error: Exception | None = None
        for intento in range(self.settings.retries + 1):
            if intento:
                self.stats.retries += 1
                espera = self.settings.backoff ** intento
                self.stats.waited += espera
                self._sleep(espera)

            self.stats.waited += self.limiter.wait()
            try:
                self.stats.requests += 1
                respuesta = self.transport.request("GET", url, self._headers())
            except TransportError as exc:
                ultimo_error = exc
                self.stats.errors += 1
                continue

            if respuesta.ok:
                return respuesta.json()

            if respuesta.status == 404:
                self.stats.errors += 1
                raise NotFound(404, url, respuesta.text()[:200])

            if respuesta.status in (401, 403):
                self.stats.errors += 1
                if scope == PLUS:
                    detalle = (
                        "Tus credenciales no han sido aceptadas (¿caducadas?)."
                        if self.has_plus
                        else "Configura SOFA_PLUS_COOKIE con tu propia sesión si tienes Plus."
                    )
                    raise PlusRequired(section_name or url, detalle)
                raise HTTPError(respuesta.status, url, respuesta.text()[:200])

            if respuesta.status == 429:
                self.stats.errors += 1
                cabecera = respuesta.headers.get("retry-after")
                espera = float(cabecera) if cabecera and cabecera.isdigit() else None
                ultimo_error = RateLimited(429, url, respuesta.text()[:200], retry_after=espera)
                if espera:
                    self.stats.waited += espera
                    self._sleep(espera)
                continue

            if 500 <= respuesta.status < 600:
                self.stats.errors += 1
                ultimo_error = HTTPError(respuesta.status, url, respuesta.text()[:200])
                continue

            self.stats.errors += 1
            raise HTTPError(respuesta.status, url, respuesta.text()[:200])

        raise ultimo_error or TransportError(f"No se pudo obtener {url}")

    # --- Atajos de alto nivel ---

    def raw(self, path: str, params: dict | None = None, ttl: int | None = None) -> Any:
        """Escotilla de escape: pide cualquier ruta de la API tal cual."""
        return self.get(path, params=params, ttl=ttl)

    def ttl_for_event(self, evento: Event | None) -> int:
        """Un partido acabado no cambia: se cachea mucho más tiempo."""
        if evento is not None and evento.is_finished:
            return self.settings.cache_ttl_finished
        return self.settings.cache_ttl

    def event(self, event_id: int) -> Event:
        """Devuelve el partido como :class:`~sofascore.models.Event`."""
        datos = self.get(f"/event/{int(event_id)}", section_name="event")
        return Event.from_api(datos)

    def section(
        self,
        section: Section | str,
        event_id: int,
        ttl: int | None = None,
        **extra,
    ) -> Any:
        """Pide una sección del catálogo y devuelve su contenido ya desenvuelto."""
        seccion = get_section(section) if isinstance(section, str) else section
        datos = self.get(
            seccion.url_path(event_id, **extra),
            ttl=ttl,
            scope=seccion.scope,
            section_name=seccion.name,
        )
        if seccion.unwrap and isinstance(datos, dict):
            return datos.get(seccion.unwrap)
        return datos

    def search(self, query: str, page: int = 0) -> list[dict]:
        """Busca en todo Sofascore (equipos, jugadores, partidos, torneos)."""
        datos = self.get("/search/all", params={"q": query, "page": page}, ttl=3600)
        return (datos or {}).get("results", []) if isinstance(datos, dict) else []

    def team_events(self, team_id: int, when: str = "last", page: int = 0) -> list[dict]:
        """Partidos de un equipo: ``when`` es ``last`` (jugados) o ``next``."""
        datos = self.get(f"/team/{int(team_id)}/events/{when}/{int(page)}", ttl=1800)
        return (datos or {}).get("events", []) if isinstance(datos, dict) else []

    def scheduled_events(self, date: str, sport: str | None = None) -> list[dict]:
        """Todos los partidos de un día (``AAAA-MM-DD``) para un deporte."""
        deporte = sport or self.settings.sport
        datos = self.get(f"/sport/{deporte}/scheduled-events/{date}", ttl=1800)
        return (datos or {}).get("events", []) if isinstance(datos, dict) else []

    def player_statistics(self, event_id: int, player_id: int, ttl: int | None = None) -> Any:
        """Estadísticas de un jugador en un partido (suele requerir Plus)."""
        return self.get(
            f"/event/{int(event_id)}/player/{int(player_id)}/statistics",
            ttl=ttl,
            scope=PLUS,
            section_name="player_statistics",
        )

    def player_heatmap(self, event_id: int, player_id: int, ttl: int | None = None) -> Any:
        """Mapa de calor de un jugador en un partido (suele requerir Plus)."""
        datos = self.get(
            f"/event/{int(event_id)}/player/{int(player_id)}/heatmap",
            ttl=ttl,
            scope=PLUS,
            section_name="heatmaps",
        )
        if isinstance(datos, dict):
            return datos.get("heatmap", datos)
        return datos

    def standings(self, unique_tournament_id: int, season_id: int, kind: str = "total") -> Any:
        """Clasificación de una competición/temporada."""
        datos = self.get(
            f"/unique-tournament/{int(unique_tournament_id)}/season/{int(season_id)}/standings/{kind}",
            ttl=3600,
        )
        return (datos or {}).get("standings", datos) if isinstance(datos, dict) else datos
