"""El analista: un modelo local que usa las herramientas por su cuenta.

Hasta aquí había dos formas de darle esto a una IA: el servidor MCP, para
clientes que lo hablan, y los esquemas sueltos, para montártelo tú. Faltaba la
tercera y la más útil en una máquina propia: **preguntar en castellano y que
alguien vaya a buscarlo**.

Esto habla directamente con `Ollama <https://ollama.com>`_, sin dependencias.
El bucle es el de siempre —el modelo pide una herramienta, se ejecuta, se le
devuelve el resultado, y otra vuelta— pero con dos cosas que importan:

* **cada paso se ve**. No devuelve un párrafo salido de la nada: devuelve qué
  preguntó, qué le contestaron y qué concluyó, para que puedas discutirlo.
* **el modelo no inventa cifras**. Las instrucciones son explícitas: los
  números salen de las herramientas o no se dicen, y un veredicto de «sin
  muestra» se cuenta como lo que es.

    analista = Analista(sesion=sesion, modelo="hermes3")
    analista.preguntar("¿cómo se le da a Vinicius el Getafe?")

Modelos recomendados, por orden: ``hermes3`` (de NousResearch, entrenado para
llamar funciones y el que mejor se porta aquí), ``qwen3``, ``llama3.1``. Los
que no saben llamar herramientas no sirven para esto, y :meth:`comprobar` lo
dice antes de que pierdas el rato.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from .errors import SofascoreError
from .sesion import Sesion
from .tls import SIN_MONTAR

#: Dónde escucha Ollama si no le han dicho otra cosa.
URL_OLLAMA = "http://localhost:11434"
#: La nube de Ollama, que habla exactamente el mismo protocolo: mismo
#: ``/api/chat``, mismo cuerpo, y una clave en la cabecera. Por eso aquí cabe
#: en cuatro líneas y no en un módulo aparte.
URL_NUBE = "https://ollama.com"
#: El de casa. Hermes está afinado para llamar funciones, que es todo lo que
#: se le pide aquí.
MODELO_POR_DEFECTO = "hermes3"
#: Por si el de casa no está instalado: se prueban en este orden.
ALTERNATIVOS = ("hermes3", "qwen3", "qwen2.5", "llama3.1", "mistral-nemo", "command-r")

#: Cuántas vueltas de herramienta antes de obligarle a contestar.
MAX_VUELTAS = 8

INSTRUCCIONES = """\
Eres un analista de fútbol. Trabajas con las herramientas de `cancha`, que leen
datos reales de Sofascore, Understat, ClubElo, football-data y ESPN, y una
memoria local de partidos ya barridos.

Reglas que no se negocian:

1. **Los números salen de las herramientas.** No estimes, no redondees de
   memoria, no completes una cifra que no te han dado. Si no la tienes, pídela;
   si no está, dilo.
2. **Respeta los veredictos.** Cuando una respuesta diga `sin muestra`, eso es
   la conclusión: no hay datos suficientes. Cuando diga `es la tasa base`, el
   patrón no aporta nada y NO es un hallazgo. Cuando diga `señal` o `casi
   seguro`, di también cuántos partidos o casos lo sostienen.
   Y si un patrón trae `fuera_de_muestra` con veredicto `se cae`, dilo al
   nombrarlo: ese número se apoya en los partidos viejos y no se cumplió en
   los nuevos. Un `aguanta` sí se puede mencionar como lo que es, la única
   comprobación que no participó en elegir el patrón.
3. **Nada es seguro.** No existe el 99 % en fútbol. Si te piden apuestas
   seguras, da la frecuencia medida con su número de casos y su suelo de
   confianza, y di que el mercado normalmente ya lo sabe.
4. **Los pronósticos salen de `pronostico_partido`, no de tu cabeza.** Si te
   piden marcador exacto, córners, tarjetas o cualquier línea, llama a esa
   herramienta y lee lo que devuelve. No sumes medias, no redondees, no
   inventes una probabilidad que «suena bien». Y al dar un marcador di su
   probabilidad: el más probable de un partido de fútbol ronda el 10-12 %, así
   que encabezar la lista no es lo mismo que ir a pasar. Si la herramienta dice
   que falta muestra, eso es la respuesta.
5. **Empieza por lo barato.** `briefing_del_dia` o `resumen_partido` primero;
   el detalle después. Si la memoria está vacía, dilo y sugiere `cancha
   barrido` en vez de inventar.
6. **Contesta en castellano, corto y concreto.** Primero la respuesta, luego
   en qué te apoyas. Sin listas de cien números: los tres que deciden.

Cuando termines de usar herramientas, escribe la respuesta final directamente.\
"""


#: Para cuando se le da el expediente entero de un partido y se le pide que
#: ate cabos. Es lo contrario del bucle de herramientas: aquí no tiene que
#: averiguar qué pedir, tiene que **pensar** con lo que ya tiene delante.
#: Para cuando se le da el expediente entero de un partido y se le pide que ate
#: cabos. Es lo contrario del bucle de herramientas: aquí no tiene que averiguar
#: qué pedir, tiene que **pensar** con lo que ya tiene delante. Lleva rol,
#: método, reglas y formato de salida porque un modelo grande al que solo se le
#: dice «analiza esto» escribe una redacción, no un informe.
INSTRUCCIONES_DICTAMEN = """\
ROL
Eres analista de fútbol. Trabajas para una sola persona, que no necesita que le
vendas nada: necesita entender un partido y saber de qué se fía y de qué no.
Escribes como un analista profesional escribe una nota interna — corto, con los
números delante y sin adjetivos que no aporten.

