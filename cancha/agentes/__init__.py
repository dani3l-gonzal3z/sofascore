"""Agentes analistas: varios estilos mirando el mismo partido, y una tabla.

Hasta aquí había **un** analista, con unas instrucciones iguales para todo el
mundo, que contestaba en prosa. Se leía, se creía o no, y ahí moría.

Un agente es lo mismo pero con nombre y con carácter: sus instrucciones, su
modelo, su presupuesto de vueltas y —lo que de verdad los diferencia— **a qué
datos llega**. Uno que solo mire árbitros y tarjetas no escribe distinto que
otro que lo mire todo: piensa distinto, porque no sabe lo mismo.

Y hay una condición que lo cambia todo: **un agente está obligado a terminar
dando probabilidades**. Con eso, sus predicciones entran en el registro con su
nombre al lado y se miden igual que las del cálculo y las del mercado, que
concursan como dos más. Entonces ya no hace falta opinar sobre quién analiza
mejor: se mira la tabla.

    from cancha.agentes import cargar, correr

    agente = cargar()["el-esceptico"]
    correr(almacen, cliente, agente, "Girona vs Osasuna")

Lo que un agente **no** es: un oráculo. Que uno vaya primero en la tabla con
sesenta predicciones quiere decir que ha ido mejor en sesenta predicciones.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUTA_POR_DEFECTO = "datos/agentes.json"

#: Cuántas vueltas de herramientas se le dejan gastar como mucho. Cada vuelta es
#: una llamada al modelo, así que esto es el presupuesto.
VUELTAS_POR_DEFECTO = 6
#: Y el tope duro: por encima de esto no se deja configurar, porque un agente en
#: bucle con una clave de la nube puesta es una factura.
VUELTAS_MAXIMAS = 20


class AgenteRaro(ValueError):
    """Esa definición de agente no vale, y se dice por qué."""


@dataclass
class Agente:
    """Cómo analiza uno. Todo lo que se puede programar de él sin tocar código."""

    clave: str
    nombre: str = ""
    #: Su forma de mirar un partido. Es lo que va de sistema, delante de todo.
    instrucciones: str = ""
    #: Vacío = el modelo de los ajustes. Puede ser uno de la nube.
    modelo: str = ""
    #: El modelo bueno, si quieres que **abra y cierre** él y que el de casa haga
    #: las vueltas de en medio. Vacío = uno solo de principio a fin. Baja el gasto
    #: del caro como dos tercios, pero no es gratis en calidad: ver docs/agentes.md.
    modelo_director: str = ""
    #: Tope de tokens de entrada que se le deja gastar en total. 0 = sin tope.
    techo_tokens: int = 0
    vueltas: int = VUELTAS_POR_DEFECTO
    #: Con cuánto detalle arranca su expediente: ``todo``, ``tabla`` o ``no``.
    crudo: str = "tabla"
    #: A qué herramientas llega. Vacío = a todas.
    herramientas: tuple[str, ...] = ()
    temperatura: float = 0.2
    activo: bool = True

    def as_dict(self) -> dict:
        return {"nombre": self.nombre or self.clave,
                "instrucciones": self.instrucciones, "modelo": self.modelo,
                "modelo_director": self.modelo_director,
                "techo_tokens": self.techo_tokens,
                "vueltas": self.vueltas, "crudo": self.crudo,
                "herramientas": list(self.herramientas),
                "temperatura": self.temperatura, "activo": self.activo}


#: Tres para empezar, que son tres formas distintas de mirar un partido y no
#: tres maneras de decir lo mismo. Están escritos para que se noten en la tabla:
#: si dos agentes aciertan lo mismo, es que eran el mismo agente.
POR_DEFECTO: dict[str, dict] = {
    "el-esceptico": {
        "nombre": "El escéptico",
        "instrucciones": (
            "Tu sesgo es la duda. Antes de afirmar cualquier cosa, mira con "
            "cuánta muestra está medida: por debajo de seis partidos no es un "
            "rasgo, es una racha. Desconfía de los patrones llamativos y de las "
            "rachas cortas, y cuando el mercado y el cálculo se separen, empieza "
            "suponiendo que el que se equivoca es el cálculo. Tus probabilidades "
            "deben quedarse cerca del mercado salvo que tengas un motivo medido "
            "para separarte, y ese motivo tiene que estar escrito."),
        "crudo": "tabla",
        "vueltas": 4,
    },
    "el-del-crudo": {
        "nombre": "El del crudo",
        "instrucciones": (
            "No te fíes de las medias: te las han calculado, pero esconden lo "
            "que pasó en cada partido. Empieza siempre por los datos en crudo "
            "—partido a partido— y busca la tendencia: si lo malo está todo al "
            "principio, si hay un partido rarísimo que se come la media, si el "
            "equipo ha cambiado de cara hace tres jornadas. Cuando una media y "
            "su crudo no cuenten la misma historia, gana el crudo, y dilo."),
        "crudo": "todo",
        "vueltas": 6,
    },
    "el-del-arbitro": {
        "nombre": "El del árbitro",
        "instrucciones": (
            "Mira el partido por donde casi nadie lo mira: quién pita, cómo "
            "reparte, y qué equipos se meten en líos. Las tarjetas y las faltas "
            "son tu terreno; el marcador te importa menos y lo dices. Si no "
            "tienes árbitro designado, dilo claramente y baja tu confianza en "
            "vez de inventarte un perfil."),
        "crudo": "tabla",
        "vueltas": 5,
        "herramientas": ["perfil_de_arbitro", "pronostico_partido",
                         "estilo_de_equipo", "casi_seguro"],
    },
}


# ------------------------------------------------------------------ leerlos

def ruta(dada: str | Path | None = None) -> Path:
    return Path(dada or os.environ.get("CANCHA_AGENTES") or RUTA_POR_DEFECTO)


def cargar(dada: str | Path | None = None) -> dict[str, Agente]:
    """Los agentes guardados. La primera vez, los de ejemplo.

    Un fichero roto no puede dejarte sin programa ni sin los demás agentes: el
    que no se entienda se salta, y los otros siguen.
    """
    destino = ruta(dada)
    if not destino.is_file():
        return {clave: construir(clave, datos)
                for clave, datos in deepcopy(POR_DEFECTO).items()}
    try:
        guardado = json.loads(destino.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(guardado, dict):
        return {}
    salida = {}
    for clave, datos in guardado.items():
        if isinstance(datos, dict):
            try:
                salida[str(clave)] = construir(str(clave), datos)
            except AgenteRaro:
                continue
    return salida


def construir(clave: str, datos: dict) -> Agente:
    """Un `Agente` desde lo que se haya guardado o llegado por una petición.

    Lo que no venga, o no valga, se queda en su valor por defecto: un campo raro
    no puede dejar sin agente a nadie. Lo que **sí** se rechaza se rechaza antes,
    en `validar`, y con una frase.
    """
    return Agente(
        clave=clave,
        nombre=str(datos.get("nombre") or clave),
        instrucciones=str(datos.get("instrucciones") or ""),
        modelo=str(datos.get("modelo") or ""),
        modelo_director=str(datos.get("modelo_director") or ""),
        techo_tokens=max(0, _entero_libre(datos.get("techo_tokens"), 0)),
        vueltas=_entero(datos.get("vueltas"), VUELTAS_POR_DEFECTO),
        crudo=(datos.get("crudo") if datos.get("crudo") in ("todo", "tabla", "no")
               else "tabla"),
        herramientas=tuple(str(x) for x in (datos.get("herramientas") or [])),
        temperatura=_numero(datos.get("temperatura"), 0.2),
        activo=bool(datos.get("activo", True)),
    )


def _entero(valor: Any, si_no: int) -> int:
    try:
        return max(1, min(VUELTAS_MAXIMAS, int(valor)))
    except (TypeError, ValueError):
        return si_no


def _entero_libre(valor: Any, si_no: int) -> int:
    """Un entero sin el tope de las vueltas: el techo de tokens es de otro orden."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return si_no


