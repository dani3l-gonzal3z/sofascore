# Ajustes

Lo que se decide una vez y no se vuelve a escribir: la hora de la guardia, las
ligas que sigues, el modelo de Ollama, el puerto y el bot.

Tres sitios para tocarlo, y es el mismo fichero:

- **La pestaña Ajustes de la interfaz**, también desde el móvil.
- `cancha ajustes guardia.hora=02:30 modelo=qwen2.5:7b`
- `datos/ajustes.json` a mano.

## Quién manda

```
línea de comandos   >   datos/ajustes.json   >   lo de fábrica
```

Así puedes probar algo una vez sin cambiar lo de todos los días:

```bash
cancha guardia --a-las 02:00 --ahora      # solo esta vez
cancha ajustes guardia.hora=02:00         # a partir de ahora
```

## Qué se puede poner

| Ajuste | Qué | De fábrica |
| --- | --- | --- |
| `guardia.activa` | Si la guardia se pone en marcha con `cancha arrancar` | `true` |
| `guardia.hora` | A qué hora prepara el día siguiente, en hora local | `03:00` |
| `guardia.dias` | Qué día prepara: `1` es mañana | `1` |
| `guardia.partidos` | Cuántos partidos abastece a fondo | `12` |
| `guardia.max` | Tope de peticiones por vuelta (`0` = sin tope) | `0` |
| `guardia.ultimos` | Partidos recientes por equipo en el barrido | `6` |
| `guardia.registro` | Dónde escribe lo que va haciendo | `datos/guardia.log` |
| `ligas` | Las competiciones que sigues (ver abajo) | todas |
| `modelo` | Modelo de Ollama para el analista y el bot | `hermes3` |
| `ollama` | Dónde escucha Ollama | `http://127.0.0.1:11434` |
| `web.puerto` | Puerto de la interfaz | `8765` |
| `web.lan` | Abrirla a la wifi | `true` |
| `web.clave` | Clave de la interfaz | vacía |
| `telegram.token` | Token del bot | vacío |
| `telegram.chats` | Quién puede hablarle | vacío |
| `memoria`, `briefings` | Dónde viven los ficheros | `datos/…` |

**La hora se coge al vuelo.** La guardia mira los ajustes mientras espera, así
que cambiarla desde el móvil a las once de la noche vale para esa misma noche.
El puerto, la clave y el bot se leen al arrancar: la interfaz te avisa de cuáles
necesitan reiniciar.

## Las ligas

Vale cualquier combinación de tres cosas:

- **Grupos**: `grandes`, `uefa`, `europeas`, `usa`, `sudamerica`, `arabia`, y
  sus versiones femeninas con `_f`.
- **Atajos**: `todo`, `masculino`, `femenino`, `europa`, `america`.
- **Competiciones sueltas**, por su nombre o por un alias: `laliga`, `premier`,
  `champions`, `liga_f`…

```bash
cancha ajustes ligas=grandes,uefa,laliga
cancha ajustes ligas=                      # vacío = las 71 del catálogo
cancha ajustes --ligas                     # ver todo lo que se puede elegir
```

En la interfaz son botones: los grupos arriba y las 71 competiciones dentro de
«O una a una».

**Elegir menos hace las noches mucho más cortas.** El catálogo entero son 71
competiciones; si solo miras las cinco grandes, la guardia acaba en una
fracción del tiempo y la memoria crece con lo que de verdad vas a consultar.

## El token del bot

Se puede escribir desde la interfaz, pero **no se devuelve**: cuando vuelves a
abrir los ajustes ves `••••••••ABCD`. Si lo dejas como está, no se toca; si
escribes uno nuevo, se cambia. Sin esto, abrir los ajustes y darle a guardar te
borraría el bot.

El fichero se escribe con permisos solo para ti donde el sistema lo permite. En
Windows eso no significa gran cosa y no se finge que sí: si compartes el
ordenador, ten en cuenta que el token está ahí.

## En una Surface Laptop (Copilot+, ARM64)

Merece un apartado porque hay tres cosas que se comportan distinto. Antes de
dar nada por hecho, `cancha doctor` te lo dice todo.

**1. `curl_cffi` puede no tener versión para ARM64.** Es el transporte
recomendado porque imita el TLS de Chrome y atraviesa el anti-bot de
Cloudflare. Si al instalar falla, el framework usa `httpx` o `urllib` solo, y
entonces **Sofascore responderá 403 muchas veces**. `cancha doctor` dice cuál
está en uso y avisa. Alternativas si pasa: instalar `httpx`
(`pip install httpx`), o correr el proyecto bajo Python x64 por emulación, que
en un Snapdragon X va bien de sobra para esto.

**2. Ollama.** Comprueba en [ollama.com](https://ollama.com) si hay descarga
para Windows ARM64 antes de suponerlo. Con 16 GB de RAM, `hermes3` (8B, unos
5 GB) cabe cómodo. Lo que **no** va a usar es la NPU: Ollama tira de CPU y GPU,
así que las respuestas del analista tardarán más que en un portátil con GPU
dedicada. Los datos y el pronóstico no dependen de eso — se calculan en Python
y son instantáneos.

Si el analista se te hace lento, baja de modelo antes que de expectativas:

```bash
cancha ajustes modelo=qwen2.5:7b
```

**3. La suspensión.** Es lo de siempre de estos portátiles: con la tapa cerrada
se duermen. La guardia le pide al sistema que no suspenda mientras trabaja
(ver [Dejarlo funcionando](dejarlo-funcionando.md)), pero si cierras la tapa
manda la tapa. Para dejarlo toda la noche: tapa abierta y pantalla apagada, o
el Programador de tareas con «Reactivar el equipo».

Y una cosa que sí juega a tu favor: 16 GB dan de sobra. La memoria son 35 KiB
por partido, así que una temporada entera de las cinco grandes son 131 MiB de
disco y nada de RAM.

---

[← Volver al índice](../README.md)