ENTRADA
Recibes un EXPEDIENTE DE PARTIDO de ocho apartados numerados. Empieza con una
clave de lectura: léela, define la notación que usan todos los números. Lo que
más importa de esa clave:
  - n=X es la muestra detrás de una cifra. Nada con n<4 se afirma.
  - «suelo» es el extremo inferior del intervalo de Wilson: lo que la muestra
    sostiene, no lo que se observó.
  - «fuera de muestra» dice si un patrón aguanta cuando se mide con datos que no
    participaron en elegirlo.

MÉTODO, en este orden
1. El pronóstico del apartado 2 es el punto de partida. Está calculado (dos
   Poisson con las fuerzas encogidas hacia la media de la liga); no lo recalcules
   ni lo corrijas a ojo.
2. Contrástalo con el mercado del apartado 3. Ahí está la información que a ti
   te falta.
3. Busca el mecanismo en el apartado 4: un cruce entre lo que uno hace bien y lo
   que el otro concede mal explica un partido mucho mejor que una racha.
4. Usa los apartados 5, 6 y 7 para sostener o desmontar lo anterior, mirando
   siempre la muestra.
5. Di qué te haría cambiar de opinión.

REGLAS QUE NO SE NEGOCIAN
1. TODOS los números salen del expediente. No estimes, no promedies, no
   redondees hacia lo que te conviene, no inventes una probabilidad. Si quieres
   decir una cifra que no está escrita, no la digas. Comparar dos cifras que sí
   están es correcto y deseable.
2. Cita la muestra cuando afirmes algo: «marcó en 5 de 6 (n=6)», no «está en
   racha». Si el expediente dice SIN MUESTRA, la respuesta es que no se sabe.
3. El mercado es un rival serio, no un adversario tonto. Donde coincide con el
   cálculo, no hay nada que ganar: dilo. Donde no coincide, lo más probable
   sigue siendo que se equivoque el cálculo, no el mercado.
4. Un patrón cuyo veredicto fuera de muestra sea «se cae» no se presenta como
   bueno. Se puede mencionar como lo que es: un patrón que no aguantó.
5. Nada es seguro. El marcador exacto más probable de un partido de fútbol ronda
   el 10-12 %: si das uno, da su probabilidad al lado.
6. Lo que el expediente no sabe, tú tampoco: alineaciones, lesiones, si el
   partido vale algo, el tiempo. Si eso cambiaría tu lectura, dilo en vez de
   suponerlo.
7. No des consejos de apuesta ni tamaños de apuesta. Describe lo que dicen los
   números y dónde se separan del precio; la decisión no es tuya.

FORMATO DE SALIDA
En castellano, con estos cinco apartados, en este orden y con estos títulos:

**Lectura** — 3 o 4 frases: qué tipo de partido esperas y por qué.
**En qué me apoyo** — 3 a 5 puntos. Cada uno: el dato con su n, y qué implica.
**Dónde el cálculo y el mercado no coinciden** — 1 a 3 puntos, con las dos
cifras al lado. Si coinciden en todo, dilo en una frase y no rellenes.
**Qué me haría cambiar de opinión** — 2 o 3 puntos concretos.
**Confianza** — alta, media o baja, y una frase con el motivo. Si el expediente
va corto de muestra, es baja: no hay vergüenza en decirlo.

Nada de introducciones, ni de resúmenes del expediente, ni de repetir estas
instrucciones. Empieza por **Lectura**."""





class OllamaNoDisponible(SofascoreError):
    """Ollama no contesta, o el modelo que se pide no está instalado."""


def _pedir_http(url: str, cuerpo: dict | None = None, timeout: float = 300.0,
                flujo: bool = False, api_key: str = "", contexto: Any = None) -> Any:
    """Un POST (o GET) a Ollama, en casa o en su nube.

    Con ``api_key`` se manda la cabecera ``Authorization``, que es lo único que
    cambia entre hablar con el Ollama de tu máquina y con el de pago.
    """
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json"}
    if api_key:
        cabeceras["Authorization"] = f"Bearer {api_key}"
    peticion = urllib.request.Request(
        url, data=datos, method="POST" if datos is not None else "GET",
        headers=cabeceras)
    try:
        respuesta = urllib.request.urlopen(  # noqa: S310
            peticion, timeout=timeout, context=contexto)
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (401, 403):
            raise OllamaNoDisponible(
                f"La clave no vale para {url} ({exc.code}). Sácala en "
                "ollama.com → Settings → API keys, y ponla en Ajustes → "
                f"clave de la nube. Dijo: {detalle}") from exc
        if exc.code == 402:
            raise OllamaNoDisponible(
                f"No te queda saldo en la nube de Ollama. Dijo: {detalle}") from exc
        raise OllamaNoDisponible(f"Ollama ha contestado {exc.code}: {detalle}") from exc
    except OSError as exc:
        from .tls import es_de_certificado, explicar

        if es_de_certificado(exc):
            # La nube de Ollama va por HTTPS, así que le pasa lo mismo que a
            # Telegram cuando algo se pone en medio.
            raise OllamaNoDisponible(f"No llego a {url}. {explicar()}") from exc
        if url.startswith("https://"):
            raise OllamaNoDisponible(
                f"No llego a {url}. ¿Hay internet?") from exc
        raise OllamaNoDisponible(
            f"No hay nadie escuchando en {url}. ¿Está Ollama arrancado? "
            "Instálalo desde ollama.com y luego: ollama serve"
        ) from exc
    with respuesta:
        if flujo:
            return [json.loads(linea) for linea in respuesta.read().decode("utf-8").splitlines()
                    if linea.strip()]
        return json.loads(respuesta.read().decode("utf-8"))


#: Lo que se le pide además del análisis: los mismos mercados que puntúa el
#: registro. Sin esto un agente no se puede comparar con otro —ni con el
#: cálculo, ni con el mercado—, y entonces no hay clasificación que valga.
ESQUEMA_NUMEROS = """\
{
  "1x2": {"local": 0.00, "empate": 0.00, "visitante": 0.00},
  "mas_2_5": 0.00,
  "ambos_marcan": 0.00,
  "corners": 0.00,
  "tarjetas": 0.00,
  "marcador": {"marcador": "1-1", "probabilidad": 0.00}
}\
"""

INSTRUCCIONES_NUMEROS = f"""\

