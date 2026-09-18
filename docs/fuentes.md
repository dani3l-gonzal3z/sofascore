# Otras fuentes

Sofascore es la fuente principal, pero no la única:

```bash
cancha fuentes                     # qué hay y qué aporta cada una
cancha contexto 12437616           # un partido visto por todas a la vez
```

| Fuente | Qué aporta |
| --- | --- |
| **Sofascore** | Partidos, equipos, jugadores y competiciones. La base de todo. |
| **Understat** | xG disparo a disparo, de un modelo **distinto**. Cinco grandes ligas. |
| **ClubElo** | Elo de clubes europeos desde 1939. Cuánto vale de verdad un rival. |
| **football-data.co.uk** | Resultados, tiros, tarjetas, árbitro y **cuotas de cierre** por liga y temporada desde 1993. CSV, sin anti-bot. |
| **ESPN** | Agenda independiente, clasificación, resumen de partido y **noticias** (lesiones, destituciones). JSON público. |
| **ScraperFC** *(si está instalada)* | FBref (abre un navegador), Transfermarkt (valores de mercado), Capology (salarios). |
| **soccerdata** *(si está instalada)* | FBref sin navegador, SoFIFA, WhoScored. Cinco grandes ligas. |

### Lo que aquí se hace distinto

`soccerdata` y `ScraperFC` te dan una tabla por fuente y el emparejado te lo
comes tú: los equipos se llaman distinto en cada sitio, los partidos llevan ids
distintos y las temporadas se numeran distinto. Aquí eso lo hace el framework.

```bash
cancha contexto "Real Madrid vs Barcelona" --date 2024-10-26
```
```
Real Madrid 0 - 4 FC Barcelona  (LaLiga, 2024-10-26)

  xG Sofascore      1.48 - 2.58
  xG Understat      1.31 - 2.79

  Discrepancia máxima entre modelos: 0.21
  Los dos modelos coinciden: el xG es sólido.

  Elo  Real Madrid 2010.1 (#2)  vs  Barcelona 1995.7 (#3)
       Probabilidad del local según Elo: 52%
```

**Dos modelos de xG que discrepan son información, no ruido**: donde no se
ponen de acuerdo suele haber penaltis, remates bloqueados o tiros muy lejanos,
que cada modelo pondera distinto. La IA tiene esa comparación en una sola
llamada (`contexto_externo`).

Además, todas las fuentes comparten transporte, caché, errores tipados y modo
offline, **cada una con su propio ritmo, su paciencia y sus raíces de
reserva**: ClubElo aguanta dos peticiones por segundo pero tarda en contestar
(30 s de espera, y si https no va se prueba http), y Understat no es una API
pública y se le va despacio. Añadir una
fuente es heredar de `Fuente` y escribir lo que trae.

### Las cuotas: quién era favorito

```bash
cancha cuotas                        # rellena las de la memoria desde football-data.co.uk
cancha contexto 12437616             # enseña el mercado de Sofascore y el de cierre
```

