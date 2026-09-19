"""Los comandos, por familias.

``cli.py` eran novecientas líneas con veintiún comandos y su parser entrelazado.
Ahora cada familia vive en su módulo y aporta lo suyo con ``registrar``:

* :mod:`.partido` — el informe, la búsqueda, el análisis y el cruce de fuentes;
* :mod:`.memoria` — el barrido, los perfiles y la previa;
* :mod:`.entidades` — equipos, jugadores, competiciones y listados;
* :mod:`.credenciales` — sacar tu cookie y comprobarla;
* :mod:`.datos` — grabar respuestas, la caché, el diagnóstico;
* :mod:`.ia` — el servidor MCP y las herramientas.
"""

from . import credenciales, datos, entidades, ia, memoria, partido
from .comun import construir_cliente, depuracion, envolver, imprimir, parsers_padre

#: En el orden en que se quieren ver en la ayuda.
FAMILIAS = (partido, memoria, entidades, ia, credenciales, datos)

__all__ = [
    "FAMILIAS", "parsers_padre", "construir_cliente", "imprimir", "envolver", "depuracion",
    "partido", "memoria", "entidades", "credenciales", "datos", "ia",
]
