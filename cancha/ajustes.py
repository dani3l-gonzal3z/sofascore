"""Los ajustes: decidir una vez y no volver a escribirlo.

La hora de la guardia, las ligas que sigues, el modelo de Ollama, el puerto y
el bot viven en un ``datos/ajustes.json`` que se puede tocar desde tres sitios:
la pestaña Ajustes de la interfaz —también desde el móvil—, el comando
``cancha ajustes``, o el propio fichero.

**El orden manda**: lo que pones en la línea de comandos gana siempre a lo que
hay en el fichero, y el fichero gana a lo que trae de fábrica. Así se puede
probar algo una vez (``cancha guardia --a-las 02:00``) sin cambiar lo de todos
los días.

El fichero es JSON y no TOML por lo de siempre en este proyecto: ``json`` está
en la biblioteca estándar y ``tomllib`` no sabe escribir.
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from typing import Any

RUTA_POR_DEFECTO = "datos/ajustes.json"

#: Lo que trae de fábrica. Es también el mapa de lo que se puede cambiar: una
#: clave que no esté aquí no se guarda, para que un fichero a medio escribir no
#: se convierta en ajustes fantasma que nadie lee.
POR_DEFECTO: dict[str, Any] = {
    "memoria": "datos/cancha.db",
    "briefings": "datos/briefings",
    #: Vacío quiere decir «todo el catálogo». Acepta grupos (``grandes``),
    #: atajos (``femenino``, ``europa``) y competiciones sueltas (``laliga``).
    "ligas": [],
    "modelo": "hermes3",
    "ollama": "http://127.0.0.1:11434",
    #: Con clave, `ollama` se ignora y se habla con https://ollama.com. Los
    #: datos del partido salen entonces de tu ordenador: es la única parte de
    #: esto que no es local, y por eso va con su aviso en la interfaz.
    "ollama_api_key": "",
    "guardia": {
        "activa": True,
        "hora": "03:00",
        "dias": 1,
        "partidos": 12,
        "max": 0,
        "ultimos": 6,
        "registro": "datos/guardia.log",
    },
    #: Cuánta historia traerse y con cuánto detalle. Hasta aquí el único modo de
    #: llenar la memoria era ir partido a partido desde su pantalla, y con eso no
    #: se junta muestra: se tarda semanas en tener con qué calcular nada.
    "historia": {
        #: Hacia atrás desde hoy. Tres temporadas es lo que hace falta para que
        #: un perfil de equipo tenga sentido y un árbitro tenga muestra.
        "anos": 3,
        #: Qué se pide de cada partido. Cada sección es **una petición más por
        #: partido**, así que esto multiplica: con cinco secciones, diez mil
        #: partidos son cincuenta mil peticiones. Ver `cancha historia --plan`.
        "secciones": ["statistics", "lineups", "incidents", "shotmap",
                      "odds_featured"],
        #: Tope de peticiones por tanda. 0 = sin tope, y entonces tarda lo que
        #: tarde. Con tope se puede dejar corriendo a ratos y reanudar.
        "max": 0,
    },
    "web": {"puerto": 8765, "lan": True, "clave": ""},
    #: Cuando algo abre tu HTTPS por el camino —un antivirus que «revisa webs
    #: seguras», el proxy de una empresa, una VPN—, Python no conoce a quien
    #: firma el certificado y no se conecta a nada. Ver :mod:`cancha.tls`.
    "red": {"ca_bundle": "", "sin_verificar": False},
    "telegram": {"token": "", "chats": []},
}

#: Lo que no se enseña de vuelta. El token del bot es una llave: se puede
#: escribir desde la interfaz, pero no se devuelve para que no acabe en una
#: captura de pantalla ni en el historial del navegador.
SECRETOS = ("telegram.token", "ollama_api_key")


def ruta(dada: str | Path | None = None) -> Path:
    return Path(dada or os.environ.get("CANCHA_AJUSTES") or RUTA_POR_DEFECTO)


def _fusionar(base: dict, encima: dict) -> dict:
    """Mezcla en profundidad, ignorando claves que no existan de fábrica."""
    salida = deepcopy(base)
    for clave, valor in (encima or {}).items():
        if clave not in salida:
            continue
        if isinstance(salida[clave], dict) and isinstance(valor, dict):
            salida[clave] = _fusionar(salida[clave], valor)
        else:
            salida[clave] = valor
    return salida


def cargar(dada: str | Path | None = None) -> dict:
    """Los ajustes guardados, sobre los de fábrica.

    Un fichero roto no puede dejarte sin programa: se avisa por el valor
    ``_error`` y se sigue con lo de fábrica, que es lo que hace falta para
    poder entrar a arreglarlo.
    """
    destino = ruta(dada)
    if not destino.is_file():
        return deepcopy(POR_DEFECTO)
    try:
        guardado = json.loads(destino.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        salida = deepcopy(POR_DEFECTO)
        salida["_error"] = f"No he podido leer {destino}: {exc}. Uso los de fábrica."
        return salida
    if not isinstance(guardado, dict):
        salida = deepcopy(POR_DEFECTO)
        salida["_error"] = f"{destino} no contiene un objeto JSON. Uso los de fábrica."
        return salida
    return _fusionar(POR_DEFECTO, guardado)


def guardar(ajustes: dict, dada: str | Path | None = None) -> Path:
    """Escribe los ajustes. Solo los conocidos, y solo para ti.

    El fichero lleva el token del bot, así que se le quitan los permisos de
    grupo y de otros donde el sistema lo permita. En Windows no significa nada
    y no se finge que sí.
    """
    destino = ruta(dada)
    destino.parent.mkdir(parents=True, exist_ok=True)
    limpio = {k: v for k, v in _fusionar(POR_DEFECTO, ajustes).items()
              if not k.startswith("_")}
    destino.write_text(json.dumps(limpio, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    # En Windows esto no significa gran cosa y no se finge que sí.
    with suppress(OSError):
        destino.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return destino


# ------------------------------------------------------------------ escribir

class AjusteDesconocido(ValueError):
    """Esa clave no existe. Se dice, en vez de guardarla y no usarla nunca."""


def _claves() -> list[str]:
    """Todas las claves con punto que se pueden poner."""
    salida = []
    for clave, valor in POR_DEFECTO.items():
        if isinstance(valor, dict):
            salida += [f"{clave}.{sub}" for sub in valor]
        else:
            salida.append(clave)
    return salida


def _convertir(actual: Any, texto: str) -> Any:
    """Del texto de la línea de comandos al tipo que tenía ese ajuste."""
    if isinstance(actual, bool):
        return texto.strip().lower() in ("1", "si", "sí", "true", "on", "yes")
    if isinstance(actual, int):
        try:
            return int(texto)
        except ValueError as exc:
            raise AjusteDesconocido(f"«{texto}» no es un número entero.") from exc
    if isinstance(actual, list):
        return [x.strip() for x in texto.replace(";", ",").split(",") if x.strip()]
    return texto


def poner(ajustes: dict, clave: str, valor: Any) -> dict:
    """Cambia un ajuste por su nombre con punto. Devuelve los ajustes nuevos."""
    partes = clave.strip().split(".")
    if clave.strip() not in _claves():
        raise AjusteDesconocido(
            f"No existe el ajuste «{clave}». Los que hay:\n  "
            + "\n  ".join(_claves()))
    salida = deepcopy(ajustes)
    destino = salida
    for parte in partes[:-1]:
        destino = destino[parte]
    actual = destino[partes[-1]]
    nuevo = _convertir(actual, valor) if isinstance(valor, str) else valor
    if clave.strip() in SECRETOS and isinstance(nuevo, str) and nuevo:
        nuevo = _revisar_secreto(clave, nuevo)
    destino[partes[-1]] = nuevo
    return salida


def sin_secretos(ajustes: dict) -> dict:
    """Los ajustes tal como se pueden enseñar: con el token tapado."""
    salida = deepcopy(ajustes)
    for camino in SECRETOS:
        trozos = camino.split(".")
        nodo = salida
        for trozo in trozos[:-1]:
            nodo = nodo.get(trozo, {})
        valor = nodo.get(trozos[-1])
        if valor:
            nodo[trozos[-1]] = "•" * 8 + str(valor)[-4:]
            nodo[trozos[-1] + "_puesto"] = True
        else:
            nodo[trozos[-1]] = ""
            nodo[trozos[-1] + "_puesto"] = False
    return salida


class SecretoRaro(ValueError):
    """Eso que has pegado no puede ser una clave."""


def _revisar_secreto(camino: str, valor: str) -> str:
    """Limpia una clave y se queja si es evidente que no lo es.

    Los dos accidentes que pasan de verdad: pegarla con un salto de línea al
    final —copiar de una web se lo trae— y pegar la **clave pública** SSH de
    Ollama en vez de la API key, que están en la misma pantalla de su web.
    """
    limpio = valor.strip()
    if not limpio:
        return limpio
    if limpio.startswith("ssh-"):
        raise SecretoRaro(
            f"Eso es una clave pública SSH, no una API key ({limpio[:11]}…). "
            "En ollama.com las dos cosas están juntas: la que hace falta es la "
            "de «API keys».")
    if "•" in limpio:
        raise SecretoRaro(
            "Ahí dentro han quedado los puntos de la clave tapada, así que esto "
            "no es una clave. Borra el campo entero y pega la clave sola.")
    if any(c.isspace() for c in limpio):
        raise SecretoRaro("La clave lleva un espacio o un salto de línea en medio. "
                          "Pégala entera y sin nada más.")
    del camino
    return limpio


def aplicar_desde_fuera(ajustes: dict, cambios: dict) -> dict:
    """Mezcla lo que llega de la interfaz, respetando lo que no se enseña.

    Un secreto que vuelve vacío es «no lo toques», no «bórralo»: el campo de la
    interfaz se enseña vacío aunque haya uno guardado, que es la única forma de
    que pegar uno nuevo funcione siempre. Para quitarlo del todo está el fichero
    de ajustes, o ``cancha ajustes ollama_api_key=``.
    """
    limpio = deepcopy(cambios or {})
    for camino in SECRETOS:
        trozos = camino.split(".")
        nodo = limpio
        for trozo in trozos[:-1]:
            nodo = nodo.get(trozo) if isinstance(nodo.get(trozo), dict) else {}
        if not isinstance(nodo, dict):
            continue
        nodo.pop(trozos[-1] + "_puesto", None)
        valor = nodo.get(trozos[-1])
        if not isinstance(valor, str):
            continue
        # Vacío es «no lo toques»: el campo se enseña vacío a propósito. Y si
        # vienen puntos es que se ha pegado encima de la máscara, que es
        # justo el accidente que hacía que la clave nueva no se guardara
        # nunca. Eso se dice, no se traga en silencio.
        if not valor.strip():
            nodo.pop(trozos[-1], None)
        else:
            nodo[trozos[-1]] = _revisar_secreto(camino, valor)
    return _fusionar(ajustes, limpio)


# ------------------------------------------------------------------ revisar

def revisar(ajustes: dict) -> list[str]:  # noqa: C901 - es una lista de avisos
    """Qué hay mal en estos ajustes, en palabras. Vacío es que están bien."""
    from .guardia import segundos_hasta
    from .ligas import competiciones_de

    problemas = []
    try:
        segundos_hasta(ajustes["guardia"]["hora"])
    except (ValueError, KeyError, TypeError):
        problemas.append(f"La hora de la guardia «{ajustes['guardia']['hora']}» no vale: "
                         "se escribe como 03:00.")
    ligas = ajustes.get("ligas") or []
    if ligas:
        if not competiciones_de(ligas):
            problemas.append("Ninguna de las ligas elegidas existe en el catálogo. "
                             "Mira las que hay con: cancha ajustes --ligas")
        else:
            from .ligas import ALIAS_GRUPO, GRUPOS, por_nombre

            for liga in ligas:
                clave = " ".join(str(liga).strip().lower().split())
                if clave not in GRUPOS and clave not in ALIAS_GRUPO and not por_nombre(liga):
                    problemas.append(f"No conozco la liga «{liga}»; la ignoro.")
    chats = (ajustes.get("telegram") or {}).get("chats") or []
    for chat in chats:
        try:
            int(chat)
        except (TypeError, ValueError):
            problemas.append(f"«{chat}» no es un identificador de chat: es un número.")
    red = ajustes.get("red") or {}
    bundle = str(red.get("ca_bundle") or "").strip()
    if bundle and not Path(bundle).is_file():
        problemas.append(f"El fichero de certificados «{bundle}» no está. "
                         "Tiene que ser un .pem que exista en este ordenador.")
    if red.get("sin_verificar"):
        problemas.append("Estás sin comprobar con quién hablas (red.sin_verificar). "
                         "Funciona, pero cualquiera que se ponga en medio puede leer "
                         "y cambiar lo que pasa por ahí, incluido el token del bot.")
    puerto = (ajustes.get("web") or {}).get("puerto")
    if not isinstance(puerto, int) or not (1 <= puerto <= 65535):
        problemas.append(f"El puerto «{puerto}» no vale.")
    problemas += _revisar_historia(ajustes.get("historia") or {})
    return problemas


def _revisar_historia(historia: dict) -> list[str]:
    """Que los años y las secciones que se piden existan y sean razonables."""
    from .endpoints import SECTIONS

    problemas = []
    anos = historia.get("anos")
    if not isinstance(anos, int) or not (1 <= anos <= 15):
        problemas.append(f"Los años de historia («{anos}») van de 1 a 15. Sofascore "
                         "tampoco guarda mucho más de las categorías pequeñas.")
    secciones = historia.get("secciones") or []
    if not secciones:
        problemas.append("Sin ninguna sección elegida, un partido se guarda con el "
                         "marcador y nada más: no hay con qué calcular.")
    for seccion in secciones:
        if seccion not in SECTIONS:
            problemas.append(f"No conozco la sección «{seccion}». Las que hay salen "
                             "con: cancha fuentes --secciones")
    # `statistics` es de la que sale casi todo lo que se calcula después. Sin
    # ella se pueden guardar diez mil partidos y seguir sin poder hacer nada.
    if secciones and "statistics" not in secciones:
        problemas.append("Sin «statistics» no hay tiros, ni córners, ni posesión: "
                         "es de donde sale casi todo lo que se calcula. Puedes "
                         "quitarla, pero entonces la memoria no sirve de mucho.")
    maximo = historia.get("max")
    if not isinstance(maximo, int) or maximo < 0:
        problemas.append(f"El tope de peticiones («{maximo}») es un número, y 0 "
                         "significa sin tope.")
    return problemas


def valor(args: Any, nombre: str, desde_ajustes: Any) -> Any:
    """Lo que manda: la línea de comandos si la hay, y si no, los ajustes."""
    dado = getattr(args, nombre, None)
    return desde_ajustes if dado is None else dado


def grupos_de(ajustes: dict) -> list[str] | None:
    """Las ligas elegidas, o ``None`` si vale todo el catálogo."""
    ligas = [x for x in (ajustes.get("ligas") or []) if str(x).strip()]
    return ligas or None


__all__ = ["POR_DEFECTO", "RUTA_POR_DEFECTO", "SECRETOS", "AjusteDesconocido",
           "SecretoRaro",
           "aplicar_desde_fuera", "cargar", "grupos_de", "guardar", "poner",
           "revisar", "ruta", "sin_secretos", "valor"]