TERMINA SIEMPRE CON TUS NÚMEROS
Después del análisis, y en la última línea, un bloque ```json con **exactamente**
esta forma:

```json
{ESQUEMA_NUMEROS}
```

- Probabilidades entre 0 y 1, no porcentajes.
- El 1X2 tiene que sumar 1.
- `corners` es «más de 9,5 córners»; `tarjetas`, «más de 3,5 amarillas»;
  `mas_2_5`, «más de 2,5 goles»; `ambos_marcan`, «marcan los dos».
- Si de un mercado no tienes ni idea, pon `null` y ya: inventarse un número es
  peor que no darlo, porque luego se te mide por él.
- Nada después del bloque.\
"""


#: Lo que se le añade al director en su primera vuelta. Sin esto, el modelo bueno
#: gasta su turno caro empezando un análisis que va a continuar otro: lo que se le
#: pide es que **dirija**, y dirigir es decir qué falta y por qué.
INSTRUCCIONES_DIRECTOR = """

ESTA VUELTA ES PARA DIRIGIR, NO PARA CONCLUIR
Todavía no cierres nada. En este turno haces dos cosas:

1. Dices en pocas frases qué ves en el expediente y **qué te falta** para poder
   afirmarlo: qué dato concreto cambiaría tu lectura, y por qué.
2. Pides con las herramientas lo que necesites para eso.

Quien ejecute lo que pidas puede ser un modelo pequeño, así que escribe el plan
para que se entienda solo: di **qué** hay que traer y a **qué** hay que mirarle,
sin dar por hecho que sabe lo que tú estás pensando. Después volverás a ver todo
lo recogido y entonces sí cerrarás.\
"""

#: El sistema del de en medio. Corto a propósito: es un recadero competente, no
#: un analista, y cuanto menos se le invite a opinar, menos opina.
SISTEMA_PEON = """\
Eres el ayudante de un analista de fútbol. Tu único trabajo es **traer datos** con
las herramientas que tienes: ni analizas, ni concluyes, ni das probabilidades. De
lo que escribas no se va a leer una palabra; de lo que traigas, todo.

Sigue el plan que te dan. Si al traer un dato se ve claramente que hace falta otro
para que ese primero signifique algo —el árbitro designado lleva a su reparto de
tarjetas, un equipo lleva a su rival de la última jornada—, tráelo también. Y
cuando ya tengas lo del plan y nada evidente que falte, para y di «listo».\
"""

#: Y lo que se le pide como turno de usuario, para que arranque.
INSTRUCCIONES_PEON = ("Trae lo que pide el plan. Cuando lo tengas todo, contesta "
                      "solo «listo».")

#: El empujón del cierre. El director vuelve a ver el expediente y los datos
#: recogidos, y ahora sí tiene que rematar.
INSTRUCCIONES_CIERRE = """\
Ya tienes delante el expediente y todo lo que se ha ido a buscar por tu plan.
Cierra el análisis ahora, con los apartados de siempre y terminando con tu bloque
```json de números.

