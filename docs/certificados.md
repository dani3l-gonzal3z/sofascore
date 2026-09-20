# Cuando algo abre tu HTTPS

Un día no se conecta nada y el error es este:

```
No llego a Telegram: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: self-signed certificate in certificate chain>
```

**No es el bot, ni Telegram, ni Sofascore.** Es que algo entre tu ordenador y la
red se está poniendo en medio de tus conexiones seguras: descifra, mira, vuelve a
cifrar con un certificado suyo y te lo presenta. Python comprueba quién firma ese
certificado, no lo conoce y corta. Y hace bien: eso es exactamente lo que tiene
que hacer cuando alguien se pone en medio.

Los sospechosos habituales son tres:

- un **antivirus** con la opción de «revisar webs seguras» encendida (Kaspersky,
  ESET, Avast, Bitdefender…);
- el **proxy** de una empresa, un colegio o una universidad (Zscaler, Netskope…);
- un cliente de **VPN**.

## Primero: saber quién es

```bash
cancha doctor --tls
```

Se asoma al certificado que te están presentando y saca el nombre de quien lo
firma. Casi siempre es el nombre del programa, tal cual:

```
  api.telegram.org
    certificados  los que trae Python
    🚫 Quien firma el certificado se llama «Kaspersky Anti-Virus Personal Root».
       Eso es lo que está abriendo tu HTTPS.
```

Desde el móvil es el botón **«¿Alguien abre mi HTTPS?»**, en Memoria →
Diagnóstico.

Que se mire sin verificar nada es a propósito: la pregunta no es «¿me fío?»
—ya sabemos que no— sino «¿quién es?».

## Luego: arreglarlo

De mejor a peor.

### 1. `pip install truststore`

```bash
pip install truststore        # o: pip install "cancha[tls]"
```

Es el arreglo bueno en Windows y en macOS, y casi siempre el único que hace
falta. Hace que Python use el **almacén de certificados del sistema**, que es
justo donde el antivirus o el proxy de tu empresa han dejado el suyo al
instalarse. Con eso, lo que tu sistema ya considera de fiar pasa a serlo aquí
también, sin exportar nada ni bajar ninguna guardia.

`cancha` lo usa solo si está instalado. No es obligatorio, como todo lo demás.

### 2. Decirle dónde está el certificado

Si no puedes instalar nada, exporta el certificado de quien firma a un fichero
`.pem` y apunta ahí:

```bash
cancha ajustes red.ca_bundle=C:\ruta\al\certificado.pem
```

O, solo para una vez, `--ca-bundle C:\ruta\al\certificado.pem`. También se puede
poner desde la interfaz, en Ajustes → Certificados, incluido desde el móvil.

Si ya tienes `SSL_CERT_FILE` o `REQUESTS_CA_BUNDLE` puestas —es lo normal cuando
alguien ha tenido que hacer funcionar `pip` en una red así—, `cancha` las usa sin
que configures nada.

### 3. Apagar la revisión de HTTPS en el antivirus

Suele llamarse «análisis HTTPS», «escaneo SSL» o «revisar webs seguras». Es una
opción de tu antivirus, no de esto.

### 4. Dejar de comprobar (último recurso)

```bash
cancha ajustes red.sin_verificar=si
```

Funciona siempre, y es lo peor de la lista: deja de comprobar con quién se está
hablando, así que cualquiera que se ponga en medio puede leer y cambiar lo que
pasa por ahí —incluido el token de tu bot—. `cancha` lo dice al arrancar y lo
repite en los ajustes cada vez que lo mira. Está porque a veces no hay otra, no
porque sea una alternativa.

## Qué se ve afectado

Todo lo que sale a internet, que son cuatro cosas: **Sofascore** y las demás
fuentes, la **nube de Ollama** (el Ollama de tu casa va por HTTP y no le afecta),
el **bot de Telegram** y las **cuotas**. Por eso los certificados se ponen una
vez, en un sitio, y valen para todos.

Con una excepción que conviene saber: `curl_cffi` —el transporte recomendado,
que imita el TLS de Chrome— lleva sus propios certificados y **no** entiende el
almacén del sistema. Con él, `truststore` no sirve de nada y hay que darle la
ruta del `.pem`. Se le pasa sola en cuanto pongas `red.ca_bundle`.

## Cómo se comprueba esto

En las pruebas se fabrica un certificado autofirmado y se levanta un servidor TLS
en `localhost` que lo presenta: es exactamente lo que hace un antivirus que abre
el HTTPS. Sobre eso se comprueba que se detecta, que se saca el nombre de quien
firma y que confiando en él a propósito deja de dar error. Sin red y sin
dependencias, como todo lo demás.

---

[← Volver al índice](../README.md)
