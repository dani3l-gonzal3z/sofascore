# Dejarlo funcionando

```bash
cancha arrancar                 # la interfaz, la guardia nocturna y el bot
```

## La primera vez, de principio a fin

En Windows, con el proyecto descargado, abre esa carpeta y:

```powershell
.\cancha.bat doctor                    # ¿con qué pide, y contesta Sofascore?
.\cancha.bat ajustes ligas=grandes     # empieza por poco; luego amplías
.\cancha.bat guardia --una-vez         # la primera carga, mirándola
.\cancha.bat                           # y ya: déjalo con esto abierto
```

El `.bat` se encarga del entorno la primera vez (tarda un minuto) y luego
arranca directo. Sin argumentos hace `arrancar`; con un comando delante, lo
ejecuta —así no tienes que saber dónde vive el entorno—.

### Cómo se escribe cada comando

En esta documentación los comandos se escriben `cancha esto y lo otro`, que es
como se llaman. En tu ordenador hay que decírselo de una de estas tres formas, y
las tres hacen lo mismo:

| Dónde | Cómo |
| --- | --- |
| **Windows, PowerShell** | `.\cancha.bat doctor --tls` |
| **Windows, símbolo del sistema** | `cancha.bat doctor --tls` |
| **Cualquier sitio** | `python -m cancha doctor --tls` |

Ese `.\` de PowerShell no es un adorno: PowerShell **no ejecuta nada de la
carpeta en la que estás** si no se lo pides así, y lo que dice cuando te falta
es «El término 'cancha' no se reconoce como nombre de un cmdlet…», que suena a
que no está instalado cuando lo está.

`cancha` a secas (sin `.bat` y sin `.\`) funciona solo si instalaste el paquete
con `pip install -e .` **y** la carpeta de scripts de tu Python está en el PATH.
En Windows, con una instalación de usuario, normalmente no lo está, y por eso
está el `.bat`.

### Instalar algo dentro del entorno

`cancha.bat` se hace un entorno propio en `.venv`, y esto es importante: un
`pip install algo` escrito en PowerShell va al **Python del sistema**, no a ese
entorno, así que `cancha` no lo verá. Dentro del entorno se instala así:

```powershell
.\.venv\Scripts\python.exe -m pip install algo
```

Casi nunca hace falta: el `.bat` instala lo que el proyecto necesita —y lo
completa solo si en una versión nueva hace falta algo más—. Y si dudas de qué
Python está usando, `.\cancha.bat doctor` lo dice en su primera línea.

**`doctor` primero, siempre.** Si dice `UrllibTransport` en vez de
`CurlTransport`, instala `curl_cffi` antes de nada o Sofascore te va a
responder 403 casi siempre.

**`ligas=grandes` es el consejo que más tiempo ahorra.** El catálogo entero son
71 competiciones y la primera noche sería larguísima. Con las cinco grandes ya
tienes de qué, y ampliar después no cuesta: lo ya guardado no se vuelve a
pedir.

**`guardia --una-vez` la primera vez, mirándola.** Hace una vuelta entera y
sale, así ves qué tarda y si algo falla antes de dejarlo solo toda la noche.

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

Sin token todavía, la última línea es otra y no es un error:

```
  telegram     esperando token · ponlo en Ajustes (o con --token / CANCHA_TELEGRAM_TOKEN)
               y empieza a escuchar solo, sin reiniciar esto
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

Montarlo son dos minutos, y se puede hacer **entero desde el móvil** con
`cancha arrancar` ya funcionando:

1. En Telegram, habla con **@BotFather** y manda `/newbot`. Te pide un nombre y
   te da un token, algo como `123456:AAE...`.
2. Pega el token en **Memoria → Ajustes → token del bot de telegram** y dale a
   guardar. **No hay que reiniciar nada**: el bot mira los ajustes en cada
   vuelta, así que en menos de medio minuto está escuchando. La misma pestaña te
   dice si lo está («el bot está escuchando») o qué le pasa.

   Desde el terminal es lo mismo con otra puerta:

   ```bash
   cancha telegram --token 123456:AAE...
   ```

3. Escríbele desde tu Telegram. Te contestará con **tu identificador de chat** y
   nada más.
4. Ponlo en **chats permitidos**. Ahí no hace falta que lo copies a mano: al
   escribirle, el bot lo apunta y aparece como un botón —con tu nombre al
   lado— para meterlo de un toque. Si todavía no sale, el botón **«¿Me ha
   escrito ya?»** lo vuelve a mirar sin recargar la página. También vale por
   la línea de comandos:

   ```bash
   cancha telegram --token 123456:AAE... --chat 987654321
   ```

### Si le escribes y no contesta

Eso pasaba antes por una razón tonta y ya está arreglada: el bot solo se
arrancaba si había token **al abrir el programa**, así que guardarlo en Ajustes
no servía de nada hasta reiniciar, y nadie te lo decía. Ahora el hilo del bot se
levanta siempre y espera al token. Si aun así no contesta, mira la pestaña
Ajustes —lo que le pase lo dice ahí— y en la consola del ordenador. Los dos
casos que hay:

* **«Hay otro programa escuchando con este mismo token»**. Telegram solo deja un
  oyente por token, y devuelve un 409 al segundo. Casi siempre son dos `cancha`
  abiertos: cierra uno.
* **«Telegram dice que el token no vale»**. El token está mal copiado o
  @BotFather lo ha revocado. Cámbialo en Ajustes; se coge al vuelo.
* **Algo de un certificado** («CERTIFICATE_VERIFY_FAILED», «self-signed
  certificate in certificate chain»). Eso no es del bot: hay un antivirus o un
  proxy abriendo tu HTTPS. `cancha doctor --tls` dice quién, y
  [Certificados](certificados.md) cómo se arregla.

Y si no está en tu lista de permitidos, el bot contesta «No tengo nada para ti»
a propósito: ver el punto siguiente.

Un token que le pases con `--token` o por el entorno **manda sobre los
ajustes**: no lo borra un fichero de ajustes vacío. Para no escribirlo cada vez:

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
| `/hoy` | Qué se juega hoy, por competición y **en tu hora** |
| `/hoy laliga` | Una competición entera |
| `/hoy 2026-09-22` | Otro día |
| `/manana` | Los de mañana |
| `/directo` | Lo que se juega ahora, en tus competiciones (`/directo laliga`) |
| `/seguro` | Los patrones que se cumplen hoy, con su número y si aguantan fuera de muestra |
| `/pronostico Girona vs Osasuna` | Marcador, córners y tarjetas, calculados |
| `/previa Girona vs Osasuna` | La previa entera |
| `/dictamen Girona vs Osasuna` | El expediente entero a un modelo ([Dictamen](dictamen.md)) |
| `/equipo Girona` | Cómo juega, comparado con su liga |
| `/jugador Vinicius` | Forma y rachas |
| `/memoria` | Qué hay guardado y cuándo fue la última guardia |

**Las horas son las de tu reloj.** Antes salían en UTC sin decirlo, así que un
partido a las 14:15 UTC se leía como las dos y cuarto cuando en España empezaba
a las cuatro y cuarto.

**Solo tus competiciones.** El bot pregunta por las ligas que elijas en Ajustes,
y las coge al vuelo. Sin filtrar, «en directo» traía el fútbol entero del
planeta: en una consulta real salieron Perú sub-15 y juveniles gallegos
mezclados con LaLiga.

**Un día largo no se vuelca entero.** Se enseñan las seis competiciones más
importantes con hasta ocho partidos cada una, las demás por nombre y número, y
`/hoy <liga>` abre la que quieras.

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
