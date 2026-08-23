"""Credenciales propias para las secciones de Sofascore Plus.

Cómo funciona, sin rodeos: el framework **no rompe ni esquiva ningún muro de
pago**. Si tienes Sofascore Plus, tu navegador ya recibe esos datos porque tu
sesión está autenticada; aquí simplemente reutilizas *tu* sesión para que el
cliente pida los mismos datos en tu nombre. Sin credenciales, esas secciones se
marcan como ``plus_required`` y el informe sigue adelante con lo público.

Tres formas de dárselas, todas equivalentes:

1. ``SOFA_PLUS_COOKIE`` — la cabecera ``Cookie`` copiada de tu navegador.
2. ``SOFA_PLUS_TOKEN``  — un token Bearer de tu cuenta.
3. ``SOFA_PLUS_COOKIE_FILE`` — un JSON de cookies exportado por tu navegador.

Reglas de la casa: son credenciales personales, no se comparten, no se suben al
repositorio (``.env`` está en ``.gitignore``) y solo valen para tu propio uso.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


def _cookies_desde_fichero(ruta: str | Path) -> str:
    """Convierte un JSON de cookies exportado del navegador en cabecera ``Cookie``.

    Acepta los dos formatos habituales: lista de ``{"name": ..., "value": ...}``
    (extensiones tipo *Cookie Editor*) o un diccionario plano ``{nombre: valor}``.
    """
    fichero = Path(ruta)
    if not fichero.is_file():
        raise FileNotFoundError(f"No existe el fichero de cookies: {fichero}")
    datos = json.loads(fichero.read_text(encoding="utf-8"))
    if isinstance(datos, dict):
        pares = [(str(k), str(v)) for k, v in datos.items()]
    elif isinstance(datos, list):
        pares = [
            (str(c["name"]), str(c.get("value", "")))
            for c in datos
            if isinstance(c, dict) and c.get("name")
        ]
    else:
        raise ValueError("Formato de cookies no reconocido (esperaba lista o diccionario).")
    return "; ".join(f"{nombre}={valor}" for nombre, valor in pares if valor)


@dataclass
class Credentials:
    """Credenciales de tu cuenta. Vacías = solo datos públicos."""

    cookie: str = ""
    token: str = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> "Credentials":
        cookie = settings.plus_cookie
        if not cookie and settings.plus_cookie_file:
            cookie = _cookies_desde_fichero(settings.plus_cookie_file)
        return cls(cookie=cookie.strip(), token=settings.plus_token.strip())

    @property
    def present(self) -> bool:
        return bool(self.cookie or self.token)

    def headers(self) -> dict[str, str]:
        """Cabeceras de autenticación a añadir a la petición."""
        cabeceras: dict[str, str] = {}
        if self.cookie:
            cabeceras["Cookie"] = self.cookie
        if self.token:
            cabeceras["Authorization"] = (
                self.token if self.token.lower().startswith("bearer ") else f"Bearer {self.token}"
            )
        return cabeceras

    def describe(self) -> str:
        """Resumen legible y sin secretos, para ``sofascore login``."""
        if not self.present:
            return "sin credenciales (solo datos públicos)"
        partes = []
        if self.cookie:
            partes.append(f"cookie de {len(self.cookie)} caracteres")
        if self.token:
            partes.append("token Bearer")
        return " + ".join(partes)
