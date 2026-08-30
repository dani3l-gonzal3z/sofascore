# La línea de comandos

```bash
cancha match <consulta> [opciones]     # informe completo de un partido
cancha team "Real Madrid"              # plantilla, calendario, forma, traspasos
cancha player "Vinicius Junior"        # ficha, atributos, temporadas
cancha league laliga                   # clasificación, jornadas, goleadores
cancha live [--league laliga]          # lo que se está jugando ahora mismo
cancha today [--date AAAA-MM-DD]       # todos los partidos de un día
cancha leagues [filtro]                # ligas conocidas con su id
cancha search <consulta>               # partidos candidatos
cancha sections [--kind team]          # catálogo de secciones
cancha cookie [--save]                 # saca tu cookie de lo copiado del navegador
cancha login [partido]                 # comprueba tus credenciales Plus
cancha raw /event/11352550/statistics  # cualquier ruta de la API, tal cual
cancha grabar <partido>                   # guarda respuestas reales para los tests
cancha analisis <partido>                 # las cuentas hechas: puntos esperados, xG
cancha fuentes                         # qué fuentes hay además de Sofascore
cancha contexto <partido>              # el partido visto por todas a la vez
cancha tools [--json]                  # las herramientas que ve una IA
cancha mcp                             # servidor MCP para una IA local
cancha doctor                          # qué transporte usa y si la API contesta
cancha cache [--clear]                 # estado de la caché
```

Los que necesitan [memoria](memoria.md) —hay que hacer un barrido antes—:

```bash
cancha barrido [--grupos grandes]      # trae los partidos del día y el historial
cancha memoria                         # qué hay guardado
cancha agenda [--date AAAA-MM-DD]      # qué se juega en las ligas que importan
cancha estilo "Girona"                 # cómo juega un equipo, contra su liga
cancha forma "Vinicius"                # cómo está y qué rachas lleva
cancha arbitro "César Soto Grado"      # cómo pita, según sus partidos guardados
cancha previa "Girona vs Osasuna"      # todo lo que se sabe antes de jugarse
cancha sistema "Getafe"                # con qué plantea: dibujo, presión, posesión
cancha contra "Vinicius" [--eje linea] # cómo rinde según lo que le pongan delante
cancha duelo "Vinicius" "Getafe"       # el jugador contra el sistema de ese rival
```

Opciones más usadas de `match`:

| Opción | Para qué |
| --- | --- |
| `--date AAAA-MM-DD` | Desempatar entre varios cruces |
| `--all` | Pedir todas las secciones del catálogo |
| `--sections statistics,shotmap` | Solo las que te interesan |
| `--no-plus` | Ni intentar las de pago |
| `--json p.json` `--markdown p.md` `--csv carpeta/` | Guardar el resultado |
| `--print statistics` | Volcar una sola sección por pantalla |
| `--stdout-json` | El informe entero en JSON, listo para `jq` |
| `--offline` / `--no-cache` | Solo caché / ignorar caché |
| `--parallel N` | Secciones a la vez (`1` las pide de una en una) |
| `--transport curl` | Forzar transporte (`auto`, `curl`, `httpx`, `urllib`) |
| `--debug` | Contadores de peticiones y ajustes en uso |

`--debug`, `--offline`, `--no-cache`, `--parallel` y `--transport` valen en
**todos** los comandos, no solo en `match`.

```bash
cancha match 11352550 --all --json partido.json --csv datos/
cancha match 11352550 --print statistics --quiet | jq '.[0].groups'
```

---

[← Volver al índice](../README.md)
