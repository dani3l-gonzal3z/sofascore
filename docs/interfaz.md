# La interfaz

```bash
cancha web              # en este ordenador: http://127.0.0.1:8765
cancha web --lan        # y desde el móvil, en la misma wifi
cancha web --abrir      # abre el navegador al arrancar
```

Es un servidor de la **biblioteca estándar** —ni un paquete más— sirviendo una
página y una API JSON encima de las mismas herramientas que ve la IA. Lo que la
IA puede preguntar, la página lo enseña; y al revés.

## Instalarla como aplicación

**Windows.** Abre la dirección en Edge o Chrome y usa «Instalar cancha» (el
icono de la barra de direcciones, o el menú ⋯ → Aplicaciones). Queda en el menú
de inicio con su ventana propia.

**iOS.** Arranca con `--lan`; el terminal te dice la dirección de tu ordenador
en la red (por ejemplo `http://192.168.1.34:8765`). Ábrela en Safari desde el
iPhone, pulsa Compartir → **«Añadir a pantalla de inicio»**. Se abre a pantalla
completa, con su icono, y recuerda la última pestaña. Necesita que el ordenador
esté encendido y en la misma wifi: es tu máquina la que hace el trabajo.

Si abres la interfaz a la red, ponle clave:

```bash
cancha web --lan --clave loquesea
```

La página la pide una vez (pestaña Memoria → Acceso) y la recuerda.

## Qué hay dentro

| Pestaña | Qué enseña |
| --- | --- |
| **Hoy** | La agenda del día por competición. Si hay [briefing](memoria.md#el-briefing) generado, cada partido lleva quién es favorito y cuántos duelos relevantes tiene. Tocar uno abre la previa: mercado, cómo llega cada equipo, rachas, dónde se pueden hacer daño, jugador contra sistema, árbitro. |
| **Partido** | Busca por nombres, URL o id. Marcador, estadísticas comparadas, *¿ganó el que mereció?*, carrera de xG, calidad de las ocasiones, todos los tiros, mejores valoraciones y, si lo pides, el contexto de las otras fuentes (Understat, ClubElo, football-data). |
| **Equipo** | Cómo juega comparado con su liga, con qué plantea (dibujo, presión, posesión, etiquetas relativas a su liga), si ha cambiado, y las noticias de ESPN. |
| **Jugador** | Forma, rachas, partido a partido, y **contra sistema** por los tres ejes con su veredicto (`señal`, `indicio`, `sin muestra`). El botón «¿Es el sistema o el contexto?» parte el análisis en dos: siendo favorito y sin serlo. |
| **Duelo** | Un jugador contra lo que suele plantear un rival concreto. |
| **Memoria** | Qué hay guardado, lanzar un barrido (corre en segundo plano y se ve el registro), árbitros, fuentes y librerías instaladas, clave. |

Todo lo que sale de la memoria necesita un barrido antes, y la página lo dice
en cada sitio en vez de dejar un hueco.

## La API

Todo cuelga de `POST /api/herramienta/<nombre>` con los argumentos en JSON:
las 41 herramientas de la IA, con la misma sesión para toda la vida del
servidor (lo ya traído no se vuelve a pedir). Además:

| Ruta | Qué |
| --- | --- |
| `GET /api/estado` | Memoria, fuentes, librerías, briefings guardados, versión |
| `GET /api/herramientas` | Los esquemas de las herramientas |
| `GET /api/briefing/AAAA-MM-DD` | El briefing guardado de ese día |
| `POST /api/barrido` | Lanza un barrido (`fecha`, `grupos`, `max`) en segundo plano |
| `GET /api/barrido` | Cómo va: líneas de registro y resumen al acabar |

Con `--clave`, la API exige la cabecera `X-Clave` (o `?clave=`); la página no.

```bash
curl -X POST http://127.0.0.1:8765/api/herramienta/duelo_jugador_rival \
     -H 'Content-Type: application/json' \
     -d '{"jugador": "Vinicius", "rival": "Getafe"}'
```

## Lo que no es

No es un servicio en internet: es **tu** ordenador sirviendo a **tu** móvil.
No hay usuarios, ni base de datos remota, ni nadie más en medio. Si quieres
verla desde fuera de casa, eso es un túnel (Tailscale, por ejemplo) y no cosa
de este proyecto.

---

[← Volver al índice](../README.md)
