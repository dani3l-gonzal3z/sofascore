# Para una IA local

El framework trae una capa de herramientas pensada para que un modelo analice
partidos por su cuenta: 23 funciones con su esquema JSON, descripciones
escritas para que el modelo sepa cuándo usar cada una, y respuestas ya
aplanadas y **recortadas** para que no le revienten el contexto.

```bash
cancha tools          # las 23, con sus parámetros
cancha tools --json   # los esquemas completos
cancha mcp            # arranca el servidor MCP
```

### Por MCP (lo más cómodo)

MCP es el estándar por el que un modelo descubre herramientas y las llama. Lo
hablan Claude Desktop, LM Studio, Continue, Cline y compañía. En
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sofascore": {
      "command": "python",
      "args": ["-m", "sofascore", "mcp"],
      "env": { "SOFA_LANGUAGE": "es" }
    }
  }
}
```

Y ya está: el modelo ve las herramientas y va tirando del hilo solo.

### A mano, con cualquier modelo

```python
from cancha import Sesion, esquemas_herramientas, ejecutar_herramienta

esquemas_herramientas()          # se los pasas como definición de funciones

# Una sesión para toda la conversación: cada sección se pide UNA vez.
with Sesion() as sesion:
    ejecutar_herramienta("resumen_partido", {"partido": "Real Madrid vs Barcelona"},
                         sesion=sesion)
    ejecutar_herramienta("tiros_partido", {"partido": "Real Madrid vs Barcelona"},
                         sesion=sesion)
```

Sin sesión cada llamada empieza de cero: resuelve el partido otra vez y vuelve
a pedir lo que ya tenía. En una conversación normal de ocho preguntas sobre un
partido eso son **25 peticiones en vez de 11**. El servidor MCP mantiene una
sesión durante toda la conversación, así que por ahí ya viene puesto.

Sirve igual con Ollama, llama.cpp, LM Studio o la API que uses: el framework no
trae ningún modelo dentro. `python examples/agente.py` enseña el bucle entero.

### Cómo está pensado que indague

La gracia no es volcarle un JSON de tres megas —no le cabe— sino que vaya
tirando del hilo:

1. **`resumen_partido`** es siempre el principio: marcador, goles, mejores
   notas y, sobre todo, **qué secciones de datos existen** para ese partido.
2. Desde ahí baja al detalle: `estadisticas_partido` (por periodo o por bloque),
   `jugadores_partido` (por equipo), `tiros_partido` (xG por disparo, filtrable
   por jugador), `cronologia_partido`, `momento_partido` (agrupado en tramos).
3. **`analisis_partido`** le da las cuentas hechas —puntos esperados, calidad
   de tiro, carrera de xG— para que no las haga él, que es donde falla.
4. Amplía el contexto: `historial_entre_equipos`, `ficha_equipo`,
   `ficha_jugador`, `clasificacion`, `partidos`. Y sobre todo
   **`contexto_externo`**, que cruza las fuentes: los dos modelos de xG con su
   diferencia, y el Elo de ambos equipos.
5. Si algo no lo cubre ninguna, `seccion_partido` le da cualquier sección del
   catálogo en crudo. Y `catalogo` le dice qué nombres son válidos.

Toda respuesta pasa por un tope de caracteres: si algo no cabe, se corta y se
le dice cuánto falta y cómo afinar, en vez de llenarle el contexto en silencio.
Un error tampoco es una excepción, es un dato que el modelo puede leer y
corregir.

---

[← Volver al índice](../README.md)