def _numero(valor: Any, si_no: float) -> float:
    try:
        return max(0.0, min(2.0, float(valor)))
    except (TypeError, ValueError):
        return si_no


#: Cómo tiene que ser la clave de un agente. Sin tildes y sin mayúsculas por la
#: misma razón que el autor del cálculo no las lleva: esto viaja por el terminal,
#: por una petición y por SQLite, que compara byte a byte.
FORMA_DE_CLAVE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")

#: Nombres que ya son de alguien: los dos concursantes fijos del registro.
CLAVES_RESERVADAS = ("calculo", "mercado")


def huella(agente: Agente) -> str:
    """Ocho caracteres que resumen **cómo piensa** este agente ahora mismo.

    Van a `predicciones.version`, y sirven para una cosa concreta: el día que le
    reescribas las instrucciones deja de ser el mismo analista, y mezclar en un
    mismo balance lo que acertó antes y lo que acierta después no mide a nadie.
    Entra lo que cambia su respuesta; no entran el nombre ni las notas.
    """
    materia = json.dumps([agente.instrucciones, agente.modelo, agente.vueltas,
                          agente.crudo, sorted(agente.herramientas),
                          round(agente.temperatura, 3), agente.modelo_director,
                          agente.techo_tokens],
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(materia.encode("utf-8")).hexdigest()[:8]


def guardar(agentes: dict[str, Agente] | dict[str, dict],
            dada: str | Path | None = None) -> Path:
    """Escribe los agentes. Solo para ti, como los ajustes: llevan tu forma de
    pensar dentro y puede que el nombre de un modelo de pago."""
    destino = ruta(dada)
    destino.parent.mkdir(parents=True, exist_ok=True)
    limpio = {clave: (valor.as_dict() if isinstance(valor, Agente) else valor)
              for clave, valor in agentes.items()}
    destino.write_text(json.dumps(limpio, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    with __import__("contextlib").suppress(OSError):
        destino.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return destino


def validar(clave: str, datos: dict) -> list[str]:
    """Qué hay mal en la definición de un agente, en palabras."""
    problemas = []
    if not str(clave or "").strip():
        problemas.append("Un agente necesita un nombre corto para llamarlo.")
    elif not FORMA_DE_CLAVE.match(str(clave)):
        problemas.append(
            f"«{clave}» no vale como nombre corto: minúsculas, números y guiones, "
            "de dos a treinta y uno, y sin tildes. Es un nombre que vas a escribir "
            "en el terminal y que va a viajar hasta la base de datos.")
    elif str(clave) in CLAVES_RESERVADAS:
        problemas.append(
            f"«{clave}» ya es de uno de los dos concursantes fijos —el cálculo y "
            "el mercado—, y son justo contra los que se te mide. Ponle otro.")
    if not str(datos.get("instrucciones") or "").strip():
        problemas.append("Sin instrucciones, un agente es el analista de siempre "
                         "con otro nombre: escribe cómo quieres que mire un partido.")
    if datos.get("crudo") not in (None, "todo", "tabla", "no"):
        problemas.append("El detalle en crudo es «todo», «tabla» o «no».")
    try:
        vueltas = int(datos.get("vueltas", VUELTAS_POR_DEFECTO))
        if not 1 <= vueltas <= VUELTAS_MAXIMAS:
            problemas.append(f"Las vueltas van de 1 a {VUELTAS_MAXIMAS}: cada una "
                             "es una llamada al modelo, y las de la nube se pagan.")
    except (TypeError, ValueError):
        problemas.append("Las vueltas son un número.")
    sueltas = _desconocidas(datos.get("herramientas") or [])
    if sueltas:
        problemas.append("No conozco estas herramientas: " + ", ".join(sueltas))
    return problemas


def _desconocidas(nombres: list) -> list[str]:
    from ..herramientas import esquemas

    conocidas = {e["name"] for e in esquemas()}
    return [str(n) for n in nombres if str(n) not in conocidas]


# ------------------------------------------------------------------ correrlos

def correr(almacen, cliente, agente: Agente, partido: Any,
           modelo_por_defecto: str = "", api_key: str = "", url: str = "",
           ca_bundle: str = "", sin_verificar: bool = False,
           al_paso=None, guardar_todo: bool = True) -> dict:
    """Pone a un agente a analizar un partido, y apunta lo que diga.

    Devuelve su análisis, sus pasos —qué datos pidió por su cuenta— y sus
    probabilidades. Si no ha dado números se guarda igual lo que ha escrito,
    marcado como que no puntúa: se lee, pero no entra en la clasificación. Que
    eso quede contado también es a propósito: un agente que falla el cierre
    cuatro veces de cada diez es un agente malo, y esconderlo sería adornarlo.
    """
    from ..analista import MODELO_POR_DEFECTO, Analista
    from ..expediente import a_texto, cabecera, expediente
    from ..registro import anotar

    empezo = time.monotonic()
    datos = expediente(almacen, partido, cliente=cliente, crudo=agente.crudo)
    if not datos.get("disponible"):
        return {"disponible": False, "agente": agente.clave,
                "nota": datos.get("nota", "No hay expediente de ese partido.")}

    documento = a_texto(datos)
    analista = Analista(
        sesion=_sesion_de(almacen, cliente),
        modelo=agente.modelo or modelo_por_defecto or MODELO_POR_DEFECTO,
        modelo_director=agente.modelo_director, techo_tokens=agente.techo_tokens,
        api_key=api_key, temperatura=agente.temperatura, max_vueltas=agente.vueltas,
        solo_herramientas=agente.herramientas, ca_bundle=ca_bundle,
        sin_verificar=sin_verificar, **({"url": url} if url else {}))
    salida = analista.analizar(documento, instrucciones=agente.instrucciones,
                               al_paso=al_paso, cabecera=cabecera(datos))

    partido_id = datos["partido"]["id"]
    pasos = salida.get("pasos") or []
    segundos = round(time.monotonic() - empezo, 1)
    apuntadas: dict = {}
    if guardar_todo:
        almacen.guardar_dictamen(
            partido_id, salida.get("respuesta") or "",
            modelo=salida.get("modelo") or agente.modelo, expediente=documento,
            en_la_nube=bool(api_key), tokens=salida.get("tokens"),
            agente=agente.clave, pasos=pasos,
            sin_numeros=bool(salida.get("sin_numeros")), segundos=segundos,
            en_sandwich=bool(salida.get("sandwich")))
        if salida.get("probabilidades"):
            # El pronóstico se le pasa hecho: el expediente ya lo calculó, y sin
            # él `anotar` volvería a calcularlo para lo único que necesita de
            # ahí, que son las cuotas con las que rellenar `prob_mercado`.
            apuntadas = anotar(
                almacen, partido_id, pronostico=datos.get("pronostico"),
                cliente=cliente, autor=agente.clave,
                version=f"{agente.clave}@{huella(agente)}",
                probabilidades=salida["probabilidades"])
    return {
        "disponible": True,
        "agente": agente.clave,
        "nombre": agente.nombre,
        "partido_id": partido_id,
        "partido": f"{datos['partido']['local']} - {datos['partido']['visitante']}",
        "respuesta": salida.get("respuesta") or "",
        "probabilidades": salida.get("probabilidades"),
        "sin_numeros": bool(salida.get("sin_numeros")),
        "reparado": bool(salida.get("reparado")),
        "pasos": pasos,
        "vueltas": salida.get("vueltas"),
        "modelo": salida.get("modelo"),
        "en_sandwich": bool(salida.get("sandwich")),
        "tokens": salida.get("tokens") or {},
        "segundos": segundos,
        "expediente": datos["tamano"],
        "apuntadas": apuntadas.get("guardadas", 0),
        "herramientas_pedidas": [p.get("nombre") for p in pasos
                                 if p.get("tipo") == "herramienta"],
    }


def _sesion_de(almacen, cliente):
    """Una sesión que comparte el almacén y el cliente que ya están abiertos.

    Se le pasa el almacén por dentro a propósito: si se le diera solo la ruta
    abriría una segunda conexión a la misma base, y entonces la escritura de uno
    esperaría a la del otro sin que se viera por qué. Esta sesión **no se cierra**
    aquí, justamente porque cerrarla cerraría el almacén de quien nos llamó.
    """
    from ..sesion import Sesion

    return Sesion(cliente=cliente, _almacen=almacen)


# El enganche a LangChain vive al lado, en `cancha.agentes.langchain`, y sigue
# donde estaba: `from cancha.agentes.langchain import agente`. No se importa
# aquí a propósito, porque es un extra opcional y esto no depende de él.
__all__ = ["CLAVES_RESERVADAS", "POR_DEFECTO", "RUTA_POR_DEFECTO",
           "VUELTAS_MAXIMAS", "Agente", "AgenteRaro", "cargar", "construir",
           "correr", "guardar", "huella", "ruta", "validar"]
