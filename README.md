# Sofascore Framework

Te lo descargas, le dices un partido y te devuelve **todos sus datos**: marcador,
estadísticas, alineaciones, cronología, momento de ataque, cara a cara, forma
previa... Y si tienes **Sofascore Plus**, también las secciones de pago, usando
tu propia sesión.

```bash
sofascore match "Real Madrid vs Barcelona" --date 2024-10-26
```

```python
from sofascore import get_match

partido = get_match("Real Madrid vs Barcelona", date="2024-10-26")

print(partido.event.label)                    # Real Madrid 0 - 4 Barcelona (LaLiga, 2024-10-26)
print(partido.statistic("expectedGoals"))     # {'name': 'Goles esperados (xG)', 'home': '1.24', ...}
print(partido.goals())                        # cronología de goles
print(partido.available())                    # secciones con datos
print(partido.locked())                       # secciones que requieren Plus
```

- **Cero dependencias.** Solo biblioteca estándar de Python 3.10+. `pip install`
  y a funcionar; `httpx` es opcional si quieres otro transporte.
- **Nada te tumba el informe.** Si una sección falla, no existe para ese deporte
  o está detrás del muro de pago, queda marcada y el resto sigue adelante.
- **Educado con la API.** Límite de peticiones por segundo, reintentos con
  espera creciente y caché en disco (un partido terminado no se vuelve a pedir).
- **Probado sin red.** 101 tests que corren en menos de un segundo con
  respuestas de ejemplo.

---

## Instalación

```bash
cd Sofascore
pip install -e .            # instala el comando `sofascore`
pip install -e ".[dev]"     # además, pytest para los tests
```

O sin instalar nada: copia la carpeta `sofascore/` a tu proyecto y usa
`python -m sofascore.cli ...`.

## Cómo se nombra un partido

Las cuatro formas valen, elige la que te resulte más cómoda:

| Forma | Ejemplo |
| --- | --- |
| Nombres de los equipos | `"Real Madrid vs Barcelona"` (`vs`, `-`, `x`, `contra`...) |
| Con fecha para desempatar | `--date 2024-10-26` |
| URL de Sofascore | `https://www.sofascore.com/.../#id:11352550` |
| Id del evento | `11352550` |

Si dos equipos se han cruzado muchas veces, el framework elige el partido más
cercano en el tiempo y te avisa de cuántos candidatos había. Con `--strict`
falla en vez de elegir; con `sofascore search` los ves todos:

```bash
sofascore search "Betis Sevilla"
```

## La línea de comandos

```bash
sofascore match <consulta> [opciones]     # informe completo
sofascore search <consulta>               # partidos candidatos
sofascore sections                        # catálogo de secciones
sofascore login [partido]                 # comprueba tus credenciales Plus
sofascore raw /event/11352550/statistics  # cualquier ruta de la API, tal cual
sofascore cache [--clear]                 # estado de la caché
```

Opciones más usadas de `match`:

| Opción | Para qué |
| --- | --- |
| `--date AAAA-MM-DD` | Desempatar entre varios cruces |
| `--all` | Pedir todas las secciones del catálogo |
| `--sections statistics,shotmap` | Solo las que te interesan |
| `--no-plus` | Ni intentar las de pago |
| `--json p.json` `--markdown p.md` `--csv carpeta/` | Guardar el resultado |
| `--print statistics` | Volcar una sola sección por pantalla |
| `--stdout-json` | El informe entero en JSON, listo para `jq` |
| `--offline` / `--no-cache` | Solo caché / ignorar caché |
| `--debug` | Contadores de peticiones y ajustes en uso |

```bash
sofascore match 11352550 --all --json partido.json --csv datos/
sofascore match 11352550 --print statistics --quiet | jq '.[0].groups'
```

## Qué trae cada informe

`sofascore sections` lista el catálogo completo. Por defecto vienen:

| Sección | Contenido |
| --- | --- |
| `event` | Marcador, estado, competición, sede, árbitro, asistencia |
| `statistics` | Posesión, tiros, pases, duelos, xG... por periodo |
| `lineups` | Titulares, suplentes, dorsales, formación, valoraciones |
| `incidents` | Goles, tarjetas, cambios, VAR, penaltis |
| `momentum` | Presión/momento de ataque minuto a minuto |
| `best_players` | Mejores jugadores según Sofascore |
| `managers` | Entrenadores |
| `h2h` | Balance histórico entre los dos equipos |
| `pregame_form` | Forma y clasificación antes del partido |

