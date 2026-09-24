"""El armazón de las herramientas: registro, recorte y ejecución.

Lo que sabe cada herramienta de fútbol vive en los otros módulos de este
paquete. Aquí solo está la mecánica: cómo se declara una, cómo se recorta su
respuesta para que quepa en el contexto de un modelo y cómo se ejecuta sin que
un fallo se convierta en una excepción que el modelo no pueda leer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..client import SofascoreClient
from ..errors import SofascoreError
from ..sesion import Sesion

#: Tope de caracteres por respuesta. Generoso para un modelo de 128k, pero
#: suficiente para que un mapa de tiros entero no se lleve el contexto por
#: delante.
MAX_CHARS = 20_000


@dataclass(frozen=True)
class Tool:
    """Una herramienta que la IA puede llamar."""

    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def schema(self) -> dict:
        """La definición en el formato que esperan los modelos con function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


TOOLS: dict[str, Tool] = {}


def herramienta(nombre: str, descripcion: str, propiedades: dict,
                obligatorios: list[str] | None = None):
    """Registra una función como herramienta."""
    def decorador(fn):
        TOOLS[nombre] = Tool(
            name=nombre,
            description=descripcion,
            parameters={
                "type": "object",
                "properties": propiedades,
                "required": obligatorios or [],
            },
            handler=fn,
        )
        return fn
    return decorador


# --------------------------------------------------------------------- recorte

def recortar(datos: Any, max_chars: int = MAX_CHARS) -> Any:
    """Deja los datos por debajo del tope, diciendo qué se ha quitado.

    Con una lista se van soltando elementos del final hasta que cabe, y se
    añade una nota con cuántos faltan: el modelo sabe entonces que hay más y
    puede pedir el resto afinando la consulta.
    """
    texto = json.dumps(datos, ensure_ascii=False, default=str)
    if len(texto) <= max_chars:
        return datos

    if isinstance(datos, list):
        cabe = datos
        while cabe and len(json.dumps(cabe, ensure_ascii=False, default=str)) > max_chars - 200:
            cabe = cabe[: int(len(cabe) * 0.8)] if len(cabe) > 10 else cabe[:-1]
        return {
            "elementos": cabe,
            "recortado": True,
            "nota": f"Se enseñan {len(cabe)} de {len(datos)}. "
                    "Afina la consulta (por equipo, por jugador, por periodo) para ver el resto.",
        }

    if isinstance(datos, dict):
        salida: dict[str, Any] = {}
        fuera = []
        for clave, valor in datos.items():
            trozo = json.dumps({clave: valor}, ensure_ascii=False, default=str)
            if len(json.dumps(salida, ensure_ascii=False, default=str)) + len(trozo) < max_chars:
                salida[clave] = valor
            else:
                fuera.append(clave)
        if fuera:
            salida["_recortado"] = f"Faltan estas claves por tamaño: {', '.join(fuera)}."
        return salida

    return texto[:max_chars] + " …[recortado]"


# ------------------------------------------------------------------- ejecución

def esquemas() -> list[dict]:
    """Las definiciones de todas las herramientas, para dárselas al modelo."""
    return [t.schema() for t in TOOLS.values()]


def ejecutar(
    nombre: str,
    argumentos: dict | None = None,
    cliente: SofascoreClient | None = None,
    max_chars: int = MAX_CHARS,
    sesion: Sesion | None = None,
) -> dict:
    """Ejecuta una herramienta y devuelve su resultado, ya recortado.

    Pásale una :class:`~cancha.sesion.Sesion` si vas a hacer varias preguntas
    sobre el mismo partido: entonces cada sección se pide una sola vez. Sin
    ella se monta una de usar y tirar, que sirve para una llamada suelta.

    Nunca lanza: un fallo se devuelve como ``{"error": ...}`` para que el modelo
    pueda leerlo, entenderlo y reintentar de otra forma.
    """
    if nombre not in TOOLS:
        return {"error": f"No existe la herramienta '{nombre}'.",
                "disponibles": sorted(TOOLS)}
    propia = sesion is None
    sesion = sesion or Sesion(cliente=cliente)
    try:
        resultado = TOOLS[nombre].handler(sesion, **(argumentos or {}))
        return recortar(resultado, max_chars)
    except SofascoreError as exc:
        return {"error": str(exc), "herramienta": nombre}
    except TypeError as exc:
        return {"error": f"Argumentos incorrectos para '{nombre}': {exc}",
                "esperados": TOOLS[nombre].parameters}
    finally:
        if propia:
            sesion.close()


__all__ = ["TOOLS", "Tool", "esquemas", "ejecutar", "recortar", "MAX_CHARS"]
