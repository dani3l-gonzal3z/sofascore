"""Cliente de la API de Sofascore.

Es la pieza de bajo nivel: sabe hablar HTTP, cachear, reintentar, respetar un
límite de peticiones y traducir códigos de error a excepciones con sentido. Lo
que *agrega* los datos de un partido vive en :mod:`sofascore.match`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from .auth import Credentials
from .cache import Cache, build_cache
from .config import Settings
from .endpoints import PLUS, PUBLIC, Section, get_section
from .errors import (
    Blocked,
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
    """Contadores de la sesión: útiles para ``--debug`` y para tests.

    Se tocan desde varios hilos cuando el informe se pide en paralelo, así que
    los incrementos van bajo un cerrojo.
    """

    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    errors: int = 0
    waited: float = 0.0
    host_switches: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, **cuantos: float) -> None:
        """Suma a varios contadores de una vez, de forma atómica."""
        with self._lock:
            for nombre, cuanto in cuantos.items():
                setattr(self, nombre, getattr(self, nombre) + cuanto)

    def as_dict(self) -> dict:
        return {
            "peticiones": self.requests,
            "aciertos_cache": self.cache_hits,
            "reintentos": self.retries,
            "errores": self.errors,
            "espera_s": round(self.waited, 2),
            "cambios_de_host": self.host_switches,
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
        self.transport = transport or build_transport(
            self.settings.transport, timeout=self.settings.timeout
        )
        self.cache = cache if cache is not None else build_cache(
            self.settings.cache_dir, self.settings.cache_ttl
        )
        self.credentials = credentials or Credentials.from_settings(self.settings)
        self.limiter = limiter or RateLimiter(self.settings.rate_limit, sleep=sleep)
        self.stats = Stats()
        self._sleep = sleep

    # --- Contexto ---

    def __enter__(self) -> SofascoreClient:
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

    def _url(self, base: str, path: str, params: dict | None = None) -> str:
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
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

        La caché se indexa por *ruta*, no por host: si una respuesta llegó por
        el host alternativo, el siguiente arranque la reutiliza igual.
        """
        ttl = self.settings.cache_ttl if ttl is None else ttl
        ruta = self._url("", path, params)
        clave = f"{'auth' if self.has_plus else 'anon'}|{ruta}"

        en_cache = self.cache.get(clave, ttl)
        if en_cache is not None:
            self.stats.bump(cache_hits=1)
            return en_cache

        if self.settings.offline:
            raise OfflineError(
                f"Modo offline y sin copia en caché de {ruta}. "
                "Desactiva SOFA_OFFLINE o precalienta la caché."
            )

        datos = self._request_all_hosts(path, params, scope=scope, section_name=section_name)
        self.cache.set(clave, datos)
        return datos

    def _request_all_hosts(
        self,
        path: str,
        params: dict | None,
        scope: str,
        section_name: str | None,
    ) -> Any:
        """Intenta la petición en cada host conocido hasta que uno responda.

        La misma API vive en ``api.sofascore.com`` y en ``www.sofascore.com``.
        Cuando el primero contesta con un bloqueo (401/403) o no hay forma de
        conectarse, se prueba el siguiente antes de darse por vencido: es un
        bloqueo del borde, no una respuesta sobre el dato pedido.
        """
        hosts = self.settings.base_urls()
        bloqueo: Exception | None = None
        for indice, base in enumerate(hosts):
            if indice:
                self.stats.bump(host_switches=1)
            url = self._url(base, path, params)
            try:
                return self._request_with_retries(url, scope=scope, section_name=section_name)
            except (PlusRequired, HTTPError, TransportError) as exc:
                es_bloqueo = isinstance(exc, (PlusRequired, TransportError)) or getattr(
                    exc, "status", 0
                ) in (401, 403)
                if indice < len(hosts) - 1 and es_bloqueo:
                    bloqueo = exc
                    continue
                # Último host: si lo que hay es un 403 en datos públicos, no es
                # el dato lo que falla, es el anti-bot. Merece decirlo.
                if getattr(exc, "status", 0) in (401, 403) and scope != PLUS:
                    raise Blocked(
                        exc.status, exc.url, getattr(exc, "body", ""),
                        transporte=type(self.transport).__name__,
                    ) from exc
                raise
        raise bloqueo or TransportError(f"No se pudo obtener {path}")

    def _request_with_retries(self, url: str, scope: str, section_name: str | None) -> Any:
        ultimo_error: Exception | None = None
        for intento in range(self.settings.retries + 1):
            if intento:
                espera = self.settings.backoff ** intento
                self.stats.bump(retries=1, waited=espera)
                self._sleep(espera)

            self.stats.bump(waited=self.limiter.wait(), requests=1)
            try:
                respuesta = self.transport.request("GET", url, self._headers())
            except TransportError as exc:
                ultimo_error = exc
                self.stats.bump(errors=1)
                continue

            if respuesta.ok:
                return respuesta.json()

            self.stats.bump(errors=1)

            if respuesta.status == 404:
                raise NotFound(404, url, respuesta.text()[:200])

            if respuesta.status in (401, 403):
                if scope == PLUS:
                    detalle = (
                        "Tus credenciales no han sido aceptadas (¿caducadas?)."
                        if self.has_plus
                        else "Configura SOFA_PLUS_COOKIE con tu propia sesión si tienes Plus."
                    )
                    raise PlusRequired(section_name or url, detalle)
                raise HTTPError(respuesta.status, url, respuesta.text()[:200])

            if respuesta.status == 429:
                cabecera = respuesta.headers.get("retry-after")
                espera = float(cabecera) if cabecera and cabecera.isdigit() else None
                ultimo_error = RateLimited(429, url, respuesta.text()[:200], retry_after=espera)
                if espera:
                    self.stats.bump(waited=espera)
                    self._sleep(espera)
                continue

            if 500 <= respuesta.status < 600:
                ultimo_error = HTTPError(respuesta.status, url, respuesta.text()[:200])
                continue

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

    def h2h_events(self, event: Event | str) -> list[dict]:
        """Todos los enfrentamientos históricos entre los dos equipos del partido.

        Es la vía más corta para encontrar un cruce antiguo: el calendario de un
        equipo solo llega a sus últimos partidos, pero esto devuelve la serie
        entera, por vieja que sea.

        **Ojo con el argumento**: esta ruta no acepta el id numérico, sino el
        ``customId`` del partido (``xNbsDNb``). Con el id devuelve 404. Por eso
        se pide aquí el :class:`~sofascore.models.Event` entero, o el código
        directamente si ya lo tienes.
        """
        codigo = event.custom_id if isinstance(event, Event) else str(event)
        if not codigo:
            raise NotFound(404, "h2h/events", "El partido no trae customId.")
        datos = self.get(f"/event/{codigo}/h2h/events", ttl=86400)
        return (datos or {}).get("events", []) if isinstance(datos, dict) else []

    def live_events(self, sport: str | None = None) -> list[dict]:
        """Todo lo que se está jugando ahora mismo en un deporte."""
        deporte = sport or self.settings.sport
        datos = self.get(f"/sport/{deporte}/events/live", ttl=30)
        return (datos or {}).get("events", []) if isinstance(datos, dict) else []

    def entity_section(
        self,
        section: Section,
        ttl: int | None = None,
        **ids,
    ) -> Any:
        """Pide una sección de un equipo, jugador o competición.

        ``ids`` rellena los huecos de la ruta (``team_id``, ``player_id``,
        ``tournament_id``, ``season_id``...).
        """
        datos = self.get(
            section.path.format(**ids),
            ttl=ttl,
            scope=section.scope,
            section_name=section.name,
        )
        if section.unwrap and isinstance(datos, dict):
            return datos.get(section.unwrap)
        return datos

    def team(self, team_id: int) -> dict:
        """Ficha de un equipo."""
        datos = self.get(f"/team/{int(team_id)}", ttl=3600)
        return (datos or {}).get("team", datos or {}) if isinstance(datos, dict) else {}

    def player(self, player_id: int) -> dict:
        """Ficha de un jugador."""
        datos = self.get(f"/player/{int(player_id)}", ttl=3600)
        return (datos or {}).get("player", datos or {}) if isinstance(datos, dict) else {}

    def tournament(self, tournament_id: int) -> dict:
        """Ficha de una competición."""
        datos = self.get(f"/unique-tournament/{int(tournament_id)}", ttl=86400)
        if isinstance(datos, dict):
            return datos.get("uniqueTournament", datos)
        return {}

    def seasons(self, tournament_id: int) -> list[dict]:
        """Temporadas de una competición, de la más reciente a la más antigua."""
        datos = self.get(f"/unique-tournament/{int(tournament_id)}/seasons", ttl=86400)
        return (datos or {}).get("seasons", []) if isinstance(datos, dict) else []

    def latest_season_id(self, tournament_id: int) -> int | None:
        """Id de la temporada en curso (la primera que devuelve la API)."""
        temporadas = self.seasons(tournament_id)
        return temporadas[0].get("id") if temporadas else None

    def player_season_statistics(
        self, player_id: int, tournament_id: int, season_id: int
    ) -> Any:
        """Estadísticas completas de un jugador en una liga y temporada."""
        return self.get(
            f"/player/{int(player_id)}/unique-tournament/{int(tournament_id)}"
            f"/season/{int(season_id)}/statistics/overall",
            ttl=3600,
        )

    def team_season_statistics(self, team_id: int, tournament_id: int, season_id: int) -> Any:
        """Estadísticas completas de un equipo en una liga y temporada."""
        return self.get(
            f"/team/{int(team_id)}/unique-tournament/{int(tournament_id)}"
            f"/season/{int(season_id)}/statistics/overall",
            ttl=3600,
        )

    def image_url(self, kind: str, entity_id: int) -> str:
        """URL del escudo/foto: ``kind`` es ``team``, ``player`` o ``tournament``."""
        base = self.settings.base_url.rstrip("/")
        rutas = {
            "team": f"{base}/team/{int(entity_id)}/image",
            "player": f"{base}/player/{int(entity_id)}/image",
            "tournament": f"{base}/unique-tournament/{int(entity_id)}/image",
        }
        if kind not in rutas:
            raise ValueError(f"Tipo de imagen desconocido: '{kind}'. Usa: {', '.join(rutas)}")
        return rutas[kind]