Bajo demanda (`--sections` o `--all`): `votes`, `h2h_events`, `team_streaks`,
`odds`, `highlights`, `comments`, `standings`.

Y las que Sofascore suele reservar a Plus: `shotmap` (xG por disparo),
`average_positions`, `player_statistics`, `heatmaps`, `win_probability`.

Cada sección termina en uno de estos estados, y lo verás en el resumen:

| Estado | Significado |
| --- | --- |
| `ok` | Datos recibidos |
| `empty` | La sección existe pero no tiene contenido (partido sin jugar, por ejemplo) |
| `plus_required` | Hace falta Sofascore Plus y no hay credenciales válidas |
| `unavailable` | Ese partido o deporte no tiene esa sección |
| `error` | Fallo de red o de la API |

## Sofascore Plus

**El framework no rompe ni esquiva ningún muro de pago.** Si tienes la
suscripción, tu navegador ya recibe esos datos porque tu sesión está
autenticada; aquí simplemente reutilizas *tu* sesión para pedir lo mismo desde
Python. Sin credenciales, esas secciones salen como `plus_required` y el
informe sigue con todo lo público.

Copia `.env.example` a `.env` y rellena **una** de las tres opciones:

```ini
SOFA_PLUS_COOKIE=          # la cabecera Cookie de tu navegador con sesión iniciada
SOFA_PLUS_TOKEN=           # o un token Bearer de tu cuenta
SOFA_PLUS_COOKIE_FILE=     # o un JSON de cookies exportado del navegador
```

Comprueba que funcionan:

```bash
sofascore login 11352550
# ✓ Las credenciales funcionan: se han recibido datos de pago.
```

Son credenciales personales: no las compartas ni las subas a ningún repositorio
(`.env` está en `.gitignore`). Caducan, así que si un día `login` dice que no
las aceptan, vuelve a copiarlas.

## Usarlo como librería

```python
from sofascore import SofascoreClient, Settings, build_report, resolve_event

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
| `config.py` | Ajustes desde entorno y `.env` (prefijo `SOFA_`) |
| `transport.py` | HTTP con `urllib`, con `httpx` o falso (para tests) |
| `cache.py` | Caché en disco, en memoria o ninguna |
| `ratelimit.py` | Espaciado de peticiones |
| `auth.py` | Tus credenciales de Plus |
| `endpoints.py` | Catálogo declarativo de secciones |
| `client.py` | Peticiones, reintentos, errores tipados |
| `resolve.py` | De «un partido» a un id de evento |
| `match.py` | El informe agregado |
| `export.py` | JSON, Markdown y CSV |
| `cli.py` | La línea de comandos |

### Añadir una sección nueva

Es una línea en `endpoints.py`; no hay que tocar el cliente:

```python
Section("mi_seccion", "/event/{event_id}/lo-que-sea",
        "Qué trae esta sección.", unwrap="clave", default=False)
```

### Otro deporte

El catálogo está pensado para fútbol, pero la API comparte estructura. Cambia el
deporte de las búsquedas con `--sport basketball` (o `SOFA_SPORT`); las secciones
que no existan aparecerán como `unavailable` en vez de romper nada.

## Errores

Todos heredan de `SofascoreError`, así que un solo `except` te cubre:

```python
from sofascore import MatchNotFound, PlusRequired, RateLimited, SofascoreError

try:
    partido = get_match("Equipo Inventado")
except MatchNotFound as exc:
    print(exc)   # explica cómo afinar la consulta
except SofascoreError as exc:
    print(f"algo ha fallado: {exc}")
```

## Desarrollo

```bash
python -m pytest                  # 101 tests, sin red
python examples/demo_offline.py   # el informe completo con datos de ejemplo
```

Los tests usan `FakeTransport` y respuestas guardadas en `tests/fixtures/`:
nada sale a internet, así que corren igual de rápido con o sin conexión.

## Aviso

Proyecto **no oficial**, sin relación con Sofascore. Usa su API pública igual
que lo haría un navegador y está pensado para uso personal y análisis propio.
Respeta sus condiciones de servicio, no subas el límite de peticiones sin
motivo y no redistribuyas datos que no sean tuyos. Las credenciales de Plus son
tuyas y solo tuyas: el framework las usa para pedir *tus* datos, nunca para
saltarse una suscripción que no tengas.
