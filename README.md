# cancha

[![tests](https://github.com/dani3l-gonzal3z/sofascore/actions/workflows/tests.yml/badge.svg)](https://github.com/dani3l-gonzal3z/sofascore/actions/workflows/tests.yml)

Le dices un partido y te devuelve **todos sus datos** —de Sofascore, de
Understat y de ClubElo— ya cruzados y listos para analizar. Por línea de
comandos, como librería o **como herramientas para una IA local**.

```bash
cancha match "Real Madrid vs Barcelona" --date 2024-10-26
cancha analisis 12437616       # puntos esperados, calidad de tiro, carrera de xG
cancha contexto 12437616       # dos modelos de xG y el Elo de ambos equipos
cancha mcp                     # servidor MCP para tu IA local
```

```python
from cancha import get_match

partido = get_match("Real Madrid vs Barcelona", date="2024-10-26")
partido.statistic("expectedGoals")
partido.goals()
partido.available()            # secciones con datos
```

- **Cero dependencias obligatorias.** Solo biblioteca estándar de Python 3.10+.
  `curl_cffi` y `pandas` son opcionales y el CI comprueba que se puede vivir sin
  ellos.
- **Un informe, no veinte llamadas.** Pides el partido y llegan las 30 secciones
  a la vez, en paralelo, con el estado de cada una a la vista.
- **Nada te tumba el informe.** Si una sección falla, no existe para ese deporte
  o está detrás del muro de pago, queda marcada y el resto sigue.
- **Las cuentas hechas.** Puntos esperados, xG acumulado, calidad de tiro: los
  números que un modelo calcularía mal.
- **Probado sin red.** 398 tests en menos de un segundo, y un modo de grabar
  respuestas reales para comprobar que la API devuelve lo que aquí se supone.

---

## Instalación

```bash
pip install -e .             # instala el comando `sofascore`
pip install curl_cffi        # muy recomendable: ver abajo
pip install -e ".[pandas]"   # además, informe.frames() devuelve DataFrames
pip install -e ".[dev]"      # además, pytest para los tests
```

### Por qué `curl_cffi`

Sofascore está detrás de Cloudflare, y **Cloudflare no mira solo las cabeceras:
mira la huella del handshake TLS**. Una petición de `urllib` con cabeceras de
Chrome canta —el TLS es de Python— y se lleva un `403` por muy perfectas que
sean las cabeceras.

`curl_cffi` habla TLS *como* Chrome, así que la huella cuadra con lo que dicen
las cabeceras. Instalarlo es todo lo que hay que hacer: el framework lo detecta
solo y empieza a usarlo.

```bash
pip install curl_cffi
cancha doctor        # dice qué transporte usa y si la API contesta
```

No es un capricho de este proyecto: **ninguna** de las librerías que hablan con
esta API usa HTTP normal. `pysofascore` usa este mismo `curl_cffi`, `soccerdata`
usa `tls_requests`, y `ScraperFC` y `sofascore-wrapper` llegan a levantar un
navegador entero. Sigue siendo opcional —sin ella el framework funciona igual
desde una red que no esté bloqueada— pero si ves un `403`, es esto.

Con `--transport` (o `SOFA_TRANSPORT`) eliges a mano: `auto`, `curl`, `httpx`
o `urllib`.

Si al instalar te avisa de que `sofascore.exe` ha quedado en una carpeta *que
no está en el PATH* (habitual en Windows con instalación de usuario), no hace
falta configurar nada: `python -m sofascore` hace exactamente lo mismo.

```bash
python -m cancha match "Real Madrid vs Barcelona" --date 2024-10-26
```

Y sin instalar nada: copia la carpeta `sofascore/` a tu proyecto y usa
`python -m sofascore ...` desde el directorio que la contiene.

## Documentación

| | |
| --- | --- |
| [Partidos](docs/partidos.md) | Cómo se nombra uno, qué trae el informe, las tablas |
| [Equipos, jugadores y ligas](docs/entidades.md) | Fichas, plantillas, clasificaciones, en directo |
| [Análisis](docs/analisis.md) | Puntos esperados, calidad de tiro, carrera de xG |
| [Fuentes de datos](docs/fuentes.md) | Understat, ClubElo, el cruce y de dónde salen las rutas |
| [Para una IA local](docs/ia.md) | Las 23 herramientas, MCP y cómo indaga |
| [La línea de comandos](docs/comandos.md) | Todos los comandos y sus opciones |
| [Sofascore Plus](docs/plus.md) | Tus credenciales, y por qué casi no hacen falta |
| [Usarlo como librería](docs/libreria.md) | La API de Python, los módulos, los errores |
| [Desarrollo](docs/desarrollo.md) | Tests, grabar respuestas reales, CI |

## Cómo se llama esto

El paquete se llamaba `sofascore` hasta que empezó a hablar con tres fuentes.
Ahora es **`cancha`**, pero el nombre viejo sigue funcionando: `import
sofascore`, `python -m sofascore` y el comando `sofascore` valen igual y no hay
planes de quitarlos.

## Aviso

Proyecto **no oficial**, sin relación con Sofascore. Usa su API pública igual
que lo haría un navegador y está pensado para uso personal y análisis propio.
Respeta sus condiciones de servicio, no subas el límite de peticiones sin
motivo y no redistribuyas datos que no sean tuyos. Las credenciales de Plus son
tuyas y solo tuyas: el framework las usa para pedir *tus* datos, nunca para
saltarse una suscripción que no tengas.
