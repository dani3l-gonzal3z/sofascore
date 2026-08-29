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
offline, **cada una con su propio ritmo** de peticiones: ClubElo aguanta dos por
segundo y Understat no es una API pública y se le va despacio. Añadir una
fuente es heredar de `Fuente` y escribir lo que trae.

### Lo que falta

**FBref** es la pieza gorda que no está: tablas HTML con la maña de venir
dentro de comentarios, y un límite de peticiones que banea por encima de una
cada tres segundos. Es su propio trabajo, no un rato. Igual **Transfermarkt**
(valores de mercado) y **WhoScored** (que necesita navegador). Si los quieres,
se piden.

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
