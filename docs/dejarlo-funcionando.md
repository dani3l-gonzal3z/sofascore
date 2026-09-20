# Dejarlo funcionando

```bash
cancha arrancar                 # la interfaz, la guardia nocturna y el bot
```

En Windows, doble clic en **`cancha.bat`**. La primera vez se prepara el
entorno solo (un minuto); las siguientes arranca directo. Si algo falla, la
ventana **no se cierra**: el error se queda para poder leerlo.

En macOS o Linux, `./arrancar.sh`.

Eso levanta tres cosas en un solo proceso, y Ctrl+C se las lleva todas:

```
  cancha — arrancando

  memoria      4.218 partidos, 3.940 con estadísticas
  transporte   CurlTransport
  credenciales sin credenciales (solo datos públicos)
  guardia      cada día a las 03:00, prepara el día +1 · registro en datos/guardia.log
               el equipo no se suspenderá mientras trabaje (la pantalla sí se apaga)
  telegram     «cancha» · https://t.me/tubot
```

Todo eso sale de tus **[ajustes](ajustes.md)** —la hora, las ligas, el modelo,
el puerto y el bot— que se cambian desde la pestaña Ajustes de la interfaz,
también desde el móvil, o con `cancha ajustes`. Lo que escribas en la línea de
comandos gana a lo guardado.

## La guardia nocturna

Cada noche a su hora hace cuatro cosas, en este orden:

1. **Barrido** del día que viene: la agenda y el historial de quien juega.
2. **Abastecimiento** de sus partidos: los últimos diez de cada equipo, lo que
   han jugado entre ellos y lo del árbitro. Es lo caro y lo que llena la
   memoria de verdad.
3. **Briefing** del día, escrito en disco.
4. **Casi seguro**, calibrado, para que abrir la pestaña por la mañana sea
   instantáneo en vez de contar miles de partidos en ese momento.

```bash
cancha guardia                        # a la hora de tus ajustes (de fábrica, 03:00)
cancha guardia --ahora                # y hace una vuelta ya, para verlo funcionar
cancha guardia --una-vez              # una vuelta y sale
cancha guardia --a-las 02:30 --partidos 20 --max 4000   # solo esta vez
cancha ajustes guardia.hora=02:30                      # a partir de ahora
```

La hora **se coge al vuelo**: la guardia mira los ajustes mientras espera, así
que cambiarla desde el móvil a las once de la noche vale para esa misma noche.

Todo lo que hace queda en `datos/guardia.log`, con los errores marcados para
que se vean de un vistazo entre cien líneas:

```
03:00:07 · ── Preparando el 2026-09-21 ──────────────────────
03:00:41 · Barrido: 38 partidos nuevos, 240 peticiones.
03:04:12 · Girona - Osasuna: 26 traídos, 12 ya estaban.
03:11:55 ✗ ERROR Sevilla - Betis: HTTP 403 en /event/1234/shotmap
03:14:02 · Calibrado con 4.218 partidos: 5 patrones útiles, 4 aguantan fuera de muestra.
03:14:02 · ── Resumen ───────────────────────────────────────
03:14:02 · 1.847 peticiones · 1 errores
```

Cortarla no rompe nada: lo guardado queda guardado y la noche siguiente sigue
por donde falte.

### Lo de la suspensión, que es lo importante

**Si el ordenador se duerme de verdad, Python deja de ejecutarse.** No hay
demonio que lo impida: el proceso se congela con la máquina y por la mañana no
ha hecho nada. Esto hay que resolverlo, no ignorarlo.

En **Windows** la guardia le pide al sistema que no se suspenda mientras
trabaja (`SetThreadExecutionState`, sin instalar nada). Pide que la **máquina**
siga despierta pero **no** la pantalla, así que el monitor se apaga y el
ordenador sigue. Es lo que uno quiere de noche, y te lo dice al arrancar.

Fuera de Windows no se toca nada y se avisa, porque fingir que se ha hecho algo
es peor que no hacerlo: desactiva la suspensión en los ajustes de energía.

Si prefieres que el equipo **sí** se duerma y despierte solo, eso es el
Programador de tareas de Windows, no este programa:

1. Programador de tareas → Crear tarea.
2. Desencadenador: diario a las 03:00.
3. Acción: `C:\ruta\.venv\Scripts\python.exe` con argumentos
   `-m cancha guardia --una-vez`, y «Iniciar en» la carpeta del proyecto.
4. Condiciones → **«Reactivar el equipo para ejecutar esta tarea»**.

Esa casilla es la diferencia. Con ella, el equipo duerme y se despierta él
solo; con `cancha arrancar`, el equipo no duerme.

## El bot de Telegram

Para preguntarle desde la calle. El ordenador se queda en casa haciendo el
trabajo y tú escribes desde donde estés. **No hace falta abrir ningún puerto ni
tener IP fija**: es tu ordenador quien llama a Telegram, no al revés.

Montarlo son dos minutos:

1. En Telegram, habla con **@BotFather** y manda `/newbot`. Te pide un nombre y
   te da un token, algo como `123456:AAE...`.
2. Arranca el bot con ese token, sin más:

   ```bash
   cancha telegram --token 123456:AAE...
   ```

3. Escríbele desde tu Telegram. Te contestará con **tu identificador de chat** y
   nada más.
4. Arráncalo otra vez con ese número:

   ```bash
   cancha telegram --token 123456:AAE... --chat 987654321
   ```

Para no escribirlo cada vez, guárdalo en el entorno y `cancha arrancar` lo coge
solo:

```bash
setx CANCHA_TELEGRAM_TOKEN "123456:AAE..."      &:: Windows
setx CANCHA_TELEGRAM_CHAT  "987654321"
```

### Por qué no contesta sin `--chat`

Un bot de Telegram es **público**: cualquiera que dé con su nombre puede
escribirle. Sin lista de permitidos, contestar sería enseñarle tu memoria
entera al primero que pase, así que no contesta a nadie —solo te dice tu id
para que lo pongas en la lista—. A un desconocido que escriba estando la lista
puesta no se le cuenta ni qué es esto.

Con todo, el token es una llave: si se filtra, quien lo tenga puede hacerse
pasar por tu bot. No lo subas a ningún sitio.

### Qué sabe hacer

| Orden | Qué |
| --- | --- |
| `/hoy` | Los partidos de hoy |
| `/manana` | Los de mañana |
| `/directo` | Lo que se está jugando ahora |
| `/seguro` | Lo que casi siempre pasa, con su número y si aguanta fuera de muestra |
| `/previa Girona vs Osasuna` | La previa entera |
| `/equipo Girona` | Cómo juega, comparado con su liga |
| `/jugador Vinicius` | Forma y rachas |
| `/memoria` | Qué hay guardado y cuándo fue la última guardia |

Y cualquier otra cosa se la pasa al **analista local**, si tienes Ollama
arrancado. Si no lo tienes, lo dice en vez de quedarse mudo.

## Verlo desde fuera por una URL

No lo hace este programa, y es a propósito. Abrir tu ordenador a internet es
una decisión con consecuencias, y hacerlo bien es un túnel —**Tailscale** o
**Cloudflare Tunnel**—, no un puerto abierto en el router. El bot de Telegram
resuelve el mismo problema sin exponer nada: si lo que quieres es preguntar
desde fuera, esa es la puerta.

Dentro de casa, el QR de `cancha arrancar` te lleva a la interfaz entera desde
el móvil.

---

[← Volver al índice](../README.md)
