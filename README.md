# cancha

[![tests](https://github.com/dani3l-gonzal3z/sofascore/actions/workflows/tests.yml/badge.svg)](https://github.com/dani3l-gonzal3z/sofascore/actions/workflows/tests.yml)

Le dices un partido y te devuelve **todos sus datos** —de Sofascore, Understat,
ClubElo, football-data.co.uk y ESPN, y de FBref o Transfermarkt si tienes sus
librerías— ya cruzados y listos para analizar. Setenta y una competiciones,
masculinas y femeninas, de Europa y de América. Por línea de comandos, como
librería, **como herramientas para una IA local** o en una interfaz que se
instala en Windows y en el iPhone.

```bash
cancha arrancar                # todo: interfaz, guardia nocturna y bot de Telegram
                               # (en Windows: doble clic en cancha.bat)
cancha web --lan               # solo la interfaz: QR en el terminal, y al móvil
cancha briefing --barrer       # el documento de la mañana: todos los partidos del día
cancha seguro                  # lo que casi siempre pasa, con el número que lo sostiene
cancha pronostico "Girona vs Osasuna"  # marcador, córners y tarjetas, calculados
cancha analista "¿cómo llega el Girona?"   # pregunta y un modelo local lo busca
cancha dictamen "Girona vs Osasuna"    # todo el expediente a un modelo, que ate cabos
cancha estilo "Girona"         # cómo juega, comparado con su liga
cancha forma "Vinicius Junior" # rachas: 4 partidos sin tirar entre palos
cancha duelo "Vinicius" "Getafe"    # cómo le va contra ese sistema, con su significación
cancha analisis 12437616       # puntos esperados, calidad de tiro, carrera de xG
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
- **Memoria.** Una base local con lo que se va viendo, para poder decir cómo
  juega un equipo *comparado con su liga* o cuántos partidos lleva alguien sin
  rematar entre palos. Eso no se contesta mirando un partido. Y si falta algo,
  `--abastecer` trae los últimos diez de cada equipo, lo que han jugado entre
  ellos y lo del árbitro: unos cuarenta partidos, minuto y medio la primera
  vez y casi nada las siguientes, porque la memoria se solapa consigo misma.
- **Se lo deja trabajando de noche.** `cancha arrancar` levanta la interfaz, la
  **guardia nocturna** —que a las tres de la mañana trae los partidos de
  mañana y todo su contexto, para que por la mañana esté hecho— y un **bot de
  Telegram** para preguntarle desde la calle sin abrir ningún puerto. En
  Windows le pide al sistema que no se suspenda mientras trabaja, porque si el
  equipo se duerme el proceso se duerme con él.
- **Una interfaz sin dependencias.** `cancha web` sirve una página desde tu
  ordenador que se instala como app en Windows y en iOS. Los partidos del día
  vienen plegados en una línea y se abren donde están, y **todo lo que sabe
  hacer el framework se puede hacer desde el móvil**: no queda nada que
  obligue a volver al terminal. Con `--lan` el terminal dibuja un **QR** —con
  la clave dentro— y entras apuntando la cámara.
- **71 competiciones, ellas y ellos.** Las cinco grandes europeas en los dos
  géneros, la Champions femenina, MLS, NWSL, Liga MX y Sudamérica entera. Los
  ids que no estaban contrastados **se descubren solos**, comprobando país y
  género: aquí no se inventa un número que barrería otra liga en silencio.
- **Un analista en tu máquina.** `cancha analista` habla con Ollama y le da las
  44 herramientas. Cada paso se ve, y las instrucciones le prohíben decir una
  cifra que no le hayan dado.
- **Y el expediente entero a un modelo grande.** `cancha dictamen "Girona vs
  Osasuna"` reúne todo lo que se sabe de un partido —el pronóstico ya
  calculado, los estilos, los cruces, los últimos partidos, el árbitro, el
  mercado y los patrones— y se lo da de una vez, en una sola llamada, para que
  ate cabos en vez de buscar. Unos 900 tokens por partido. Va con el Ollama de
  tu casa o, con una clave, con un modelo grande en su nube; en ese segundo
  caso **los datos del partido salen de tu ordenador** y lo dice cada vez.
- **Y si no hay muestra, lo dice.** «Contra bloque bajo tira la mitad» solo sale
  si la diferencia no cabe en lo que explica el azar; con tres partidos, la
  respuesta es *no se sabe*.
- **Probado sin red.** 965 tests en menos de doce segundos, y un modo de grabar
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

Con `--transport` (o `CANCHA_TRANSPORT`) eliges a mano: `auto`, `curl`, `httpx`
o `urllib`.

### Si el comando `cancha` no se encuentra

Al instalar, pip deja `cancha.exe` en una carpeta que **en Windows no suele
estar en el PATH**, y te lo avisa. No hace falta configurar nada: **`python -m
cancha` hace exactamente lo mismo**.

```bash
python -m cancha match "Real Madrid vs Barcelona" --date 2024-10-26
python -m cancha grabar 12437616
```

Si prefieres el comando a secas, añade al PATH de tu usuario la carpeta que te
dijo pip (una vez, y luego reabre la terminal):

```powershell
$scripts = "$env:APPDATA\Python\Python312\Scripts"   # la que te diga pip
[Environment]::SetEnvironmentVariable(
    "Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$scripts", "User")
```

Y sin instalar nada: copia la carpeta `cancha/` a tu proyecto y usa
`python -m cancha ...` desde el directorio que la contiene.

## Documentación

| | |
| --- | --- |
| [La memoria](docs/memoria.md) | Barrido diario, estilo de equipo, rachas de jugador, árbitros, previas |
| [La interfaz](docs/interfaz.md) | `cancha web`: una página que se instala en Windows y en iOS |
| [Dejarlo funcionando](docs/dejarlo-funcionando.md) | `cancha arrancar`: la guardia nocturna y el bot de Telegram |
| [Ajustes](docs/ajustes.md) | La hora, las ligas, el modelo: decidirlo una vez |
| [Casi seguro](docs/seguro.md) | Lo que se repite, medido: frecuencia, suelo de Wilson y elevación |
| [El pronóstico](docs/pronostico.md) | Marcador exacto, córners y tarjetas, calculados y contra el mercado |
| [El analista local](docs/analista.md) | Ollama con Hermes, y el adaptador a LangChain |
| [Dictamen](docs/dictamen.md) | El expediente entero a un modelo grande, con la nube de Ollama |
| [Jugador contra sistema](docs/sistemas.md) | Cómo rinde alguien según a qué se enfrenta, con su prueba de significación |
| [Partidos](docs/partidos.md) | Cómo se nombra uno, qué trae el informe, las tablas |
| [Equipos, jugadores y ligas](docs/entidades.md) | Fichas, plantillas, clasificaciones, en directo |
| [Análisis](docs/analisis.md) | Puntos esperados, calidad de tiro, carrera de xG |
| [Fuentes de datos](docs/fuentes.md) | Understat, ClubElo, el cruce y de dónde salen las rutas |
| [Para una IA local](docs/ia.md) | Las 44 herramientas, MCP y cómo indaga |
| [La línea de comandos](docs/comandos.md) | Todos los comandos y sus opciones |
| [Sofascore Plus](docs/plus.md) | Tus credenciales, y por qué casi no hacen falta |
| [Usarlo como librería](docs/libreria.md) | La API de Python, los módulos, los errores |
| [Desarrollo](docs/desarrollo.md) | Tests, grabar respuestas reales, CI |
| [Cambios](CHANGELOG.md) | Qué ha ido pasando en cada versión |

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
