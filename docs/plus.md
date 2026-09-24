# Sofascore Plus

**Antes de nada, un aviso honesto:** casi todo lo que la web enseña detrás del
reclamo de Plus —mapa de tiros, xG por disparo, posiciones medias, mapas de
calor, estadísticas por jugador— **la API lo sirve abierto**. Lo comprobamos
pidiéndolo sin ninguna credencial. Así que probablemente no necesites nada de
esta sección.

**El framework no rompe ni esquiva ningún muro de pago.** Si tienes la
suscripción y alguna sección sí la exige, tu navegador ya recibe esos datos
porque tu sesión está autenticada; aquí simplemente reutilizas *tu* sesión para
pedir lo mismo desde Python. Sin credenciales, esas secciones salen como
`plus_required` y el informe sigue con todo lo demás.

Copia `.env.example` a `.env` y rellena **una** de las tres opciones:

```ini
SOFA_PLUS_COOKIE=          # la cabecera Cookie de tu navegador con sesión iniciada
SOFA_PLUS_TOKEN=           # o un token Bearer de tu cuenta
SOFA_PLUS_COOKIE_FILE=     # o un JSON de cookies exportado del navegador
```

Comprueba que funcionan:

```bash
cancha login 12437616
# Partido de prueba: Real Madrid 0 - 4 FC Barcelona (LaLiga, 2024-10-26)
# ✓ Las credenciales funcionan: 'ai_insights' ha traído datos de pago.
```

Las sondas son secciones que de verdad requieran suscripción —probar con el
mapa de tiros no diría nada, porque sale `ok` tengas cuenta o no— y se prueban
todas hasta que una responda algo concluyente: varias no existen en todos los
partidos, y un 404 no dice nada de tus credenciales.

### Sacar la cookie sin volverse loco

Buscarla a mano entre cientos de peticiones —y en las cabeceras de *solicitud*,
no en las de respuesta— es donde se atasca todo el mundo. No hace falta:

1. Entra en `sofascore.com` con tu sesión de Plus iniciada.
2. `F12` → pestaña **Red** → botón **Fetch/XHR** (quita el ruido de imágenes y
   scripts). Recarga con `F5`.
3. **Botón derecho** sobre cualquier petición a `api.sofascore.com` →
   **Copiar** → **Copiar como cURL**.
4. En la terminal:

```bash
cancha cookie --save
```

Pega lo copiado, `Ctrl+Z` y `Enter` en Windows (`Ctrl+D` en Linux/Mac). Él
encuentra la cookie, te dice cuántos valores tiene y la escribe en tu `.env`.

Vale cualquiera de los tres formatos que da el navegador: *Copiar como cURL*
(bash o cmd), *Copiar como PowerShell*, o lo que devuelva `document.cookie` en
la consola. Sin `--save` te enseña la línea para que la pegues tú.

Son credenciales personales: no las compartas ni las subas a ningún repositorio
(`.env` está en `.gitignore`). Caducan, así que si un día `login` dice que no
las aceptan, vuelve a copiarlas.

---

[← Volver al índice](../README.md)
