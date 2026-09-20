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
    #: Tope de caracteres por respuesta de herramienta. Más bajo que el de MCP:
    #: un modelo de 8B se atraganta con veinte mil caracteres de una tacada.
    max_chars: int = 6000
    instrucciones: str = INSTRUCCIONES
    #: Cómo se habla con Ollama. Se puede sustituir para probar sin Ollama.
    pedir: Callable[[str, dict | None], Any] = field(default=None, repr=False)
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

        return [{"type": "function",
                 "function": {"name": e["name"], "description": e["description"],
                              "parameters": e["input_schema"]}}
                for e in esquemas()]

    def _ejecutar(self, nombre: str, argumentos: Any) -> Any:
        from .herramientas import ejecutar

        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos)
            except ValueError:
                argumentos = {}
        if not isinstance(argumentos, dict):
            argumentos = {}
        return ejecutar(nombre, argumentos, sesion=self.sesion, max_chars=self.max_chars)

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
                  al_paso: Callable[[Paso], None] | None = None) -> dict:
        """Contesta usando las herramientas que haga falta.

        Devuelve la respuesta, los pasos que ha dado y el historial de mensajes
        para poder seguir la conversación en la siguiente pregunta.
        """
        avisar = al_paso or (lambda _p: None)
        mensajes: list[dict] = list(historial or [])
        if not mensajes or mensajes[0].get("role") != "system":
            mensajes.insert(0, {"role": "system", "content": self.instrucciones})
        mensajes.append({"role": "user", "content": pregunta})

        pasos: list[Paso] = []
        herramientas = self._esquemas()
        for vuelta in range(self.max_vueltas):
            cuerpo = {
                "model": self.modelo,
                "messages": mensajes,
                "stream": False,
                "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
            }
            # En la última vuelta se le quitan las herramientas: así no se queda
            # pidiendo datos para siempre y tiene que contestar con lo que tiene.
            if vuelta < self.max_vueltas - 1:
                cuerpo["tools"] = herramientas

            respuesta = self.pedir("/api/chat", cuerpo) or {}
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
                    "respuesta": texto,
                    "pasos": [p.as_dict() for p in pasos],
                    "vueltas": vuelta + 1,
                    "modelo": self.modelo,
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

        aviso = Paso("aviso", texto=f"Se ha quedado sin vueltas ({self.max_vueltas}).")
        pasos.append(aviso)
        avisar(aviso)
        ultimo = next((m.get("content") for m in reversed(mensajes)
                       if m.get("role") == "assistant" and m.get("content")), "")
        return {"respuesta": ultimo or "No he llegado a una conclusión.",
                "pasos": [p.as_dict() for p in pasos], "vueltas": self.max_vueltas,
                "modelo": self.modelo, "historial": mensajes, "agotado": True}

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
