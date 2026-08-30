"""Nombre antiguo del paquete. Ahora se llama ``cancha``.

El framework nació hablando solo con Sofascore y por eso se llamaba así. Ya
habla con tres fuentes, así que el nombre se quedó corto y se cambió. Pero
romperle los comandos y los imports a quien ya lo usaba sería una grosería, así
que este puente sigue aquí y funciona exactamente igual::

    import sofascore              # da el paquete cancha
    from sofascore import get_match
    from sofascore.tools import TOOLS
    python -m sofascore match ...

No hay planes de quitarlo. Si escribes código nuevo, usa ``cancha``.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import suppress

_paquete = importlib.import_module("cancha")

#: Los submódulos, para que ``import sofascore.tools`` siga resolviendo.
_SUBMODULOS = (
    "analisis", "auth", "cache", "catalog", "cli", "client", "config",
    "endpoints", "entities", "errors", "export", "frames", "match", "mcp",
    "models", "ratelimit", "report", "resolve", "tools", "transport",
    "sources", "sources.base", "sources.clubelo", "sources.understat",
    "sources.cruce",
)

for _nombre in _SUBMODULOS:
    # Un submódulo que ya no exista no puede impedir que el puente funcione.
    with suppress(ImportError):
        sys.modules[f"{__name__}.{_nombre}"] = importlib.import_module(f"cancha.{_nombre}")

# A partir de aquí, `sofascore` *es* `cancha`: mismo objeto, mismos atributos.
sys.modules[__name__] = _paquete
