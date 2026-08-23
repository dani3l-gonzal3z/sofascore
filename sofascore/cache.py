"""Caché de respuestas en disco.

La API pública de Sofascore agradece que no le pidas veinte veces lo mismo:
un partido terminado no cambia nunca, así que se guarda mucho tiempo, y uno en
juego se refresca cada pocos minutos.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol


class Cache(Protocol):
    """Contrato de una caché."""

    def get(self, clave: str, ttl: int) -> Any | None: ...

    def set(self, clave: str, valor: Any) -> None: ...


class NullCache:
    """Caché que no guarda nada (``--no-cache``)."""

    def get(self, clave: str, ttl: int) -> Any | None:
        return None

    def set(self, clave: str, valor: Any) -> None:
        return None


class MemoryCache:
    """Caché en memoria: vive lo que viva el proceso. Ideal para tests."""

    def __init__(self) -> None:
        self._datos: dict[str, tuple[float, Any]] = {}

    def get(self, clave: str, ttl: int) -> Any | None:
        if ttl <= 0 or clave not in self._datos:
            return None
        guardado_en, valor = self._datos[clave]
        if time.time() - guardado_en > ttl:
            return None
        return valor

    def set(self, clave: str, valor: Any) -> None:
        self._datos[clave] = (time.time(), valor)


class DiskCache:
    """Caché en disco: un fichero JSON por petición, dentro de ``directorio``."""

    def __init__(self, directorio: str | Path) -> None:
        self.directorio = Path(directorio)

    def _ruta(self, clave: str) -> Path:
        digest = hashlib.sha256(clave.encode("utf-8")).hexdigest()[:32]
        return self.directorio / digest[:2] / f"{digest}.json"

    def get(self, clave: str, ttl: int) -> Any | None:
        if ttl <= 0:
            return None
        ruta = self._ruta(clave)
        if not ruta.is_file():
            return None
        try:
            entrada = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - float(entrada.get("guardado_en", 0)) > ttl:
            return None
        return entrada.get("valor")

    def set(self, clave: str, valor: Any) -> None:
        ruta = self._ruta(clave)
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal = ruta.with_suffix(".tmp")
            temporal.write_text(
                json.dumps({"clave": clave, "guardado_en": time.time(), "valor": valor}),
                encoding="utf-8",
            )
            temporal.replace(ruta)
        except OSError:
            # Una caché que falla nunca debe tumbar la petición.
            return None

    def clear(self) -> int:
        """Borra la caché entera. Devuelve cuántos ficheros ha eliminado."""
        borrados = 0
        if not self.directorio.is_dir():
            return 0
        for fichero in self.directorio.rglob("*.json"):
            try:
                fichero.unlink()
                borrados += 1
            except OSError:
                pass
        return borrados


def build_cache(directorio: str | Path | None, ttl: int) -> Cache:
    """Elige la caché adecuada según la configuración."""
    if ttl <= 0 or directorio is None:
        return NullCache()
    return DiskCache(directorio)
