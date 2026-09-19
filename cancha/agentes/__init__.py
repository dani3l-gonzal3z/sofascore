"""Enganches a los marcos de agentes que ya existen.

El framework no necesita ninguno: :mod:`cancha.analista` habla con Ollama
directamente y :mod:`cancha.mcp` sirve las herramientas por MCP. Esto es para
cuando ya tienes montado un agente en **LangChain** y quieres meterle el
fútbol dentro sin reescribir nada.

    from cancha.agentes import langchain as lc

    agente = lc.agente(modelo="hermes3")
    agente.invoke({"messages": [("user", "¿cómo llega el Girona?")]})

Es un extra opcional: ``pip install "cancha[langchain]"``. Si no está
instalado, el import lo dice con lo que hay que escribir.
"""

from . import langchain

__all__ = ["langchain"]
