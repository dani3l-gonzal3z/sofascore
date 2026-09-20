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

## El otro camino: darle todo de una vez

Esto de arriba es un modelo pequeño **buscando**: pide una herramienta, lee,
pide otra. Con 8B en tu ordenador es lo correcto. Si lo que quieres es un modelo
**grande** que lo vea todo a la vez y ate cabos —el suyo no es buscar, es
razonar sobre lo ya reunido—, eso es `cancha dictamen`, y está en
**[Dictamen](dictamen.md)**. Ahí entra también la nube de Ollama, que es la
única parte de este proyecto en la que los datos salen de tu ordenador.

## Qué hace falta

[Ollama](https://ollama.com), arrancado, y un modelo que sepa **llamar
funciones**. Esto último no es opcional: un modelo que no sabe llamarlas
contesta de memoria, con aplomo y sin haber mirado un solo dato, que es la peor
forma de fallar.

```bash
ollama pull hermes3        # el recomendado: afinado para llamar funciones
```

**Sobre el tamaño.** `hermes3` a secas es la variante de **8B**: no existe una
de 7B, así que si buscabas «hermes3 7b», es esta. Es la que hay que probar
primero — ocupa unos 5 GB y va bien en un portátil normal. Si quieres bajar
más, `qwen2.5:7b` y `mistral:7b` también llaman funciones. Y si el equipo da
para más, `hermes3:70b` razona mejor encadenando herramientas, pero **no va a
dar números más ciertos**: los números no los pone el modelo.

```bash
cancha analista --modelo qwen2.5:7b "¿cómo llega el Girona?"
cancha telegram --token ... --chat ... --modelo qwen2.5:7b
```

Valen también `qwen3`, `llama3.1`, `mistral-nemo` y `command-r`.
`cancha analista --comprobar` dice cuáles tienes y avisa si el que pides no
está.

**Lo que el tamaño no arregla.** Un modelo pequeño se equivoca eligiendo qué
herramienta llamar, o se lía encadenando tres. Lo que **ningún** tamaño arregla
es inventarse una cifra, y por eso los números —el pronóstico, las frecuencias,
las medias— se calculan en Python y el modelo solo los lee. Ver
[El pronóstico](pronostico.md).

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

herramientas()          # 44 StructuredTool, para tu propio agente
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
