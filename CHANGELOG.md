# Cambios

Lo que ha ido pasando, de lo nuevo a lo viejo. Las versiones siguen
[versionado semántico](https://semver.org/lang/es/), con la salvedad de que
hasta el 1.0 la API puede moverse.

## 0.12.1

Un error que no se entendía leyéndolo, y que no era de este programa.

### Arreglos

- **«No llego a Telegram: [SSL: CERTIFICATE_VERIFY_FAILED] self-signed
  certificate in certificate chain».** No era el bot, ni Telegram: era algo en el
  ordenador poniéndose en medio de las conexiones seguras —un antivirus con la
  revisión de webs encendida, el proxy de una empresa, una VPN— presentando su
  propio certificado. Python no conoce a quien lo firma y corta, que es lo que
  tiene que hacer. Pero el mensaje hablaba de certificados y parecía que lo roto
  fuera Telegram.

  Ahora hay tres cosas donde antes no había ninguna:

  1. **Se dice quién es.** `cancha doctor --tls` se asoma al certificado que te
     presentan y saca el nombre de quien lo firma, que casi siempre es el nombre
     del antivirus o del proxy, tal cual. Desde el móvil, el botón «¿Alguien abre
     mi HTTPS?» en Memoria → Diagnóstico.
  2. **Se puede arreglar.** Con `truststore` instalado se usa el almacén de
     certificados del sistema —donde esos programas dejan el suyo—, que es el
     arreglo bueno y no baja ninguna guardia. Y si no se puede instalar nada,
     `red.ca_bundle` acepta un `.pem`, igual que `--ca-bundle`, `CANCHA_CA_BUNDLE`
     y las variables de siempre (`SSL_CERT_FILE` y compañía) que quien tiene un
     proxy de empresa ya suele llevar puestas.
  3. **Se explica donde se lee.** El fallo de certificado ya no sale como un
     volcado de OpenSSL: sale diciendo qué pasa y los cuatro arreglos por orden,
     en el terminal, en la página y en el mensaje del bot.

  Los certificados se ponen **una vez** y valen para todo lo que sale a internet:
  Sofascore y las demás fuentes, el bot, las cuotas y la nube de Ollama. Con una
  salvedad que está dicha: `curl_cffi` lleva sus propios certificados y no entiende
  el almacén del sistema, así que con él `truststore` no sirve y hay que darle la
  ruta del `.pem` —que se le pasa sola en cuanto la pongas—.

  Hay un `red.sin_verificar` para cuando no hay otra. Deja de comprobar con quién
  se habla, así que va con su aviso al arrancar y en los ajustes, cada vez.
  Está porque a veces hace falta, no porque sea una alternativa.

  Todo en **[Certificados](docs/certificados.md)**.

  Probado contra un TLS de verdad: las pruebas fabrican un certificado
  autofirmado y levantan un servidor en `localhost` que lo presenta, que es
  exactamente lo que hace un antivirus que abre el HTTPS. 1.000 pruebas, sin red.

## 0.12.0

Un modelo grande mirando el partido entero, y el arreglo del bot que no
contestaba.

### Novedades

- **`cancha dictamen`: todo el expediente a un modelo, de una vez.** El analista
  de casa trabaja a cachitos —pide una herramienta, lee, pide otra— y con 8B en
  tu ordenador es lo correcto. Con un modelo grande es desperdiciarlo: lo que se
  quiere de él no es que sepa qué pedir, sino que **vea todo a la vez y ate
  cabos**. Que se dé cuenta de que el equipo que mejor llega es el que peor
  defiende los córners y enfrente hay alguien que vive de eso.

  Así que `cancha/expediente.py` monta el expediente completo de un partido
  —pronóstico calculado, cómo juega cada uno comparado con su liga, los cruces,
  los últimos seis de cada equipo y los seis entre ellos, jugadores, árbitro,
  mercado y los patrones medidos— y lo manda en **una** llamada, sin
  herramientas. Está en la línea de comandos, en la interfaz (tarjeta Dictamen)
  y en el bot (`/dictamen`).

  Los números van **ya calculados**: el expediente no trae datos en bruto para
  que el modelo los promedie. El modelo pone el razonamiento y la aritmética la
  pone Python, que es la línea de siempre y con un modelo grande importa más, no
  menos: se equivoca con más aplomo. Y el documento cierra con un apartado que
  importa tanto como los otros, **«Lo que este expediente NO sabe»**
  —alineaciones, lesiones, si el partido vale algo—, para que no rellene esos
  huecos por su cuenta.

  Medido: 2.263 caracteres en un partido sin historia detrás, unos 1.100 más
  cuando la memoria ya tiene los doce partidos anteriores. Del orden de 900
  tokens por partido. `--solo-expediente` lo enseña sin gastar nada.

- **La nube de Ollama, con clave.** `ollama_api_key` en los ajustes y ya: el
  protocolo es el mismo que en casa, así que solo cambia la URL a
  `https://ollama.com` y la clave va en la cabecera `Authorization`. Con eso
  contesta un modelo de los que en 16 GB no entran.

  **Y hay que decirlo claro: con clave, el expediente de cada partido SALE de tu
  ordenador.** Es la única parte de todo esto que no es local. La clave se tapa
  igual que el token del bot —`••••••••` y no se devuelve por la API—, el aviso
  sale en la interfaz cada vez, y en la respuesta vienen los tokens que Ollama
  dice haber cobrado. Una clave que no vale o un saldo agotado se explican por
  su nombre en vez de dejar un 401 pelado. Todo en
  **[Dictamen](docs/dictamen.md)**.

### Arreglos

- **El bot de Telegram no contestaba, y lo peor: en silencio.** Guardabas el
  token en la pestaña Ajustes, le escribías al bot y no pasaba nada. El hilo del
  bot solo se creaba **si había token al arrancar el programa**, así que guardarlo
  después no servía de nada hasta reiniciar, y nadie lo decía en ninguna parte.

  Ahora el bot mira los ajustes **en cada vuelta**: el hilo se levanta siempre,
  espera a que aparezca el token y empieza a escuchar él solo en menos de medio
  minuto. Cuando lo coge, dice quién es y dónde escribirle. Y lo mismo con los
  chats permitidos y con el modelo: se cambian con el programa funcionando. Un
  `--token` de la línea de comandos sigue mandando sobre los ajustes, que si no
  lo borraría el primer fichero de ajustes vacío.

  Lo que la interfaz decía —«guarda el token y reinicia cancha»— era además
  mentira a medias: ahora dice si el bot **está escuchando**, y si no, qué le
  pasa. Que es lo que hacía falta para no tener que ir al ordenador a mirarlo.

- **Los fallos del bot iban a ninguna parte.** El hilo se arrancaba sin a quién
  avisar, así que un token caducado o un problema de red se los tragaba el
  silencio. Ahora se cuentan en la consola y el último se guarda para verlo desde
  el móvil. El mismo fallo se dice **una** vez: un token malo daba seis líneas por
  minuto y tapaba todo lo demás.

- **Dos `cancha` abiertos con el mismo token dejaban el bot mudo.** Telegram solo
  permite un oyente por token y devuelve un 409 al segundo, sin más explicación.
  Ahora se dice con palabras: «hay otro programa escuchando con este mismo token,
  cierra el otro».

- **Y nada tumba el hilo del bot.** Cualquier excepción inesperada lo mataba, y
  morirse en segundo plano es quedarse mudo sin que nadie se entere: exactamente
  el fallo de arriba por otro camino. Ahora la vuelta se cuenta, se dice y se
  sigue.

- **El token y los chats ya no salen en «hace falta reiniciar».** Se cogen al
  vuelo; lo único que de verdad se lee al arrancar es lo que decide cómo se abre
  el puerto: `web.puerto`, `web.lan` y `web.clave`.

## 0.11.3

Más cosas que salieron usándolo.

### Arreglos

- **«Buscar los ids que faltan» reventaba** con `AttributeError: 'Almacen'
  object has no attribute 'search'`. Los dos primeros argumentos de `asegurar`
  son el cliente y la memoria, y se pasaban al revés. Ahora van por nombre,
  que es lo que impide que vuelva a pasar, y hay una prueba que recorre el
  camino entero —con un grupo que de verdad tenga ids sin identificar, porque
  con las cinco grandes no se llega ni a buscar—.

- **El bot compartía la conexión de SQLite con el servidor web**, desde otro
  hilo y sin el cerrojo que protege a la web. Ahora tiene su propia sesión,
  igual que la guardia. Y la memoria se abre en **modo WAL** con un tiempo de
  espera: es justo la forma que tiene esto —la guardia escribiendo de noche
  mientras alguien abre la página— y sin él coincidir daba un «database is
  locked» en la cara.

### Novedades

- **El identificador de chat de Telegram, de un botón.** Es un número que
  nadie se sabe, y pedirlo a secas no ayudaba. Ahora el bot apunta a quien le
  escriba sin estar en la lista, y la pestaña Ajustes lo ofrece con su nombre
  al lado para meterlo de un toque. Si todavía no te ha escrito nadie, explica
  los tres pasos en vez de dejarte con un campo vacío.

## 0.11.2

Dos fallos que salieron al usarlo en Windows.

### Arreglos

- **Abrir el historial de un clásico tumbaba la petición en Windows.**
  `Event.kickoff` usaba `datetime.fromtimestamp`, que le pregunta al sistema
  operativo, y en Windows esa llamada revienta con `OSError` para cualquier
  fecha anterior a 1970. En Linux funciona, por eso no se vio aquí. Y no es un
  caso raro: `historial_entre_equipos` trae los partidos de los años veinte.

  Ahora la hora se suma desde la época con `timedelta`: aritmética pura, igual
  en todas partes. Un valor absurdo —o en milisegundos, que alguna fuente los
  manda así— devuelve `None` en vez de reventar, porque un partido sin fecha
  legible es eso y no una excepción a media página. Hay una prueba que impide
  que la llamada vuelva a colarse en ningún sitio.

- **Una herramienta que falla ya no se lleva por delante la petición.** El
  servidor dejaba subir la excepción: veinte líneas de traza en la consola y,
  en el navegador, una conexión muerta sin mensaje. Ahora cualquier fallo se
  convierte en un JSON con el tipo, el mensaje y dónde pasó, y la página lo
  enseña. La traza se sigue imprimiendo en la consola —es local y sirve para
  arreglarlo—, pero el servidor sigue atendiendo lo siguiente.

  Con cuidado de no escribir un error encima de una respuesta a medio enviar:
  el analista contesta en NDJSON sin longitud, y hacer eso dejaría al
  navegador leyendo basura.

## 0.11.1

Un arreglo, y la prueba que faltaba.

### Arreglos

- **`cancha arrancar` no arrancaba.** Al conectar los ajustes cambié los
  valores por defecto del parser a `None` —para que los ajustes guardados
  pudieran ganar— pero `cmd_arrancar` seguía leyendo `args.port`, `args.a_las`
  y compañía sin resolverlos. Resultado: «cada día a las None» y un
  `TypeError` al abrir el puerto. `cancha guardia` y `cancha telegram` sí
  estaban bien; era justo el comando que se usa todos los días el que no.

  Lo peor no es el fallo: es que había 889 pruebas y **ninguna ejecutaba
  `cancha arrancar`**. Ahora hay dieciocho que sí, y una de ellas comprueba
  que ninguna opción le llegue al servidor en `None`, sea cual sea. Se ha
  verificado que fallan con el código roto antes de darlas por buenas.

- La prueba de que la guardia no comparte cliente con la web leía el código
  fuente en vez de ejecutarlo, así que se rompió sola al cambiar una línea.
  Ahora arranca el comando de verdad y compara los dos clientes.

## 0.11.0

Decidirlo una vez: la hora de la guardia, las ligas y el modelo, desde donde
tengas la mano.

### Novedades

- **Ajustes de verdad, en `datos/ajustes.json`.** La hora y los días de la
  guardia, cuántos partidos abastece, el tope de peticiones, las ligas que
  sigues, el modelo de Ollama, el puerto, la clave y el bot. Tres sitios para
  tocarlo y es el mismo fichero: la **pestaña Ajustes de la interfaz —también
  desde el móvil—**, `cancha ajustes clave=valor`, o el fichero a mano.

  El orden manda: **línea de comandos > fichero > fábrica**. Así
  `cancha guardia --a-las 02:00` es «solo esta vez» y
  `cancha ajustes guardia.hora=02:00` es «a partir de ahora».

- **La hora se coge al vuelo.** La guardia mira los ajustes mientras espera, en
  trozos de cinco segundos, así que cambiarla desde el móvil a las once de la
  noche vale para esa misma noche. Un ajuste que no surte efecto hasta mañana
  es papel mojado. Lo que no se puede cambiar en caliente —el puerto, la clave,
  el bot— la interfaz te lo dice por su nombre al guardar, en vez de dejarte
  con el «no me funciona» de dentro de un rato.

- **Elegir ligas, de verdad.** Grupos (`grandes`, `uefa`, `femenino`…), atajos
  (`todo`, `europa`, `america`) o las **71 competiciones una a una**, por
  nombre o alias. En la interfaz son botones; en el terminal,
  `cancha ajustes --ligas` las lista todas. Elegir menos hace las noches mucho
  más cortas.

- **El modelo, de una lista.** La pestaña Ajustes pregunta a Ollama qué tienes
  instalado y te lo ofrece en un desplegable; si Ollama no está, deja escribir
  el nombre igualmente para cuando lo arranques.

- **Documentación para portátiles ARM64** (Surface Laptop y demás Copilot+), que
  se comportan distinto en tres cosas: `curl_cffi` puede no tener versión y sin
  él llueven los 403, Ollama no usa la NPU, y la tapa cerrada manda sobre
  cualquier cosa que haga el programa.

### Detalles que importan

- **El token del bot no se devuelve nunca.** Se escribe desde la interfaz pero
  vuelve tapado, y si lo dejas como está no se toca. Sin eso, abrir los ajustes
  y darle a guardar te habría borrado el bot.
- **Un fichero de ajustes roto no te deja sin programa**: se avisa y se sigue
  con lo de fábrica, que es lo que hace falta para poder entrar a arreglarlo.
- **Las claves inventadas no se guardan.** Un ajuste que nadie lee es peor que
  no tenerlo, porque parece que hace algo.

## 0.10.0

El pronóstico completo de un partido —marcador exacto, córners, tarjetas— y un
agente que lo cuenta sin inventárselo.

### Novedades

- **`cancha pronostico`, `/pronostico` en Telegram y en la interfaz.** Marcador
  exacto con su probabilidad, 1X2, más/menos goles, marcan los dos, córners y
  tarjetas.

  Los números **los calcula la aritmética, no el modelo**. Si le das treinta y
  ocho partidos a un 8B y le pides el marcador, te lo da: con seguridad, con
  detalle y sin ninguna base. Así que se calcula en Python y el modelo solo lo
  lee en voz alta; sus instrucciones le prohíben dar una cifra que no le hayan
  dado.

  Goles por fuerzas multiplicativas medidas en **xG** cuando hay muestra —marcar
  dos con 0,4 de xG es suerte, y la suerte no se repite—, con la ventaja de
  jugar en casa sacada de esa misma liga. La matriz de marcadores es el producto
  de dos Poisson. Córners y tarjetas, por la media entre lo que hace uno y lo
  que concede el otro, y las tarjetas además por el árbitro si tiene ocho
  partidos o más.

- **Las fuerzas van encogidas hacia la media de la liga.** Sin esto el modelo
  multiplicativo se dispara: un equipo que en diez partidos ha marcado el doble,
  contra otro que ha encajado el doble, daba **lambdas de cinco goles**. No es
  un fallo de la fórmula: con diez partidos no se sabe que alguien sea el doble
  de bueno, lo parece. La respuesta trae `ataque` y `ataque_sin_encoger` para
  que se vea lo que se ha movido.

- **Todo pronóstico se compara con la cuota.** El mercado es un modelo y es
  bueno: sabe de alineaciones, bajas y dinero. Donde coincide no hay nada que
  ganar, y eso sale escrito en la respuesta, no en una nota al pie.

- **Y lo que no dice, dicho:** no sabe de lesiones ni rotaciones, no corrige la
  correlación entre marcadores (Dixon-Coles), y el marcador más probable de un
  partido de fútbol ronda el 10-12 %. Que uno encabece la lista no es que vaya a
  pasar; es que es el menos raro de muchos.

### Arreglos

- **Las tarjetas salían a la mitad.** `perfil_de_arbitro` da amarillas **por
  equipo** y se estaban dividiendo entre el total **por partido**: un factor de
  0,5 clavado en cada pronóstico. Lo encontró el test que esperaba un factor de
  1 para un árbitro que pita como la media de su liga.

## 0.9.0

Que se pueda dejar encendido y trabaje solo, y que se le pueda preguntar
desde la calle.

### Novedades

- **`cancha arrancar`: un solo comando.** Comprueba que esté todo en su sitio,
  levanta la interfaz en la wifi con su QR, pone la guardia nocturna y, si le
  das token, el bot de Telegram. Un proceso, y Ctrl+C se lo lleva todo. En
  Windows hay **`cancha.bat`**: doble clic, y la primera vez se prepara el
  entorno solo. Si algo falla, la ventana no se cierra y el error se queda
  ahí para poder leerlo.

- **La guardia nocturna.** Cada noche a su hora: barre el día que viene,
  abastece sus partidos, escribe el briefing y calibra «casi seguro». Por la
  mañana está hecho. Todo queda en `datos/guardia.log` con los errores
  marcados, y cortarla no rompe nada.

  **Y lo de la suspensión, que era el nudo.** Si el equipo se duerme de
  verdad, Python deja de ejecutarse: no hay demonio que lo impida. En Windows
  la guardia le pide al sistema que no se suspenda mientras trabaja —la
  máquina sigue, la pantalla se apaga—, y te lo dice al arrancar. Fuera de
  Windows se avisa en vez de fingirlo. Para quien prefiera que el equipo sí
  duerma y despierte solo, `--una-vez` encaja en el Programador de tareas con
  la casilla «Reactivar el equipo»; está explicado en
  `docs/dejarlo-funcionando.md`.

- **Bot de Telegram.** Para preguntar desde fuera de casa con solo el
  ordenador encendido: no hace falta abrir puertos ni tener IP fija, porque es
  tu ordenador quien llama a Telegram. Sin dependencias, por *long polling*.
  Entiende `/hoy`, `/manana`, `/directo`, `/seguro`, `/previa`, `/equipo`,
  `/jugador` y `/memoria`, y lo demás se lo pasa al analista local.

  **Sin `--chat` no contesta a nadie**, y con razón: un bot es público y
  cualquiera que dé con su nombre puede escribirle. Sin lista de permitidos
  solo responde diciéndote tu identificador de chat para que lo pongas; a un
  desconocido, con la lista puesta, no se le cuenta ni qué es esto.

### Arreglos

- **La guardia compartía cliente con el servidor web**, y el problema sutil era
  el peor: el tope de la guardia se mide con el contador de peticiones del
  cliente, así que cada previa que abrieras desde el móvil le descontaba
  presupuesto y se cortaba sola sin motivo. Ahora tiene el suyo.
- **Un `modelo` vacío dejaba al analista sin modelo.** Pasar `None` machacaba
  el de por defecto del dataclass; había un `except TypeError` tapándolo en vez
  de arreglarlo.

## 0.8.0

Buscar un partido ya no exige haber barrido antes: lo trae.

### Novedades

- **Abastecer un partido.** `cancha previa <partido> --abastecer`, o el botón
  «Memoria de este partido» en la interfaz, trae y guarda todo lo que cuesta
  entenderlo: los **últimos diez de cada equipo por separado**, los que han
  **jugado entre ellos** y los del **árbitro**, con estadísticas,
  alineaciones, tiros y cuotas. Unos cuarenta partidos, minuto y medio la
  primera vez.

  Con `--plan` dice antes lo que va a costar —cuántos partidos hacen falta,
  cuántos ya están y cuántas peticiones son— porque decidir a ciegas cuánto le
  pides a un servidor ajeno no es decidir. Y se puede cortar con `--max`: lo
  guardado queda guardado y al repetirlo sigue por donde falte.

  **No crece exponencialmente: se satura.** Los últimos diez de un equipo son
  también los últimos diez de media liga, así que el cuarto análisis de una
  competición cuesta la mitad y el cuadragésimo, una sexta parte. Está medido
  y la tabla está en `docs/memoria.md`.

- **Nada de mirar el futuro.** Los partidos que se traen se cortan por la fecha
  del que se analiza, en el origen. Promediar «sus últimos diez» con uno que
  todavía no se había jugado es la manera más silenciosa de construir un
  análisis que acierta en el pasado y falla mañana. Hay un test que lo vigila.

- **Las cuotas llevan fecha** (esquema 5). Antes se sobrescribían sin dejar
  rastro: una de apertura y una de cierre eran la misma fila. Ahora guardan
  `visto_en` y `horas_antes` del saque. No cambia nada hoy; es lo que hará
  posible entrenar algo con esto algún día, porque para eso la de cierre es la
  única que vale. Las bases antiguas ganan las columnas sin perder una fila.

### Arreglos

- **`abastecer` devolvía cero partidos «ya guardados»** cuando los había: dos
  diccionarios fusionados compartían la clave `ya_estaban` con significados
  distintos y ganaba el que siempre valía cero. Lo encontró su propio test.

## 0.7.0

Una pasada mirando el proyecto de lejos. Sale de una pregunta incómoda: la
interfaz enseñaba diecinueve de las cuarenta y una herramientas, así que
«úsalo desde el móvil» era verdad a medias. Ahora es verdad entera, y por el
camino aparecieron dos cosas que estaban mal y una que no se podía reutilizar.

### Novedades

- **La comprobación fuera de muestra.** Un patrón de «casi seguro» se medía
  sobre los mismos partidos que lo hicieron parecer bueno. Ahora el historial
  se parte **por fecha** —el 70 % más viejo y el 30 % más nuevo— y la cuenta
  se hace dos veces: si el número se mantiene en la parte nueva, que no
  participó en medirlo, el patrón dice **aguanta**; si cae más de lo que esa
  muestra puede explicar, dice **se cae** y se ve al lado del número, no en
  una nota al pie. Aparece en la página, en `cancha seguro`, en cada aviso
  del día y en las instrucciones del analista, que tiene prohibido presentar
  como hallazgo un patrón que se cae.

  Para llamarlo caída hacen falta dos cosas: que no quepa en la muestra y que
  sea de al menos cinco puntos. Con 66 casos, pasar del 100 % al 98 % se sale
  del intervalo por los pelos, y dar la alarma ahí es ruido.
- **Todo se puede hacer desde el móvil.** Veintidós herramientas no tenían
  manera de usarse desde la página. Ahora la tienen: **Directo** (lo que se
  juega ahora, refrescándose solo), **Liga** (clasificación, histórico desde
  1993, ranking Elo, agenda y noticias de ESPN, tablas de FBref), la **ficha
  completa** de equipo y de jugador, el **Elo** del club, y en el partido las
  alineaciones, la cronología, quién mandaba tramo a tramo, el historial entre
  los dos, quién generó el peligro, los tiros de Understat y los datos en
  crudo de cualquier sección.
- **Una consola de herramientas.** Las pantallas cubren lo de cada día; la
  consola cubre el resto. Pide la lista al servidor y monta los campos desde
  el esquema de cada herramienta, así que **una herramienta nueva aparece sola**
  y «todo desde el móvil» sigue siendo verdad mañana. Hay un test que lo
  vigila: cada herramienta tiene su sitio en una vista o está en una lista
  corta de excepciones con el camino escrito al lado.
- **Diagnóstico y mantenimiento desde la página.** Lo que decía `cancha
  doctor`, más el estado de la caché y de las grabaciones, más vaciar la caché
  y buscar los ids de competición que falten. Estaba todo dentro del impresor
  del comando, así que solo existía en un terminal; ahora vive en
  `cancha.diagnostico` y devuelve datos, y quien quiera los pinta.
- **Un QR para entrar en el móvil.** `cancha web --lan` dibuja un código en el
  terminal: apuntas la cámara y entras. **Si hay clave, va dentro**; la página
  la coge de la dirección, la guarda y la borra de la barra para que no quede
  en el historial. Y en Memoria → Abrirlo en el móvil se pinta el mismo QR en
  pantalla, para cuando ya estás en el ordenador.

  El codificador es nuestro (`cancha/web/qr.py`): Reed-Solomon sobre GF(256),
  versiones 1 a 10, elección de máscara por penalización. Este proyecto no
  tiene dependencias y no iba a empezar por un QR. Está comprobado por los dos
  lados: las tablas de la norma cuadran versión por versión, y lo dibujado se
  vuelve a leer decodificándolo. Fuera de los tests se contrastó además contra
  tres codificadores y un lector reales, y el símbolo que pinta la página se
  decodifica desde sus propios píxeles.
- **Todas las IP, no una.** Con VPN, Docker o WSL hay varias y solo una sirve.
  Se enseñan todas, la de la ruta por defecto primero.

### Arreglos

- **Un cruce afirmaba del rival algo que nadie había medido.** «Ataca por
  fuera y enfrente les entran los centros» se decía habiendo mirado solo la
  primera mitad de la frase: lo que concede el rival no se calculaba. Media
  frase medida y media inventada suena igual de convincente que una entera, y
  ahí está el peligro. Ahora `estilo_de_equipo` mide también la mitad
  defensiva contra la media de su liga, y un cruce necesita los dos lados.
- **Un mensaje de error con una URL dentro ensanchaba la página** en el móvil.
- **`replaceChildren` pintaba la palabra «null»** donde no tocaba nada.
- **El tope de peticiones del barrido contaba menos de la cuarta parte.** Solo
  sumaba las del detalle de partido, no las de descubrir competiciones ni las
  de la agenda liga por liga, que son las caras. Pedir un tope de 50 podía
  gastar doscientas antes de mirarlo. Ahora se cuenta lo que cuenta el propio
  cliente, y el tope se comprueba **antes de cada partido** y no una vez por
  equipo: un equipo son seis partidos.

## 0.6.0

Cuatro cosas: todo el fútbol que importa, lo que casi siempre pasa contado en
vez de supuesto, un analista que vive en tu máquina y una interfaz rehecha.

### Novedades

- **71 competiciones, masculinas y femeninas.** Las cinco grandes europeas en
  los dos géneros, la Champions femenina, las segundas y las nórdicas, MLS,
  USL, NWSL, Liga MX y Liga MX Femenil, CONCACAF, y Sudamérica entera desde
  Brasil hasta Venezuela. Los ids de Sofascore no se adivinan y no me los he
  inventado: los que no estaban contrastados **se descubren solos** la primera
  vez que hay red, comprobando país, deporte y género antes de guardar
  ninguno. Lo que no convence no se guarda, porque un id equivocado no falla:
  barre otra competición en silencio. `cancha ligas`, `--descubrir`,
  `--faltan`. La memoria sube a esquema v4 con la tabla de ligas.
- **Casi seguro** (`cancha seguro`): la corazonada de «si el Madrid perdió, el
  siguiente lo gana», contada. Doce patrones medidos sobre el historial con su
  frecuencia, su suelo de Wilson y —la cifra que decide— su **elevación sobre
  el patrón de referencia**. Si los favoritos ganan el 84 % y los favoritos que
  pincharon ganan el 61 %, no hay reacción: hay tasa base, y se dice con esas
  palabras. Ver [docs/seguro.md](docs/seguro.md).
- **El analista local** (`cancha analista "…"`): habla con Ollama —Hermes 3 por
  defecto, afinado para llamar funciones— y le da las 41 herramientas. Cada
  paso se ve: qué preguntó, cuánto le contestaron y qué concluye. Las
  instrucciones le prohíben estimar cifras y le obligan a respetar los
  veredictos de «sin muestra» y «es la tasa base». Con `pip install
  "cancha[langchain]"` hay además un adaptador a `create_agent` de LangChain
  1.x en `cancha.agentes.langchain`.
- **La interfaz, rehecha.** Identidad propia —papel de periódico en claro,
  césped de noche en oscuro, Archivo para los marcadores— y cinco pestañas:
  Hoy, Casi seguro, Analista, Buscar y Memoria. Los partidos del día vienen
  **plegados en una línea** con lo que decide si te interesan (mercado, forma,
  insignias) y se abren **donde están**, sin cambiar de página; la previa se
  pide al abrirlos, no antes. El analista responde en streaming con sus pasos a
  la vista. Tema claro, oscuro o automático.

### Arreglos

- Una tabla ancha estiraba la rejilla entera y la página se desplazaba a lo
  ancho en el móvil. Las rejillas pasan a `minmax(0, 1fr)` y la tabla se
  desliza dentro de su caja.
- `/api/analista` ya no se cae si Ollama no está: cualquier fallo se convierte
  en una respuesta que la página puede explicar.

### Lo que no se ha podido comprobar

Desde donde se escribió esto no hay red hacia Sofascore, así que **el
descubridor de competiciones no se ha ejercitado contra la API real**: su
lógica está probada con respuestas de mentira, incluidas las trampas (Liga F
frente a LaLiga, Bundesliga alemana frente a austriaca). La primera ejecución
con red es la prueba: `cancha ligas --descubrir` y luego `cancha ligas`.
Tampoco había un Ollama al que preguntar: el bucle del analista está probado
con un Ollama de mentira que devuelve respuestas guionizadas.

## 0.5.0

El framework se pidió por consola y por una IA. Ahora también se mira: hay una
interfaz, y lo que enseña sale de más sitios.

### Novedades

- **Interfaz** (`cancha web`): un servidor de la biblioteca estándar sirviendo
  una página y una API JSON encima de las mismas herramientas que ve la IA. Se
  instala como app en Windows (Edge o Chrome → Instalar) y en iOS (Safari →
  Añadir a pantalla de inicio) con `--lan`. Seis pestañas: Hoy, Partido,
  Equipo, Jugador, Duelo y Memoria, con el barrido corriendo en segundo plano.
- **Briefing** (`cancha briefing`): el documento de la mañana. Todos los
  partidos del día con cómo llegan los dos, si han cambiado, quién lleva racha,
  qué le pasa a sus jugadores contra el sistema del rival, el mercado y el
  árbitro. En Markdown y JSON, uno por día; `--barrer` barre antes.
- **Quién era favorito** (`cancha/cuotas.py`): las cuotas se guardan en la
  memoria (esquema v3, migración automática) y se convierten a probabilidades
  sin el margen de la casa. Con eso, `cancha contra X --desglose` y la
  herramienta `sistema_o_contexto` hacen el análisis dos veces —siendo
  favorito y sin serlo— y dicen, hallazgo por hallazgo, si es el sistema o el
  contexto. Es la comprobación que la versión anterior solo podía prometer.
- **Si un equipo ha cambiado** (`cancha estilo X --evolucion`): sus últimos
  partidos frente a los de antes, dimensión a dimensión, más el dibujo.
- **Tres fuentes más.** football-data.co.uk (resultados y cuotas de cierre
  desde 1993; `cancha cuotas` rellena la memoria con ellas), ESPN (agenda
  independiente, clasificación, resumen y **noticias**: `cancha noticias
  laliga`) y, si están instaladas, **ScraperFC** y **soccerdata** para FBref,
  Transfermarkt, Capology y SoFIFA a través de sus lectores, con nuestra
  interfaz. Extras `cancha[scraperfc]` y `cancha[soccerdata]`.
- **Nueve herramientas más para la IA** (41 en total): `briefing_del_dia`,
  `sistema_o_contexto`, `evolucion_de_equipo`, `noticias`, `agenda_espn`,
  `historial_de_liga`, `rellenar_cuotas`, `datos_externos` y el parámetro
  `solo` en `jugador_contra_sistema`.

### Arreglos

- `_numero(3.5)` devolvía 3: `int()` trunca sin avisar. Una línea de 3,5 goles
  se convertía en 3.
- El emparejado por nombres aceptaba «Girona - Osasuna» como «Sevilla -
  Osasuna» con un lado exacto y el otro cualquiera. Ahora los dos lados
  tienen que parecerse.
- La previa guardaba las cuotas de un partido por jugar antes de guardar su
  cabecera, y la clave foránea lo rechazaba.
- La conexión de SQLite deja de estar atada al hilo que la abrió, que es lo
  que necesita un servidor con un hilo por petición.

### Lo que no se ha podido comprobar

Las fuentes nuevas están escritas contra el formato que documentan
`soccerdata` y los propios sitios, pero desde donde se escribieron no había red
hacia ellos. La primera ejecución real es la prueba.

## 0.4.0

La memoria ya guardaba muchos partidos. Lo que faltaba era la pregunta que
justifica guardarlos: **cómo rinde un jugador según a qué se enfrenta**.

### Novedades

- **Jugador contra sistema** (`cancha/sistemas.py`, `cancha contra`,
  `cancha duelo`, `cancha sistema`): agrupa los partidos de un jugador por el
  sistema que le puso delante el rival y compara cada grupo con la media del
  propio jugador. Con tres cuidados que son el módulo entero:
  - **el sistema se mide, no se supone**: se caracteriza cada partido por lo
    que pasó en él —formación, presión al estilo del PPDA, posesión—, porque el
    mismo equipo no plantea igual en casa que fuera;
  - **se compara contra su liga**: los cortes salen de los terciles de la propia
    competición, así que «presiona alto» significa alto *para ahí*, y si no hay
    muestra para calcularlos no se etiqueta;
  - **si no hay muestra, se dice**: todo por 90 minutos, y cada diferencia
    contrastada contra el azar con una Poisson de una cola. Por debajo de tres
    partidos o 180 minutos el veredicto es `sin muestra`, por bonito que sea el
    número.
- **La memoria guarda las alineaciones** (esquema v2): sin la formación no hay
  línea de cinco que valga. Las bases viejas se migran solas al abrirlas; nadie
  tiene que repetir un barrido de una semana porque el esquema creció.
- **Tres herramientas más para la IA** (32 en total): `sistema_de_equipo`,
  `jugador_contra_sistema` —con `solo_lo_relevante`, para que al modelo le
  lleguen los hallazgos y no cien números— y `duelo_jugador_rival`.
- **[Documentación](docs/sistemas.md)** de todo esto, incluido un apartado
  entero de lo que **no** dice: el sesgo de selección (a los bloques bajos se
  les juega sobre todo siendo favorito) está escrito también en cada respuesta.

### Arreglos

- **El barrido se caía con un 404**: la ruta global de partidos del día
  (`/sport/football/scheduled-events/{fecha}`) ha dejado de existir. Ahora se
  intenta y, si no está, se pide competición por competición, que es más lento
  pero funciona.
- **`--rate 0` no llegaba a las fuentes**: cada una imponía su propio ritmo
  pasara lo que pasara, así que la opción existía y no hacía nada ahí. De paso,
  la batería de tests baja de dieciséis segundos a menos de tres.
- **ClubElo no contestaba nunca**: con el transporte que imita a Chrome se
  quedaba en treinta segundos y cero bytes por http y por https. Es una API
  pública que sirve CSV, sin anti-bot que sortear, así que ahora se le habla
  con `urllib`. De paso, cada fuente puede pedir el transporte que le convenga.

## 0.3.0

El framework sabía traer los datos de **un** partido. Ahora se acuerda de
muchos, que es lo que hace falta para analizar de verdad: un dato suelto no
dice nada sin saber qué es normal en esa liga o en ese jugador.

### Novedades

- **Memoria local** (`cancha/almacen.py`): una base SQLite —biblioteca
  estándar— con partidos, estadísticas, actuaciones de jugadores, tiros e
  incidencias. Guardar es idempotente, así que un barrido se puede cortar y
  reanudar sin romper nada.
- **Barrido** (`cancha barrido`): la agenda del día en 25 competiciones (las
  cinco grandes, UEFA, MLS, Arabia, y varias europeas y americanas) y, de cada
  equipo que juega, sus últimos partidos con detalle. El primero es caro; los
  siguientes casi no, porque solo entra lo nuevo.
- **Estilo de equipo** (`cancha estilo`): posesión, verticalidad, juego por
  fuera, dependencia del balón parado, presión… todo **comparado con la media
  de su liga**, y esa media se calcula sin contar al propio equipo.
- **Forma y rachas de jugador** (`cancha forma`): cuántos partidos lleva sin
  marcar, sin tirar entre palos o sin ser titular. Las rachas solo cuentan
  partidos jugados, no los que pasó en el banquillo.
- **Perfil de árbitro** (`cancha arbitro`): tarjetas, penaltis y faltas por
  partido, y cómo reparte entre local y visitante. Sale de contar sus partidos
  guardados; Sofascore no publica un endpoint para esto.
- **Previa** (`cancha previa`): todo junto sobre un partido por jugar, incluido
  dónde se pueden hacer daño.
- **Seis herramientas más para la IA** (29 en total), ninguna de las cuales
  sale a la red: leen de la memoria. Con `agenda_del_dia` y `previa_de_partido`
  se escribe un repaso diario entero.

### Arreglos

- **ClubElo se pedía por HTTP plano** y se quedaba colgado quince segundos sin
  recibir un byte. Ahora se intenta primero por HTTPS, con el HTTP de reserva.
  El mecanismo es general: cualquier fuente puede declarar raíces alternativas
  y su propio timeout.
- Cuando una fuente no contestaba, el aviso culpaba a cómo hubieras escrito el
  nombre del equipo. Ahora distingue «no encontrado» de «no ha contestado».
- El orden en que la IA ve las herramientas ya no depende del orden de los
  imports, que cualquier formateador reordena sin avisar.

### Verificado contra la API real

**Understat funciona.** Se escribió a ciegas, leyendo el código de
`soccerdata`, y en la primera ejecución real dio 1.41–2.52 de xG donde
Sofascore daba 1.46–2.58: los dos modelos coinciden dentro de 0.06.

## 0.2.0

El paquete se llamaba `sofascore` y hablaba solo con Sofascore. Ahora se llama
**`cancha`**, habla con tres fuentes y trae una capa pensada para que una IA
analice partidos por su cuenta. **El nombre viejo sigue funcionando** —`import
sofascore`, `python -m sofascore` y el comando `sofascore`— y no hay planes de
quitarlo.

### Novedades

- **Para una IA local.** 23 herramientas con su esquema JSON y descripciones
  escritas para que un modelo sepa cuándo usar cada una, más un **servidor MCP**
  (`cancha mcp`) sin dependencias. Las respuestas vienen recortadas para no
  llenarle el contexto, y un fallo llega como dato legible en vez de excepción.
- **Métricas calculadas** (`cancha analisis`): puntos esperados a partir del xG
  de cada disparo —convolución exacta, no una aproximación de Poisson—, calidad
  de tiro, carrera de xG minuto a minuto, desglose por situación y aportación
  por jugador. Son las cuentas que un modelo hace mal.
- **Otras fuentes**: Understat (un segundo modelo de xG) y ClubElo (fuerza real
  de un club). Y `cancha contexto`, que **cruza las fuentes** sobre un mismo
  partido: los dos modelos de xG con su diferencia calculada y el Elo de ambos
  equipos. El emparejado lo hace el framework, que es lo que `soccerdata` y
  `ScraperFC` dejan en tus manos.
- **Equipos, jugadores y competiciones**: 28 secciones nuevas con la misma
  mecánica que los partidos, y `cancha team|player|league`.
- **Grabar respuestas reales** (`cancha grabar`) y reproducirlas sin red
  (`--replay`), con tests de contrato que comprueban que la API devuelve lo que
  el código supone.
- **Sesión de análisis**: ocho preguntas seguidas sobre un partido pasan de 25
  peticiones a 11.
- **Transporte con huella TLS de Chrome** (`curl_cffi`, opcional), que es lo
  único que atraviesa el anti-bot de Cloudflare. Se elige solo si está
  instalado.
- **Integración continua**: los tests en Python 3.10–3.13 sobre Linux, Windows y
  macOS, más un trabajo que comprueba que se puede vivir sin dependencias.
- Comandos nuevos: `analisis`, `contexto`, `fuentes`, `grabar`, `grabaciones`,
  `cookie`, `doctor`, `mcp`, `tools`, `live`, `today`, `leagues`.
- Tablas y `DataFrame` (`informe.tables()` / `informe.frames()`), catálogo de 37
  ligas, códigos de estado y 110 claves de estadística.

### Arreglos

Todos salieron de ejecutarlo contra la API de verdad:

- `/h2h/events` pide el **`customId`** del partido, no el id numérico. Con el id
  devuelve 404 siempre, y esa ruta era además la última vía para encontrar un
  cruce antiguo: llevaba dos rondas sin hacer nada, en silencio.
- La **probabilidad de victoria** cuelga de `/event/{id}/graph/win-probability`,
  no de `/event/{id}/win-probability`.
- **`--date` no filtraba**: se pedía un partido de 2024 y salía uno de 2026 con
  los mismos equipos. La fecha era una penalización blanda cuando el usuario la
  da como condición dura.
- **No se llegaba a partidos de hace temporadas**: solo se pedía la primera
  página del calendario del equipo, los ~30 partidos más recientes.
- **Lo de «Plus» era casi todo mentira**: `shotmap`, `heatmaps`,
  `average_positions` y `player_statistics` los sirve la API abiertos.
  Marcarlos como de pago hacía que `--no-plus` se saltara datos gratis.
- El **CSV de incidencias salía del final al principio** y los cambios de
  jugador aparecían sin nadie, porque en un cambio la API no usa la clave
  `player`.
- `--debug` solo existía en `match`; los demás comandos fallaban con
  «unrecognized arguments».
- `live` devolvía 150 partidos en una lista plana empezando por amistosos y
  ligas sub-12. Ahora van agrupados por competición y se pueden filtrar.
- Las **estadísticas de temporada de un jugador** pedían dos ids que nadie sabe
  de antemano; ahora se deducen del propio informe.
- `cancha login` sondeaba con una sección que da 404 en muchos partidos, así que
  no decía nada de tus credenciales.
- **ClubElo se pedía por HTTP plano** y se quedaba colgado quince segundos sin
  recibir un byte. Ahora se intenta primero por HTTPS, con el HTTP de reserva y
  más paciencia. Y cuando una fuente no contesta, el aviso ya no culpa a cómo
  hayas escrito el nombre del equipo.

### Cambios internos

- `tools.py` (839 líneas) y `cli.py` (898) repartidos en paquetes por familias;
  `cli.py` queda en 56 líneas. El README, en nueve páginas bajo `docs/`.
- Las variables de entorno aceptan `CANCHA_` además de `SOFA_`.
- La carpeta de caché pasa a `.cancha-cache`.
- Un fixture corta la red en los tests: uno que intente salir a internet falla
  al instante y con nombre, en vez de colgar la suite.
- De 101 tests a 398.

## 0.1.0

La primera versión: le dices un partido de Sofascore y te devuelve todos sus
datos. Catálogo declarativo de secciones, resolución de partidos por nombre,
caché en disco, límite de peticiones, exportación a JSON, Markdown y CSV, y
soporte para tus propias credenciales de Sofascore Plus. Sin dependencias.
