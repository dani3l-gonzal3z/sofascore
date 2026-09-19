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

Cinco pestañas, y la de **Hoy** es la que se abre.

| Pestaña | Qué enseña |
| --- | --- |
| **Hoy** | Los partidos del día, **plegados**: hora, equipos, la barra del mercado, la forma de cada uno y las insignias que importan. Tocar uno lo abre **ahí mismo**, sin cambiar de página: mercado, cómo llega cada equipo, dónde se pueden hacer daño, jugador contra sistema y árbitro. Arriba, el resumen de lo casi seguro del día. |
| **Casi seguro** | Lo que se repite, con su número. Cada aviso lleva la frecuencia, el suelo de confianza, cuántos casos lo sostienen y cuánto se separa de su referencia. La pestaña *Los patrones* enseña la calibración entera. |
| **Analista** | Pregunta en castellano y un modelo local busca los datos. Los pasos se ven mientras ocurren: qué herramienta pidió y cuánto le contestaron. |
| **Buscar** | Partido, equipo, jugador o duelo, con un selector arriba. |
| **Memoria** | Qué hay guardado, el barrido en segundo plano con su registro, el catálogo de competiciones y cuántas faltan por identificar, árbitros, fuentes y ajustes (clave y tema). |

### Las tarjetas plegadas

Es la idea de la que sale el diseño: **un partido ocupa una línea hasta que lo
abres**. En esa línea caben las tres cosas que deciden si te interesa —quién es
favorito según el mercado, cómo llegan los dos y si hay algo que casi siempre
pasa— y el resto está a un toque, en su sitio, sin perder la lista.

La previa se pide **cuando abres la tarjeta**, no antes: veinte partidos en
pantalla no son veinte análisis, son veinte líneas.

### El tema

Claro, oscuro o automático, en Memoria → Ajustes. El automático sigue al
sistema, que es lo que hace el iPhone por la noche.

## La API

Todo cuelga de `POST /api/herramienta/<nombre>` con los argumentos en JSON:
las 41 herramientas de la IA, con la misma sesión para toda la vida del
servidor (lo ya traído no se vuelve a pedir). Además:

| Ruta | Qué |
| --- | --- |
| `GET /api/estado` | Memoria, catálogo de competiciones, fuentes, librerías, briefings, modelo |
| `GET /api/herramientas` | Los esquemas de las herramientas |
| `GET /api/briefing/AAAA-MM-DD` | El briefing guardado de ese día |
| `POST /api/seguro` | Los avisos del día, o la calibración entera con `calibrar: true` |
| `POST /api/analista` | Una pregunta al modelo local. Contesta en **NDJSON**, un paso por línea |
| `GET /api/analista` | Si Ollama está, qué modelos tiene y si LangChain está instalado |
| `POST /api/barrido` | Lanza un barrido (`fecha`, `grupos`, `max`) en segundo plano |
| `GET /api/barrido` | Cómo va: líneas de registro y resumen al acabar |

El analista va en streaming a propósito: sin él verías un minuto de reloj
girando y luego un párrafo. Cada línea es `{"paso": …}` mientras trabaja y
`{"fin": …}` al terminar, con el historial para seguir la conversación.

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
