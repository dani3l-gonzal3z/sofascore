# La interfaz

```bash
cancha web              # en este ordenador: http://127.0.0.1:8765
cancha web --lan        # y desde el móvil: dibuja un QR, apuntas la cámara
cancha web --abrir      # abre el navegador al arrancar
```

Es un servidor de la **biblioteca estándar** —ni un paquete más— sirviendo una
página y una API JSON encima de las mismas herramientas que ve la IA. Lo que la
IA puede preguntar, la página lo enseña; y al revés.

## Instalarla como aplicación

**Windows.** Abre la dirección en Edge o Chrome y usa «Instalar cancha» (el
icono de la barra de direcciones, o el menú ⋯ → Aplicaciones). Queda en el menú
de inicio con su ventana propia.

**iOS.** Arranca con `--lan` y el terminal **dibuja un código QR**: apuntas la
cámara del iPhone y entras. Luego Compartir → **«Añadir a pantalla de inicio»**
y se abre a pantalla completa, con su icono, recordando la última pestaña.
Necesita que el ordenador esté encendido y en la misma wifi: es tu máquina la
que hace el trabajo.

Si abres la interfaz a la red, ponle clave:

```bash
cancha web --lan --clave loquesea
```

**La clave va dentro del QR**, así que el móvil entra sin que la teclees: la
página la coge de la dirección, la guarda y la borra de la barra para que no
se quede en el historial. También se puede poner a mano en Memoria → Ajustes.

El QR no es un paquete más: está escrito aquí (`cancha/web/qr.py`, versiones
1 a 10, Reed-Solomon sobre GF(256)) porque el proyecto no tiene dependencias y
no iba a empezar por esto. Con `--sin-color` se dibuja sin ANSI, y con
`--sin-qr` no se dibuja.

Si el ordenador tiene varias IP —una VPN, Docker, WSL— se enseñan **todas**, la
de la ruta por defecto primero: enseñar una sola y que sea la que no es deja al
móvil sin entrar y sin saber por qué.

Y si ya estás en el ordenador, la pestaña **Memoria → Abrirlo en el móvil**
pinta el mismo QR en pantalla.

## Qué hay dentro

Cinco pestañas, y la de **Hoy** es la que se abre. **Todo lo que hace el
framework se puede hacer desde aquí**, también desde el móvil: no hay nada que
obligue a volver al terminal.

| Pestaña | Qué enseña |
| --- | --- |
| **Hoy** | Los partidos del día, **plegados**: hora, equipos, la barra del mercado, la forma de cada uno y las insignias que importan. Tocar uno lo abre **ahí mismo**, sin cambiar de página: mercado, cómo llega cada equipo, dónde se pueden hacer daño, jugador contra sistema y árbitro. Arriba, el resumen de lo casi seguro del día. El selector **Directo** enseña lo que se está jugando ahora, refrescándose solo. |
| **Casi seguro** | Lo que se repite, con su número. Cada aviso lleva la frecuencia, el suelo de confianza, cuántos casos lo sostienen y cuánto se separa de su referencia. La pestaña *Los patrones* enseña la calibración entera. |
| **Analista** | Pregunta en castellano y un modelo local busca los datos. Los pasos se ven mientras ocurren: qué herramienta pidió y cuánto le contestaron. Debajo, **Dictamen**: el expediente entero de un partido a un modelo de una vez, con el documento que se le manda a la vista y, si usas la nube, el aviso de que eso sale de tu ordenador ([Dictamen](dictamen.md)). |
| **Buscar** | Partido, equipo, jugador, **liga** o duelo, con un selector arriba. El partido trae alineaciones, cronología, quién mandaba tramo a tramo, historial entre los dos, quién generó el peligro y los datos en crudo de cualquier sección. El equipo y el jugador traen su ficha completa, y el equipo además su Elo. La liga trae clasificación, histórico desde 1993, ranking Elo, agenda y noticias de ESPN y las tablas de FBref. |
| **Memoria** | Qué hay guardado, el barrido en segundo plano con su registro, el catálogo de competiciones (y un botón para buscar los ids que faltan), rellenar cuotas, árbitros, fuentes, el QR para abrirlo en el móvil, el **diagnóstico** (lo que dice `cancha doctor`, más la caché), los **[ajustes](ajustes.md)** —donde se le puede poner el token del bot de Telegram sin reiniciar nada, y se ve si está escuchando— y la **consola de herramientas**. |

### Las tarjetas plegadas

Es la idea de la que sale el diseño: **un partido ocupa una línea hasta que lo
abres**. En esa línea caben las tres cosas que deciden si te interesa —quién es
favorito según el mercado, cómo llegan los dos y si hay algo que casi siempre
pasa— y el resto está a un toque, en su sitio, sin perder la lista.

La previa se pide **cuando abres la tarjeta**, no antes: veinte partidos en
pantalla no son veinte análisis, son veinte líneas.

### La consola de herramientas

Las pantallas de arriba cubren lo de cada día. La consola cubre el resto: pide
la lista al servidor (`GET /api/herramientas`), monta los campos desde el
esquema de cada una y enseña el JSON tal cual lo recibiría la IA. Como la lista
viene del servidor, **una herramienta nueva aparece sola**, sin tocar la
página. Es lo que garantiza que «todo se puede hacer desde el móvil» siga
siendo verdad mañana.

### El tema

Claro, oscuro o automático, en Memoria → Ajustes. El automático sigue al
sistema, que es lo que hace el iPhone por la noche.

## La API

Todo cuelga de `POST /api/herramienta/<nombre>` con los argumentos en JSON:
las 44 herramientas de la IA, con la misma sesión para toda la vida del
servidor (lo ya traído no se vuelve a pedir). Además:

| Ruta | Qué |
| --- | --- |
| `GET /api/estado` | Memoria, catálogo de competiciones, fuentes, librerías, briefings, modelo |
| `GET /api/herramientas` | Los esquemas de las herramientas |
| `GET /api/briefing/AAAA-MM-DD` | El briefing guardado de ese día |
| `POST /api/seguro` | Los avisos del día, o la calibración entera con `calibrar: true` |
| `POST /api/analista` | Una pregunta al modelo local. Contesta en **NDJSON**, un paso por línea |
| `GET /api/analista` | Si Ollama está, qué modelos tiene y si LangChain está instalado |
| `POST /api/dictamen` | Monta el expediente de un partido y se lo da entero a un modelo ([Dictamen](dictamen.md)) |
| `POST /api/barrido` | Lanza un barrido (`fecha`, `grupos`, `max`) en segundo plano |
| `GET /api/barrido` | Cómo va: líneas de registro y resumen al acabar |
| `GET /api/diagnostico` | Transportes, credenciales, caché y grabaciones. Con `?red=1` prueba contra la API |
| `POST /api/cache` | Vacía la caché de disco |
| `POST /api/ligas` | Busca los ids de competición que falten (necesita red) |
| `GET /api/red` | Por dónde se llega a este servidor, con la matriz del QR ya calculada |

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
