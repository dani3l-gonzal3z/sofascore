# Usarlo como librería

```python
from cancha import SofascoreClient, Settings, build_report, resolve_event

# Un cliente reutilizable (comparte caché y límite de peticiones).
cliente = SofascoreClient(Settings.from_env(rate_limit=2))

partido = resolve_event(cliente, "Girona vs Osasuna").event
informe = build_report(cliente, partido, sections=["statistics", "lineups"])

for jugador in informe.players():
    valoracion = jugador.raw.get("statistics", {}).get("rating")
    print(f"{jugador.shirt_number:>2} {jugador.name:<25} {valoracion}")
```

Piezas sueltas, todas intercambiables:

| Módulo | Qué hace |
| --- | --- |
| `config.py` | Ajustes desde entorno y `.env` (prefijo `CANCHA_`, y `SOFA_` sigue valiendo) |
| `transport.py` | HTTP con `curl_cffi`, `urllib`, `httpx`, a medida o falso |
| `cache.py` | Caché en disco, en memoria o ninguna |
| `ratelimit.py` | Espaciado de peticiones |
| `auth.py` | Tus credenciales de Plus y la cookie del navegador |
| `endpoints.py` | Catálogo declarativo de secciones (partido, equipo, jugador, liga) |
| `catalog.py` | Ligas conocidas, códigos de estado y claves de estadística |
| `client.py` | Peticiones, reintentos, cambio de host, errores tipados |
| `resolve.py` | De «un partido» a un id de evento |
| `report.py` | La mecánica común: secciones, estados, paralelismo |
| `match.py` | El informe de un partido |
| `entities.py` | Los informes de equipo, jugador y competición |
| `sesion.py` | Sostiene lo ya resuelto y traído, para no repetirlo |
| `analisis.py` | Métricas calculadas: puntos esperados, calidad de tiro, xG acumulado |
| `frames.py` | Tablas y `DataFrame` |
| `export.py` | JSON, Markdown y CSV |
| `grabacion.py` | Grabar respuestas reales y reproducirlas sin red |
| `herramientas/` | Las 23 herramientas para una IA, por familias |
| `mcp.py` | Servidor MCP (JSON-RPC por stdin/stdout) |
| `sources/` | Otras fuentes: Understat, ClubElo, y el cruce entre ellas |
| `comandos/` | Los comandos del CLI, por familias |
| `cli.py` | El armazón de la línea de comandos |

### Añadir una sección nueva

Es una línea en `endpoints.py`; no hay que tocar el cliente:

```python
Section("mi_seccion", "/event/{event_id}/lo-que-sea",
        "Qué trae esta sección.", unwrap="clave", default=False)
```

### Otro deporte

El catálogo está pensado para fútbol, pero la API comparte estructura. Cambia el
deporte de las búsquedas con `--sport basketball` (o `SOFA_SPORT`); las secciones
que no existan aparecerán como `unavailable` en vez de romper nada. Las que sí
son de otro deporte (`point_by_point`, `innings`...) se piden solas cuando el
partido lo es.

### Si te bloquean

Lo primero es `pip install curl_cffi` (ver [en el README](../README.md#por-qué-curl_cffi)), que
resuelve el caso normal. El framework se prueba además con los dos hosts de la
API antes de rendirse, y si aun así te responden 403 te lo dice con la salida
escrita en el propio error, no con un `HTTP 403` a secas.

Si ni con eso, el transporte es enchufable y no hace falta tocar nada más —aquí
con `curl_cffi` a mano, pero vale igual `playwright` o un proxy tuyo:

```python
from curl_cffi import requests as cr
from cancha import SofascoreClient
from cancha.transport import CallableTransport

sesion = cr.Session(impersonate="chrome")
cliente = SofascoreClient(transport=CallableTransport(
    lambda m, url, h: (lambda r: (r.status_code, r.content))(sesion.request(m, url, headers=h))
))
```

`curl_cffi`, `playwright` o lo que prefieras son dependencias tuyas: el
framework sigue sin necesitar ninguna.

## Errores

Todos heredan de `SofascoreError`, así que un solo `except` te cubre:

```python
from cancha import MatchNotFound, PlusRequired, RateLimited, SofascoreError

try:
    partido = get_match("Equipo Inventado")
except MatchNotFound as exc:
    print(exc)   # explica cómo afinar la consulta
except SofascoreError as exc:
    print(f"algo ha fallado: {exc}")
```

---

[← Volver al índice](../README.md)
