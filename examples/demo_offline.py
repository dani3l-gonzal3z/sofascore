"""Demostración sin red: usa las respuestas de ejemplo de `tests/fixtures`.

    python examples/demo_offline.py

Sirve para ver la forma del informe (y para desarrollar) sin tocar la API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sofascore import MemoryCache, Settings, SofascoreClient  # noqa: E402
from sofascore.export import to_markdown  # noqa: E402
from sofascore.match import build_report  # noqa: E402
from sofascore.transport import FakeTransport  # noqa: E402

FIXTURES = RAIZ / "tests" / "fixtures"
EVENT_ID = 11352550


def cargar(nombre: str) -> dict:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def main() -> int:
    rutas = {
        f"/event/{EVENT_ID}/statistics": cargar("statistics"),
        f"/event/{EVENT_ID}/lineups": cargar("lineups"),
        f"/event/{EVENT_ID}/incidents": cargar("incidents"),
        f"/event/{EVENT_ID}/graph": cargar("graph"),
        f"/event/{EVENT_ID}/shotmap": 403,  # sin Plus: queda bloqueada
        f"/event/{EVENT_ID}": cargar("event"),
    }
    cliente = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=0),
        transport=FakeTransport(rutas),
        cache=MemoryCache(),
    )
    informe = build_report(
        cliente,
        EVENT_ID,
        sections=["statistics", "lineups", "incidents", "momentum", "shotmap"],
    )

    print(informe.summary())
    print("\n" + "=" * 70 + "\n")
    print(to_markdown(informe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
