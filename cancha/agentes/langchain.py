"""Las herramientas de cancha como herramientas de LangChain.

LangChain 1.x trae su propio constructor de agentes (``create_agent``) y su
cliente de Ollama (``ChatOllama``). Lo que falta es el puente: convertir los
esquemas de :mod:`cancha.herramientas` en ``StructuredTool`` y atarlos a una
:class:`~cancha.sesion.Sesion`, para que todo el agente comparta el trabajo ya
hecho en vez de pedir el mismo partido ocho veces.

    from cancha.agentes.langchain import agente, herramientas

    herramientas()                       # 40+ StructuredTool, para tu agente
    agente(modelo="hermes3").invoke({"messages": [("user", "¿qué hay hoy?")]})

No hace falta para usar el framework con una IA —:mod:`cancha.analista` no
depende de nada— pero si ya tienes LangChain, esto encaja sin fricción.
"""

from __future__ import annotations

from typing import Any

from ..errors import SofascoreError
from ..sesion import Sesion

#: Lo que hay que instalar si falta.
INSTALAR = 'pip install "cancha[langchain]"'


class LangChainNoDisponible(SofascoreError):
    """LangChain no está instalado."""


def _importar(modulo: str, que: str):
    try:
        importado = __import__(modulo, fromlist=[que])
    except ImportError as exc:
        raise LangChainNoDisponible(
            f"Hace falta {modulo} para esto. Instálalo con: {INSTALAR}"
        ) from exc
    return getattr(importado, que)


def disponible() -> dict:
    """¿Está LangChain, y con qué versión?"""
    import importlib.util

    salida: dict[str, Any] = {"instalar": INSTALAR}
    for paquete in ("langchain", "langchain_core", "langchain_ollama"):
        presente = importlib.util.find_spec(paquete) is not None
        version = None
        if presente:
            try:
                from importlib.metadata import version as _version

                version = _version(paquete.replace("_", "-"))
            except Exception:  # noqa: BLE001 - la versión es cosmética
                version = "?"
        salida[paquete] = {"instalado": presente, "version": version}
    salida["listo"] = all(salida[p]["instalado"]
                          for p in ("langchain", "langchain_core", "langchain_ollama"))
    return salida


def herramientas(sesion: Sesion | None = None, solo: list[str] | None = None,
                 max_chars: int = 6000) -> list:
    """Las herramientas de cancha, envueltas para LangChain.

    Comparten una sola :class:`~cancha.sesion.Sesion`, que es lo que hace que
    ocho preguntas sobre el mismo partido cuesten un partido y no ocho.
    """
    StructuredTool = _importar("langchain_core.tools", "StructuredTool")
    from ..herramientas import TOOLS, ejecutar

    sesion = sesion or Sesion()
    elegidas = [t for n, t in TOOLS.items() if not solo or n in solo]

    def envolver(nombre: str):
        def correr(**argumentos: Any) -> str:
            import json

            resultado = ejecutar(nombre, argumentos, sesion=sesion, max_chars=max_chars)
            return json.dumps(resultado, ensure_ascii=False, default=str)

        correr.__name__ = nombre
        return correr

    return [
        StructuredTool.from_function(
            func=envolver(t.name), name=t.name,
            description=t.description, args_schema=t.parameters,
        )
        for t in elegidas
    ]


def modelo_ollama(modelo: str | None = None, url: str | None = None, **opciones):
    """Un ``ChatOllama`` apuntando a tu Ollama, con valores sensatos."""
    ChatOllama = _importar("langchain_ollama", "ChatOllama")
    from ..analista import MODELO_POR_DEFECTO, URL_OLLAMA

    return ChatOllama(
        model=modelo or MODELO_POR_DEFECTO,
        base_url=url or URL_OLLAMA,
        temperature=opciones.pop("temperature", 0.2),
        num_ctx=opciones.pop("num_ctx", 16384),
        **opciones,
    )


def agente(modelo: str | Any = None, sesion: Sesion | None = None,
           url: str | None = None, instrucciones: str | None = None,
           solo: list[str] | None = None, **opciones):
    """Un agente de LangChain con el fútbol dentro.

    ``modelo`` puede ser el nombre de un modelo de Ollama o un chat model ya
    construido, por si quieres usar otro proveedor: las herramientas son las
    mismas.
    """
    create_agent = _importar("langchain.agents", "create_agent")
    from ..analista import INSTRUCCIONES

    chat = modelo if (modelo is not None and not isinstance(modelo, str)) \
        else modelo_ollama(modelo, url)
    return create_agent(
        chat,
        tools=herramientas(sesion, solo=solo),
        system_prompt=instrucciones or INSTRUCCIONES,
        **opciones,
    )


__all__ = ["herramientas", "agente", "modelo_ollama", "disponible",
           "LangChainNoDisponible", "INSTALAR"]
