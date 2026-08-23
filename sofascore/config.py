"""Configuración del framework: variables de entorno y fichero ``.env``.

Sin dependencias externas: se lee el ``.env`` con un parser mínimo y las
variables tienen prefijo ``SOFA_`` (p. ej. ``SOFA_CACHE_TTL=600``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

ENV_PREFIX = "SOFA_"

DEFAULT_BASE_URL = "https://api.sofascore.com/api/v1"
DEFAULT_USER_AGENT = (
    "sofascore-framework/0.1 (+uso personal; https://github.com/dani3l-gonzal3z/b2f-)"
)


def parse_dotenv(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parser mínimo de ``.env``: ``CLAVE=valor``, ``#`` comenta, comillas opcionales."""
    valores: dict[str, str] = {}
    fichero = Path(path)
    if not fichero.is_file():
        return valores
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip()
        if clave.startswith("export "):
            clave = clave[len("export ") :].strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[clave] = valor
    return valores


def _as_bool(valor: str, por_defecto: bool = False) -> bool:
    if valor is None or valor == "":
        return por_defecto
    return valor.strip().lower() in {"1", "true", "yes", "y", "on", "si", "sí"}


@dataclass
class Settings:
    """Ajustes del cliente. Todo tiene un valor por defecto razonable."""

    # --- Red ---
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    retries: int = 3
    backoff: float = 1.5
    #: Peticiones por segundo como máximo (cortesía con la API pública).
    rate_limit: float = 3.0
    user_agent: str = DEFAULT_USER_AGENT
    #: Idioma preferido para textos (comentarios, nombres de rondas...).
    language: str = "es"

    # --- Caché en disco ---
    cache_dir: Path = Path(".sofascore-cache")
    #: Segundos de validez de una respuesta cacheada (0 = sin caché).
    cache_ttl: int = 600
    #: Partidos ya finalizados se cachean mucho más tiempo (segundos).
    cache_ttl_finished: int = 60 * 60 * 24 * 30

    # --- Credenciales propias de Sofascore Plus (opcionales) ---
    #: Cabecera ``Cookie`` copiada de TU navegador con sesión Plus iniciada.
    plus_cookie: str = ""
    #: Token Bearer de TU cuenta, si prefieres ese método.
    plus_token: str = ""
    #: Fichero JSON con cookies exportadas de TU navegador.
    plus_cookie_file: str = ""

    # --- Comportamiento ---
    #: Si está activo, no se hace ninguna petición de red (solo caché/fixtures).
    offline: bool = False
    #: Deporte por defecto al buscar partidos.
    sport: str = "football"
    #: Cabeceras extra que quieras añadir a cada petición.
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        dotenv: str | os.PathLike[str] | None = ".env",
        **overrides,
    ) -> "Settings":
        """Construye los ajustes desde el entorno, el ``.env`` y overrides explícitos.

        Precedencia (de menor a mayor): valores por defecto < ``.env`` <
        variables de entorno < ``overrides``.
        """
        fuente: dict[str, str] = {}
        if dotenv:
            fuente.update(parse_dotenv(dotenv))
        fuente.update(env if env is not None else os.environ)

        ajustes = cls()
        for campo in ("base_url", "user_agent", "language", "plus_cookie", "plus_token",
                      "plus_cookie_file", "sport"):
            valor = fuente.get(ENV_PREFIX + campo.upper())
            if valor:
                setattr(ajustes, campo, valor)
        for campo in ("timeout", "backoff", "rate_limit"):
            valor = fuente.get(ENV_PREFIX + campo.upper())
            if valor:
                setattr(ajustes, campo, float(valor))
        for campo in ("retries", "cache_ttl", "cache_ttl_finished"):
            valor = fuente.get(ENV_PREFIX + campo.upper())
            if valor:
                setattr(ajustes, campo, int(valor))
        if ENV_PREFIX + "OFFLINE" in fuente:
            ajustes.offline = _as_bool(fuente[ENV_PREFIX + "OFFLINE"])
        if fuente.get(ENV_PREFIX + "CACHE_DIR"):
            ajustes.cache_dir = Path(fuente[ENV_PREFIX + "CACHE_DIR"])

        if overrides:
            ajustes = replace(ajustes, **{k: v for k, v in overrides.items() if v is not None})
        return ajustes

    # --- Utilidades ---

    def has_plus_credentials(self) -> bool:
        """¿Hay credenciales propias configuradas para las secciones Plus?"""
        return bool(self.plus_cookie or self.plus_token or self.plus_cookie_file)

    def redacted(self) -> dict:
        """Copia serializable con los secretos ocultos (para logs y ``--debug``)."""
        datos = {
            "base_url": self.base_url,
            "timeout": self.timeout,
            "retries": self.retries,
            "rate_limit": self.rate_limit,
            "language": self.language,
            "cache_dir": str(self.cache_dir),
            "cache_ttl": self.cache_ttl,
            "offline": self.offline,
            "sport": self.sport,
            "plus_credentials": "configuradas" if self.has_plus_credentials() else "no",
        }
        return datos