Dos cosas: lo que se ha traído está tal cual lo devolvieron las herramientas, sin
que nadie lo haya interpretado por ti —así que júzgalo tú—, y si algo que pediste
no aparece es que no estaba: dilo y baja tu confianza, no rellenes el hueco.\
"""


def _primeras_lineas(texto: str, cuantas: int = 4) -> str:
    """Las primeras líneas de un expediente, para identificar el partido.

    Es el respaldo de `cabecera`: si a `analizar` no le dan una, se saca de aquí,
    porque el expediente empieza justo con el partido, la competición y la fecha.
    """
    return "\n".join(texto.splitlines()[:cuantas])


def extraer_numeros(texto: str) -> dict | None:
    """El último bloque JSON de una respuesta, si lo hay y si se puede leer.

    Se coge el **último** a propósito: un modelo que se explica a sí mismo
    escribe a veces un ejemplo antes del bueno. Y se intenta también sin las
    comillas del bloque, porque no todos los modelos las ponen.
    """
    import re

    candidatos = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
    if not candidatos:
        # Sin bloque: el último objeto que parezca JSON y empiece por «{"1x2»
        # o similar. Se prueba desde la última llave de apertura hacia atrás.
        candidatos = re.findall(r"(\{[^{}]*\"1x2\".*\})", texto, re.S)
    for crudo in reversed(candidatos):
        try:
            datos = json.loads(crudo)
        except ValueError:
            continue
        if isinstance(datos, dict):
            return datos
    return None


@dataclass
class Paso:
    """Una cosa que ha hecho el analista, para poder enseñarla."""

    tipo: str            # herramienta | resultado | respuesta | aviso
    nombre: str = ""
    argumentos: dict = field(default_factory=dict)
    texto: str = ""
    datos: Any = None
    caracteres: int = 0

    def as_dict(self) -> dict:
        salida = {"tipo": self.tipo}
        if self.nombre:
            salida["nombre"] = self.nombre
        if self.argumentos:
            salida["argumentos"] = self.argumentos
        if self.texto:
            salida["texto"] = self.texto
        if self.caracteres:
            salida["caracteres"] = self.caracteres
        return salida


@dataclass
class Analista:
    """Un modelo local con las herramientas de cancha en la mano."""

    sesion: Sesion | None = None
    modelo: str = MODELO_POR_DEFECTO
    url: str = URL_OLLAMA
    #: Clave para la nube de Ollama. Vacía = el de tu máquina, gratis y en
    #: local. Con clave, los datos del partido salen de tu ordenador.
    api_key: str = ""
    _contexto_tls: Any = field(default=SIN_MONTAR, repr=False)
    #: Certificados propios, para cuando algo abre tu HTTPS por el camino. Solo
    #: hace falta para la nube; el Ollama de casa va por HTTP. Ver
    #: :mod:`cancha.tls`.
    ca_bundle: str = ""
    sin_verificar: bool = False
    temperatura: float = 0.2
    #: Ventana del modelo, en tokens. Ojo: esto no tiene nada que ver con el
    #: contexto TLS, que es otra cosa con el mismo nombre en castellano.
    contexto: int = 16384
    max_vueltas: int = MAX_VUELTAS
    #: El modelo bueno, si quieres uno distinto para **abrir y cerrar**. Vacío =
    #: el mismo de principio a fin, que es lo de siempre. Ver
    #: :meth:`analizar` para qué hace cada uno y por qué ahorra tanto.
    modelo_director: str = ""
    #: Tope de tokens de entrada que se le deja gastar, sumando todas las
    #: vueltas. 0 = sin tope. `max_vueltas` cuenta turnos, y seis turnos sobre
    #: un expediente grande cuestan tres veces más que seis sobre uno pequeño:
    #: el número de vueltas no dice nada del gasto, y esto sí.
    techo_tokens: int = 0
    #: Con qué herramientas se le deja trabajar. Vacío = todas.
    solo_herramientas: tuple[str, ...] = ()
    #: Tope de caracteres por respuesta de herramienta. Más bajo que el de MCP:
    #: un modelo de 8B se atraganta con veinte mil caracteres de una tacada.
    max_chars: int = 6000
    instrucciones: str = INSTRUCCIONES
    #: Cómo se habla con Ollama. Se puede sustituir para probar sin Ollama.
    pedir: Callable[[str, dict | None], Any] = field(default=None, repr=False)
    #: Un cerrojo compartido con quien más use la memoria (el servidor web). Se
    #: coge **solo al ejecutar una herramienta**, nunca mientras el modelo
    #: piensa: antes el servidor lo sostenía durante toda la respuesta y la página
    #: entera se quedaba congelada los minutos que tardase un modelo de casa.
    cerrojo: Any = field(default=None, repr=False)
    _propia: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.pedir is None:
            self.pedir = lambda ruta, cuerpo=None: _pedir_http(
                f"{self.url.rstrip('/')}{ruta}", cuerpo, api_key=self.api_key,
                contexto=self._tls())
        # Con clave y sin decir a dónde, se supone la nube: nadie pone una
        # clave de pago para hablar con el Ollama de su propio portátil.
        if self.api_key and self.url == URL_OLLAMA:
            self.url = URL_NUBE
        if self.sesion is None:
            self.sesion = Sesion()
            self._propia = True

    # --- quién habla en cada momento ---

    @property
    def en_sandwich(self) -> bool:
        """¿Hay un modelo director distinto del que hace el trabajo de en medio?"""
        return bool(self.modelo_director and self.modelo_director != self.modelo)

    @property
    def modelo_de_cierre(self) -> str:
        """Quién escribe la conclusión, y quien saca los números."""
        return self.modelo_director or self.modelo

    def _sumar_tokens(self, salida: dict, respuesta: dict) -> None:
        """Va apuntando lo que cuesta, por modelo y en total.

        Sin esto no hay forma de saber qué vale una ejecución, y el coste es
        justo lo que estamos intentando bajar: un ahorro que no se mide es una
        opinión.
        """
        cuentas = salida.setdefault("tokens", {"prompt_eval_count": 0,
                                              "eval_count": 0, "por_modelo": {}})
        entrada = int(respuesta.get("prompt_eval_count") or 0)
        salidas = int(respuesta.get("eval_count") or 0)
        cuentas["prompt_eval_count"] += entrada
        cuentas["eval_count"] += salidas
        suyo = cuentas["por_modelo"].setdefault(
            respuesta.get("model") or self.modelo, {"entrada": 0, "salida": 0,
                                                    "llamadas": 0})
        suyo["entrada"] += entrada
        suyo["salida"] += salidas
        suyo["llamadas"] += 1

    def _tls(self):
        """El contexto TLS para hablar con la nube. ``None`` si no hay nada que decir."""
        if self._contexto_tls is SIN_MONTAR:
            from .tls import contexto as contexto_tls

            self._contexto_tls = contexto_tls(self.ca_bundle, self.sin_verificar)
        return self._contexto_tls

    def close(self) -> None:
        if self._propia and self.sesion is not None:
            self.sesion.close()

    # --- qué hay instalado ---

    def modelos(self) -> list[dict]:
        """Los modelos que tiene Ollama, con su tamaño."""
        datos = self.pedir("/api/tags", None) or {}
        salida = []
        for modelo in datos.get("models", []) or []:
            detalles = modelo.get("details") or {}
            salida.append({
                "nombre": modelo.get("name") or modelo.get("model"),
                "tamano": modelo.get("size"),
                "parametros": detalles.get("parameter_size"),
                "familia": detalles.get("family"),
            })
        return salida

    def comprobar(self) -> dict:
        """¿Está Ollama? ¿Está el modelo? ¿Sabe llamar herramientas?

        Lo importante es lo tercero: un modelo sin function calling da
        respuestas preciosas y completamente inventadas, porque no puede mirar
        ningún dato. Vale más saberlo antes.
        """
        try:
            instalados = self.modelos()
        except OllamaNoDisponible as exc:
            return {"disponible": False, "nota": str(exc),
                    "como": "Instala Ollama (ollama.com), arráncalo y trae un modelo:\n"
                            f"    ollama pull {MODELO_POR_DEFECTO}"}
        nombres = [m["nombre"] or "" for m in instalados]
        tiene = any(n == self.modelo or n.startswith(self.modelo + ":") for n in nombres)
        sugerido = None
        if not tiene:
            sugerido = next((n for n in nombres
                             if any(n.startswith(a) for a in ALTERNATIVOS)), None)
        return {
            "disponible": True,
            "url": self.url,
            "en_la_nube": bool(self.api_key),
            "modelo": self.modelo,
            "instalado": tiene,
            "modelos": instalados,
            "sugerido": sugerido,
            "nota": None if tiene else (
                f"'{self.modelo}' no está instalado. "
                + (f"Puedes usar '{sugerido}' con --modelo, o traer el recomendado: "
                   if sugerido else "Tráelo con: ")
                + f"ollama pull {MODELO_POR_DEFECTO}"),
            "aviso_herramientas": (
                "El modelo tiene que saber llamar funciones. Hermes, Qwen, Llama 3.1 "
                "y Mistral Nemo saben; los modelos pequeños de propósito general, no, "
                "y entonces contestan de memoria, que es la peor forma de fallar."
            ),
        }

    # --- el bucle ---

    def _esquemas(self) -> list[dict]:
        from .herramientas import esquemas

        # Un agente puede tener solo unas cuantas: es lo que de verdad hace a
        # dos agentes distintos —a qué datos llegan—, más que cómo escriben.
        permitidas = set(self.solo_herramientas or ())
        return [{"type": "function",
                 "function": {"name": e["name"], "description": e["description"],
                              "parameters": e["input_schema"]}}
                for e in esquemas()
                if not permitidas or e["name"] in permitidas]

    def _ejecutar(self, nombre: str, argumentos: Any) -> Any:
        from .herramientas import ejecutar

        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos)
            except ValueError:
                argumentos = {}
        if not isinstance(argumentos, dict):
            argumentos = {}
        # El cerrojo, solo aquí: es donde se toca la memoria. Mientras el modelo
        # piensa —que con uno local son minutos— el resto del programa sigue.
        with self.cerrojo or nullcontext():
            return ejecutar(nombre, argumentos, sesion=self.sesion,
                            max_chars=self.max_chars)

    def analizar(self, expediente: str, pregunta: str = "", instrucciones: str = "",
                 al_paso: Callable[[Paso], None] | None = None,
                 cabecera: str = "") -> dict:
        """Un agente trabajando: el expediente delante, y que pida lo que quiera.

        Es el bucle de herramientas de :meth:`preguntar` —ahí está lo de «voy a
        informarme de esto que veo necesario»— pero arrancando con el expediente
        ya montado y con una condición: termina dando sus números. Sin números no
        se puede comparar con nadie, y un análisis que no se puede comparar es
        una opinión.

        Con `modelo_director` puesto, el trabajo se reparte: ver
        :meth:`_en_sandwich`. `cabecera` son las tres líneas que identifican el
        partido, y solo hacen falta ahí.
        """
        sistema = (instrucciones or INSTRUCCIONES_DICTAMEN) + INSTRUCCIONES_NUMEROS
        peticion = pregunta.strip() or (
            "Analiza este partido: qué esperas que pase y por qué, qué te parece "
            "lo más aprovechable y qué te haría cambiar de opinión.")
        if self.en_sandwich:
            salida = self._en_sandwich(expediente, sistema, peticion, cabecera, al_paso)
        else:
            # El expediente va en el mensaje del usuario, y la pregunta detrás: el
            # bucle de `preguntar` añade la pregunta él solo, así que aquí solo se
            # le pasa el sistema y el documento como historial.
            salida = self.preguntar(
                peticion,
                historial=[{"role": "system", "content": sistema},
                           {"role": "user", "content": expediente}],
                al_paso=al_paso)
        numeros = extraer_numeros(salida.get("respuesta") or "")
        if numeros is None:
            numeros = self._pedir_los_numeros(salida, al_paso)
        salida["probabilidades"] = numeros
        salida["sin_numeros"] = numeros is None
        return salida

    def _en_sandwich(self, expediente: str, sistema: str, peticion: str,
                     cabecera: str = "", al_paso=None) -> dict:
        """El modelo bueno abre y cierra; el de casa hace los recados de en medio.

        El bucle normal reenvía **el historial entero** en cada vuelta, así que el
        expediente se paga otra vez en cada turno. Con seis vueltas eso son seis
        expedientes; aquí se pagan dos —el primero y el último—, y las vueltas de
        en medio, que son las de ir a buscar datos, las hace el modelo local
        gratis. En un expediente de doce mil tokens eso baja el gasto como dos
        tercios.

        Tres decisiones que no son detalles:

        **El medio aporta datos, no razonamiento.** Lo que el modelo local escribe
        se tira. Si se le devolviera al director, este lo leería con
        ``role: "assistant"`` —o sea, como algo que había dicho él— y los modelos
        se anclan a lo que creen que ya dijeron: habrías pagado por un modelo
        bueno para que defienda el razonamiento de uno peor. Al director vuelven
        los resultados de las herramientas y su propio plan, nada más.

        **El medio no recibe el expediente.** Su trabajo es traer lo que el plan
        pide, y para eso le basta saber qué partido es. Además evita el fallo
        silencioso: un modelo local con ventana de 16k al que le metes doce mil
        tokens y encima van creciendo los resultados hace que Ollama recorte por
        lo viejo —que es donde están las instrucciones— sin avisar a nadie.

        **Si el director no pide nada, no hay medio.** Cuando en su primera vuelta
        contesta sin llamar a ninguna herramienta, ya tiene lo que necesita: se
        devuelve eso y se ahorra todo lo demás.
        """
        avisar = al_paso or (lambda _p: None)
        herramientas = self._esquemas()
        salida: dict = {}

        # --- 1. Abre el director: qué ve y qué va a necesitar.
        avisar(Paso("aviso", texto=f"Abre {self.modelo_director}."))
        mensajes = [
            {"role": "system", "content": sistema + INSTRUCCIONES_DIRECTOR},
            {"role": "user", "content": f"{expediente}\n\n---\n\n{peticion}"},
        ]
        respuesta = self.pedir("/api/chat", {
            "model": self.modelo_director, "messages": mensajes, "stream": False,
            "tools": herramientas,
            "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
        }) or {}
        self._sumar_tokens(salida, respuesta)
        apertura = respuesta.get("message") or {}
        plan = (apertura.get("content") or "").strip()
        encargos = apertura.get("tool_calls") or []
        pasos = [Paso("respuesta", texto=plan)] if plan else []
        for paso in pasos:
            avisar(paso)

        if not encargos:
            # No ha pedido nada: con el expediente le bastaba, y esto ya es la
            # respuesta. Nos ahorramos el medio y el cierre enteros.
            return {**salida, "respuesta": plan, "pasos": [p.as_dict() for p in pasos],
                    "vueltas": 1, "modelo": self.modelo_director,
                    "historial": mensajes, "sandwich": True, "sin_recados": True}

        # --- 2. El medio: ejecuta lo pedido y sigue buscando si hace falta.
        recogido: list[dict] = []
        pasos += self._recados(encargos, recogido, avisar)
        if self.max_vueltas > 2:
            avisar(Paso("aviso", texto=f"Sigue buscando {self.modelo} "
                                       f"({self.max_vueltas - 2} vueltas)."))
            del_medio = Analista(
                sesion=self.sesion, modelo=self.modelo, url=self.url,
                temperatura=self.temperatura, contexto=self.contexto,
                max_vueltas=self.max_vueltas - 1, techo_tokens=self.techo_tokens,
                solo_herramientas=self.solo_herramientas, max_chars=self.max_chars,
                pedir=self.pedir, _contexto_tls=self._contexto_tls)
            suyo = del_medio.preguntar(
                INSTRUCCIONES_PEON,
                historial=[{"role": "system", "content": SISTEMA_PEON},
                           {"role": "user", "content":
                               (cabecera or _primeras_lineas(expediente))
                               + "\n\nEl plan del analista jefe:\n\n" + plan},
                           *[{"role": "tool", "name": d["nombre"],
                              "tool_name": d["nombre"], "content": d["texto"]}
                             for d in recogido]],
                al_paso=al_paso, modelo=self.modelo)
            # Del medio se guardan sus pasos —para poder ver qué buscó— y sus
            # resultados. Su prosa no: ver el docstring.
            for paso in suyo.get("pasos") or []:
                if paso.get("tipo") == "resultado":
                    recogido.append({"nombre": paso.get("nombre") or "",
                                     "texto": json.dumps(paso.get("datos"),
                                                         ensure_ascii=False,
                                                         default=str)})
                if paso.get("tipo") != "respuesta":
                    pasos.append(Paso(paso["tipo"], nombre=paso.get("nombre") or "",
                                      argumentos=paso.get("argumentos") or {},
                                      texto=paso.get("texto") or "",
                                      caracteres=paso.get("caracteres") or 0))
            for clave, valor in (suyo.get("tokens") or {}).get("por_modelo", {}).items():
                suyos = salida.setdefault("tokens", {}).setdefault(
                    "por_modelo", {}).setdefault(clave, {"entrada": 0, "salida": 0,
                                                         "llamadas": 0})
                for campo in ("entrada", "salida", "llamadas"):
                    suyos[campo] += valor[campo]

        # --- 3. Cierra el director, con todo delante y sin herramientas.
        avisar(Paso("aviso", texto=f"Cierra {self.modelo_director} con "
                                   f"{len(recogido)} datos recogidos."))
        cierre = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": f"{expediente}\n\n---\n\n{peticion}"},
            {"role": "assistant", "content": plan},
            *[{"role": "tool", "name": d["nombre"], "tool_name": d["nombre"],
               "content": d["texto"]} for d in recogido],
            {"role": "user", "content": INSTRUCCIONES_CIERRE},
        ]
        respuesta = self.pedir("/api/chat", {
            "model": self.modelo_director, "messages": cierre, "stream": False,
            "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
        }) or {}
        self._sumar_tokens(salida, respuesta)
        texto = ((respuesta.get("message") or {}).get("content") or "").strip()
        final = Paso("respuesta", texto=texto)
        pasos.append(final)
        avisar(final)
        return {**salida, "respuesta": texto, "pasos": [p.as_dict() for p in pasos],
                "vueltas": len([p for p in pasos if p.tipo == "herramienta"]) + 2,
                "modelo": self.modelo_director, "historial": cierre,
                "sandwich": True, "datos_recogidos": len(recogido)}

    def _recados(self, encargos: list[dict], recogido: list[dict],
                 avisar) -> list[Paso]:
        """Ejecuta las herramientas que ha pedido alguien. Sin modelo por medio.

        Cuando el plan no se ramifica, esto es todo lo que hace falta: no se
        necesita un modelo para ejecutar una lista, y el que no se usa no cuesta
        ni tokens ni segundos ni puede desviarse.
        """
        pasos = []
        for encargo in encargos:
            funcion = encargo.get("function") or {}
            nombre = funcion.get("name") or ""
            argumentos = funcion.get("arguments") or {}
            paso = Paso("herramienta", nombre=nombre,
                        argumentos=argumentos if isinstance(argumentos, dict) else {})
            pasos.append(paso)
            avisar(paso)
            resultado = self._ejecutar(nombre, argumentos)
            texto = json.dumps(resultado, ensure_ascii=False, default=str)
            hecho = Paso("resultado", nombre=nombre, datos=resultado,
                         caracteres=len(texto))
            pasos.append(hecho)
            avisar(hecho)
            recogido.append({"nombre": nombre, "texto": texto})
        return pasos

    def _pedir_los_numeros(self, salida: dict, al_paso=None) -> dict | None:
        """Una segunda oportunidad, y solo una.

        A veces el modelo escribe un análisis impecable y se deja el bloque. Se
        le pide otra vez, a secas. Si vuelve a fallar se guarda lo que ha
        escrito y se marca que no puntúa: insistir en bucle cuesta dinero y no
        convence a un modelo que no sabe hacerlo.

        Y se le manda **solo su propio análisis**, no el historial entero. Antes
        iba el expediente completo y todos los resultados de herramienta otra vez,
        que en un partido con seis vueltas son decenas de miles de tokens pagados
        para extraer seis números. Los números salen del análisis, no de los datos
        crudos: si no están en lo que ha escrito, tampoco los va a sacar de volver
        a leerse las tablas.
        """
        avisar = al_paso or (lambda _p: None)
        avisar(Paso("aviso", texto="No ha dado los números; se los pido otra vez."))
        escrito = (salida.get("respuesta") or "").strip()
        mensajes = [
            {"role": "system", "content": "Devuelves JSON y nada más."},
            {"role": "user", "content":
                "Este es un análisis de un partido de fútbol:\n\n"
                f"{escrito}\n\n---\n\nSaca de ahí las probabilidades y "
                "contesta **solo** con el bloque ```json, sin una palabra "
                f"alrededor:\n\n{ESQUEMA_NUMEROS}"},
        ]
        respuesta = self.pedir("/api/chat", {
            "model": self.modelo_de_cierre, "messages": mensajes, "stream": False,
            "options": {"temperature": 0, "num_ctx": self.contexto},
        }) or {}
        texto = ((respuesta.get("message") or {}).get("content") or "").strip()
        salida["reparado"] = True
        self._sumar_tokens(salida, respuesta)
        return extraer_numeros(texto)

    def dictaminar(self, expediente: str, pregunta: str = "",
                   instrucciones: str | None = None) -> dict:
        """Una sola llamada con el expediente entero delante. Sin herramientas.

        Es lo que tiene sentido con un modelo grande: no que sepa qué pedir,
        sino que vea todo a la vez y ate cabos. Y al no dar vueltas, se paga
        una sola vez.
        """
        sistema = instrucciones or INSTRUCCIONES_DICTAMEN
        peticion = pregunta.strip() or (
            "Analiza este partido: qué esperas que pase y por qué, qué te parece "
            "lo más aprovechable y qué te haría cambiar de opinión.")
        mensajes = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": f"{expediente}\n\n---\n\n{peticion}"},
        ]
        respuesta = self.pedir("/api/chat", {
            "model": self.modelo,
            "messages": mensajes,
            "stream": False,
            "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
        }) or {}
        texto = ((respuesta.get("message") or {}).get("content") or "").strip()
        return {
            "respuesta": texto,
            "modelo": self.modelo,
            "url": self.url,
            "en_la_nube": bool(self.api_key),
            "caracteres_enviados": len(expediente) + len(sistema) + len(peticion),
            # Lo que cuenta Ollama, cuando lo cuenta: es lo que se paga.
            "tokens": {k: respuesta[k] for k in
                       ("prompt_eval_count", "eval_count") if k in respuesta},
        }

    def preguntar(self, pregunta: str, historial: list[dict] | None = None,
                  al_paso: Callable[[Paso], None] | None = None,
                  modelo: str = "") -> dict:
        """Contesta usando las herramientas que haga falta.

        Devuelve la respuesta, los pasos que ha dado, lo que ha costado en
        tokens y el historial de mensajes para poder seguir la conversación en
        la siguiente pregunta.

        ``modelo`` deja pedir explícitamente con otro modelo del configurado, que
        es lo que usa :meth:`analizar` para repartir las vueltas entre el director
        y el de en medio.
        """
        avisar = al_paso or (lambda _p: None)
        mensajes: list[dict] = list(historial or [])
        if not mensajes or mensajes[0].get("role") != "system":
            mensajes.insert(0, {"role": "system", "content": self.instrucciones})
        mensajes.append({"role": "user", "content": pregunta})

        pasos: list[Paso] = []
        herramientas = self._esquemas()
        salida: dict = {}
        for vuelta in range(self.max_vueltas):
            cuerpo = {
                "model": modelo or self.modelo,
                "messages": mensajes,
                "stream": False,
                "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
            }
            # En la última vuelta se le quitan las herramientas: así no se queda
            # pidiendo datos para siempre y tiene que contestar con lo que tiene.
            if vuelta < self.max_vueltas - 1:
                cuerpo["tools"] = herramientas

            respuesta = self.pedir("/api/chat", cuerpo) or {}
            self._sumar_tokens(salida, respuesta)
            mensaje = respuesta.get("message") or {}
            llamadas = mensaje.get("tool_calls") or []
            mensajes.append({k: v for k, v in mensaje.items() if k in
                             ("role", "content", "tool_calls")} or {"role": "assistant",
                                                                    "content": ""})
            if not llamadas:
                texto = (mensaje.get("content") or "").strip()
                paso = Paso("respuesta", texto=texto)
                pasos.append(paso)
                avisar(paso)
                return {
                    **salida,
                    "respuesta": texto,
                    "pasos": [p.as_dict() for p in pasos],
                    "vueltas": vuelta + 1,
                    "modelo": modelo or self.modelo,
                    "historial": mensajes,
                    "peticiones": (self.sesion.cliente.stats.as_dict()
                                   if self.sesion and self.sesion.cliente else {}),
                }

            for llamada in llamadas:
                funcion = llamada.get("function") or {}
                nombre = funcion.get("name") or ""
                argumentos = funcion.get("arguments") or {}
                paso = Paso("herramienta", nombre=nombre,
                            argumentos=argumentos if isinstance(argumentos, dict) else {})
                pasos.append(paso)
                avisar(paso)

                resultado = self._ejecutar(nombre, argumentos)
                texto = json.dumps(resultado, ensure_ascii=False, default=str)
                hecho = Paso("resultado", nombre=nombre, datos=resultado,
                             caracteres=len(texto))
                pasos.append(hecho)
                avisar(hecho)
                mensajes.append({"role": "tool", "name": nombre, "tool_name": nombre,
                                 "content": texto})

            # El techo de tokens, comprobado **después** de una vuelta completa y
            # no en medio: cortar entre la petición de una herramienta y su
            # resultado dejaría el historial en un estado que el modelo no
            # entiende. Vale para las dos cosas que se quieren evitar: una
            # factura que se dispara y un modelo local que se atasca en bucle.
            gastado = (salida.get("tokens") or {}).get("prompt_eval_count", 0)
            if self.techo_tokens and gastado >= self.techo_tokens:
                aviso = Paso("aviso", texto=(
                    f"Se ha quedado sin presupuesto: {gastado} tokens de entrada, "
                    f"y el techo está en {self.techo_tokens}."))
                pasos.append(aviso)
                avisar(aviso)
                ultimo = next((m.get("content") for m in reversed(mensajes)
                               if m.get("role") == "assistant" and m.get("content")), "")
                return {**salida,
                        "respuesta": ultimo or "Me he quedado sin presupuesto.",
                        "pasos": [p.as_dict() for p in pasos], "vueltas": vuelta + 1,
                        "modelo": modelo or self.modelo, "historial": mensajes,
                        "sin_presupuesto": True}

        aviso = Paso("aviso", texto=f"Se ha quedado sin vueltas ({self.max_vueltas}).")
        pasos.append(aviso)
        avisar(aviso)
        ultimo = next((m.get("content") for m in reversed(mensajes)
                       if m.get("role") == "assistant" and m.get("content")), "")
        return {**salida, "respuesta": ultimo or "No he llegado a una conclusión.",
                "pasos": [p.as_dict() for p in pasos], "vueltas": self.max_vueltas,
                "modelo": modelo or self.modelo, "historial": mensajes,
                "agotado": True}

    def conversar(self, preguntas: Iterator[str]) -> Iterator[dict]:
        """Varias preguntas seguidas, guardando el hilo entre ellas."""
        historial: list[dict] | None = None
        for pregunta in preguntas:
            salida = self.preguntar(pregunta, historial=historial)
            historial = salida["historial"]
            yield salida


def texto_de_paso(paso: dict) -> str:
    """Un paso en una línea, para el terminal."""
    if paso["tipo"] == "herramienta":
        argumentos = ", ".join(f"{k}={v}" for k, v in (paso.get("argumentos") or {}).items())
        return f"  → {paso['nombre']}({argumentos})"
    if paso["tipo"] == "resultado":
        return f"     {paso.get('caracteres', 0)} caracteres"
    if paso["tipo"] == "aviso":
        return f"  ⚠ {paso.get('texto', '')}"
    return ""


__all__ = ["ALTERNATIVOS", "INSTRUCCIONES", "INSTRUCCIONES_DICTAMEN",
           "MODELO_POR_DEFECTO", "URL_NUBE", "URL_OLLAMA", "Analista",
           "OllamaNoDisponible", "Paso", "texto_de_paso"]