No es para apostar. Las cuotas se convierten a probabilidades **quitando el
margen de la casa** (tres cuotas de 2.00 no son un 50 % cada una, son un
tercio) y de ahí sale quién era favorito y con qué claridad. Es la variable que
separa «rinde peor contra bloque bajo» de «rinde peor siendo favorito»: ver
[Jugador contra sistema](sistemas.md#el-sistema-o-el-contexto).

El barrido las pide de Sofascore (`odds_featured`) con el resto. Para lo
barrido antes, `cancha cuotas` las saca de football-data.co.uk emparejando por
nombres y fecha, una temporada por petición.

### Las noticias

```bash
cancha noticias laliga --equipo "Real Madrid"
```

Lesiones, sanciones, destituciones, fichajes: el contexto que ningún número
trae y que una IA sí puede leer (`noticias`). Salen de ESPN, que cubre las
grandes ligas, MLS, Arabia y las copas europeas.

### FBref, Transfermarkt y Capology: las librerías de referencia

Hay datos que este framework no va a scrapear por su cuenta. **FBref** exige un
navegador desde que endureció su anti-bot (ScraperFC 4 abre Chrome para
leerlo); **Transfermarkt** y **Capology** son HTML que cambia. Las dos librerías
de referencia llevan años manteniendo esos lectores, y reescribirlos aquí sería
copiar su trabajo y heredar su fragilidad sin su mantenimiento.

Así que se usan, si están:

```bash
pip install "cancha[scraperfc]"      # o pip install ScraperFC
pip install "cancha[soccerdata]"     # o pip install soccerdata
cancha fuentes                       # dice cuáles hay
```

El framework las detecta y las expone con la misma forma que el resto —listas
de diccionarios, nuestros nombres de liga, errores tipados— a través de
`cancha.sources.externas` y de la herramienta `datos_externos`. Si no están,
la respuesta dice qué instalar. Todo eso se ejecuta en tu máquina, tarda y
necesita red: pide poco y concreto.

```python
from cancha.sources import adaptador

sd = adaptador("soccerdata")
sd.fbref_jugadores("laliga", 2024, tipo="shooting", maximo=30)

sfc = adaptador("scraperfc")
sfc.temporadas("transfermarkt", "laliga")      # el formato exacto que pide
sfc.transfermarkt_valores("laliga", "24/25")
```

**Ninguna de las fuentes nuevas se ha podido probar contra el servicio real
desde donde se escribió**: los tests usan respuestas con la forma que
documentan `soccerdata` y los propios sitios. Si algo no cuadra la primera
vez, `cancha raw` y la sección de contribución dicen cómo mirar la respuesta.

## De dónde salen las rutas

La API que usa la web de Sofascore no está documentada. Las rutas de este
framework están **contrastadas una a una** con las librerías públicas que llevan
años hablando con ella: [`ScraperFC`](https://pypi.org/project/ScraperFC/),
[`soccerdata`](https://pypi.org/project/soccerdata/),
[`sofascore-wrapper`](https://pypi.org/project/sofascore-wrapper/),
[`sofascrape`](https://pypi.org/project/sofascrape/) y
[`pysofascore`](https://pypi.org/project/pysofascore/). Cuando una ruta aparece
en varias de ellas, es la que funciona de verdad.

De ese repaso salieron tres cosas que aquí ya están puestas:

- la **probabilidad de victoria** cuelga de `/event/{id}/graph/win-probability`,
  no de `/event/{id}/win-probability`;
- el **catálogo de ligas** (nombre → id de competición) y la tabla de **códigos
  de estado** (`100` = *Ended*, `7` = *2nd half*...);
- las **claves de estadística** que devuelve la API — 110 de jugador y las
  habituales de equipo—, que es lo que hace posible `partido.suggest()`.

Si alguna ruta cambiara, la sección saldría como `unavailable` en el resumen en
vez de romper el informe, y corregirla es una línea en `endpoints.py`.

## Comparado con otras librerías

Si lo que quieres es sacar datos de varias fuentes y ponerte a analizar cuanto
antes, `soccerdata` y `ScraperFC` están más rodados: cubren FBref, Understat,
WhoScored, Transfermarkt y más, y llevan años de parches.

Este framework hace tres cosas que no encontré en ellos:

1. **Un informe, no un wrapper.** Los demás te dan `get_lineups(id)`,
   `get_statistics(id)`... y tú ensamblas. Aquí dices el partido y llegan las 30
   secciones a la vez, cada una con su estado.
2. **Sofascore Plus.** Ninguno contempla autenticación: todos asumen acceso
   anónimo. Aquí, si tienes la suscripción, pones tu sesión y esas secciones
   dejan de salir bloqueadas.
3. **Cero dependencias.** `pysofascore` arrastra `scrapling` y `curl_cffi`;
   `sofascore-wrapper` levanta un Chromium con Playwright; `soccerdata` y
   `ScraperFC` traen pandas y compañía. Esto funciona con la biblioteca estándar.

---

[← Volver al índice](../README.md)
