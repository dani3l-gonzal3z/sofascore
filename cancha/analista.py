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

#: Dónde escucha Ollama si no le han dicho otra cosa.
URL_OLLAMA = "http://localhost:11434"
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
4. **Empieza por lo barato.** `briefing_del_dia` o `resumen_partido` primero;
   el detalle después. Si la memoria está vacía, dilo y sugiere `cancha
   barrido` en vez de inventar.
5. **Contesta en castellano, corto y concreto.** Primero la respuesta, luego
   en qué te apoyas. Sin listas de cien números: los tres que deciden.

Cuando termines de usar herramientas, escribe la respuesta final directamente.\
"""


class OllamaNoDisponible(SofascoreError):
    """Ollama no contesta, o el modelo que se pide no está instalado."""


def _pedir_http(url: str, cuerpo: dict | None = None, timeout: float = 300.0,
                flujo: bool = False) -> Any:
    """Un POST (o GET) a Ollama. Es localhost: urllib sobra y no arrastra nada."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method="POST" if datos is not None else "GET",
        headers={"Content-Type": "application/json"})
    try:
        respuesta = urllib.request.urlopen(peticion, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:300]
        raise OllamaNoDisponible(f"Ollama ha contestado {exc.code}: {detalle}") from exc
    except OSError as exc:
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
    temperatura: float = 0.2
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
                f"{self.url.rstrip('/')}{ruta}", cuerpo)
        if self.sesion is None:
            self.sesion = Sesion()
            self._propia = True

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


__all__ = ["Analista", "Paso", "OllamaNoDisponible", "texto_de_paso",
           "INSTRUCCIONES", "URL_OLLAMA", "MODELO_POR_DEFECTO", "ALTERNATIVOS"]
