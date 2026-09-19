# El analista local

```bash
cancha analista "¿cómo se le da a Vinicius el Getafe?"
cancha analista                      # conversación
cancha analista --comprobar          # ¿está Ollama? ¿está el modelo?
```

Había dos formas de darle esto a una IA: el servidor MCP, para clientes que lo
hablan, y los esquemas sueltos, para montártelo tú. Faltaba la tercera y la más
útil en una máquina propia: **preguntar en castellano y que alguien vaya a
buscarlo**.

## Qué hace falta

[Ollama](https://ollama.com), arrancado, y un modelo que sepa **llamar
funciones**. Esto último no es opcional: un modelo que no sabe llamarlas
contesta de memoria, con aplomo y sin haber mirado un solo dato, que es la peor
forma de fallar.

```bash
ollama pull hermes3        # el recomendado: afinado para esto
```

Valen también `qwen3`, `qwen2.5`, `llama3.1`, `mistral-nemo` y `command-r`.
`cancha analista --comprobar` dice cuáles tienes y avisa si el que pides no
está.

## Cómo trabaja

El bucle es el de siempre —el modelo pide una herramienta, se ejecuta, se le
devuelve el resultado, y otra vuelta— con dos cosas que importan:

**Cada paso se ve.** No devuelve un párrafo salido de la nada:

```
› ¿cómo llega el Girona?
  → estilo_de_equipo(equipo=Girona)
     3480 caracteres
  → forma_de_jugador(jugador=Stuani)
     1120 caracteres

El Girona llega con 11-7 en seis partidos y dos rasgos que lo separan de
LaLiga: tiene el balón un 22 % más que la media y juega en largo un 31 %
menos. Concede 1,42 xG por partido, que es mucho para un equipo que domina.
```

**El modelo no inventa cifras.** Las instrucciones son explícitas y se
comprueban en los tests: los números salen de las herramientas o no se dicen, un
veredicto de `sin muestra` es la conclusión y no un obstáculo, y `es la tasa
base` significa que **no** es un hallazgo.

Opciones: `--modelo`, `--url` (si Ollama no está en el sitio de siempre),
`--vueltas` (tope de llamadas por pregunta), `--temperatura`, `--quiet`.

## En la interfaz

La pestaña **Analista** de [`cancha web`](interfaz.md) es lo mismo con las
herramientas en marcha a la vista: cada una aparece como una etiqueta mientras
se ejecuta y se queda con cuántos caracteres devolvió. El hilo se guarda en el
navegador, así que puedes seguir la conversación al día siguiente.

## Con LangChain

Si ya tienes un agente montado, las herramientas se enchufan sin reescribir
nada:

```bash
pip install "cancha[langchain]"
```

```python
from cancha.agentes.langchain import agente, herramientas

herramientas()          # 41 StructuredTool, para tu propio agente
agente(modelo="hermes3").invoke({"messages": [("user", "¿qué hay hoy?")]})
```

`agente()` monta un `create_agent` de LangChain 1.x con `ChatOllama`, las
herramientas de cancha y las mismas instrucciones. `modelo` acepta también un
chat model ya construido, por si prefieres otro proveedor: las herramientas son
las mismas.

Todas comparten una sola [`Sesion`](libreria.md), que es lo que hace que ocho
preguntas sobre el mismo partido cuesten un partido y no ocho.

## Lo que no es

No es un modelo entrenado en fútbol: es un modelo general con acceso a datos
buenos. Lo que aporta el framework es que **los datos que ve sean correctos y
vengan con su veredicto**, que es justo lo que un modelo no sabe hacer por su
cuenta.

---

[← Volver al índice](../README.md)
