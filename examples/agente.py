"""Enganchar las herramientas a una IA, sin depender de ninguna en concreto.

    python examples/agente.py

El framework no trae ningún modelo dentro: te da las herramientas y tú decides
quién las llama. Este ejemplo enseña las dos piezas que hacen falta —los
esquemas y el ejecutor— y simula un par de vueltas del bucle para que se vea la
forma que tienen los datos.

Para usarlo de verdad tienes dos caminos:

* **MCP** (lo más cómodo): ``sofascore mcp`` y configuras tu cliente local.
  No hay que escribir nada de código.
* **A mano**: le pasas ``esquemas_herramientas()`` a tu modelo como definición
  de funciones y, cuando pida una, se la ejecutas con
  ``ejecutar_herramienta(nombre, argumentos)``. Vale igual con Ollama,
  llama.cpp, LM Studio o la API que uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sofascore import ejecutar_herramienta, esquemas_herramientas  # noqa: E402


def main() -> int:
    esquemas = esquemas_herramientas()
    print(f"El modelo ve {len(esquemas)} herramientas:\n")
    for esquema in esquemas:
        print(f"  · {esquema['name']}")

    print("\nAsí se le pasan a un modelo con function calling:\n")
    print(json.dumps(esquemas[1], ensure_ascii=False, indent=2)[:600] + " …")

    print("\n" + "=" * 70)
    print("Una sesión de análisis, tal como la haría el modelo:\n")

    # 1) Empieza por el resumen, que le dice qué datos hay.
    plan = [
        ("resumen_partido", {"partido": "Real Madrid vs Barcelona", "fecha": "2024-10-26"}),
        ("estadisticas_partido", {"partido": "12437616", "grupo": "Shots"}),
        ("tiros_partido", {"partido": "12437616", "solo_goles": True}),
        ("jugadores_partido", {"partido": "12437616", "equipo": "Barcelona"}),
        ("momento_partido", {"partido": "12437616", "cada": 15}),
    ]
    for nombre, argumentos in plan:
        print(f"\n>>> {nombre}({json.dumps(argumentos, ensure_ascii=False)})")
        resultado = ejecutar_herramienta(nombre, argumentos)
        texto = json.dumps(resultado, ensure_ascii=False, default=str)
        print(f"    {len(texto)} caracteres")
        print("    " + texto[:400] + (" …" if len(texto) > 400 else ""))
        if isinstance(resultado, dict) and "error" in resultado:
            print("    (necesita conexión a internet; sin ella el error es este)")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
