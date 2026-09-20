"""¿Está todo en su sitio? Transportes, credenciales, caché y grabaciones.

Esto vivía dentro del impresor de ``cancha doctor``, así que solo se podía ver
desde un terminal: la página no tenía manera de contarlo, y el móvil menos.
Aquí devuelve datos, y quien quiera los pinta —el comando en texto, la
interfaz en una tarjeta—. Nada de esto toca la red salvo ``probar_api``, que se
pide aparte porque tarda.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache import DiskCache
from .config import Settings
from .errors import SofascoreError
from .transport import AUTO_ORDER, transport_disponible

#: Por qué querría alguien cada transporte. El orden es el de preferencia.
PARA_QUE = {
    "curl": "curl_cffi — imita el TLS de Chrome, atraviesa el anti-bot",
    "httpx": "httpx — HTTP/2 y conexiones reutilizadas",
    "urllib": "biblioteca estándar, siempre está",
}


def transportes() -> list[dict]:
    """Cuáles se pueden usar, sin pedir nada a nadie."""
    return [{"nombre": nombre, "disponible": transport_disponible(nombre),
             "para_que": PARA_QUE[nombre]} for nombre in AUTO_ORDER]


def estado_cache(cache_dir: str | Path | None = None) -> dict:
    """Cuánto hay guardado y dónde."""
    ajustes = Settings.from_env(cache_dir=Path(cache_dir) if cache_dir else None)
    carpeta = ajustes.cache_dir
    if not carpeta:
        return {"activa": False, "nota": "La caché está apagada."}
    ficheros = list(Path(carpeta).rglob("*.json"))
    return {
        "activa": True,
        "carpeta": str(carpeta),
        "respuestas": len(ficheros),
        "kib": round(sum(f.stat().st_size for f in ficheros) / 1024, 1),
    }


def limpiar_cache(cache_dir: str | Path | None = None) -> dict:
    ajustes = Settings.from_env(cache_dir=Path(cache_dir) if cache_dir else None)
    borrados = DiskCache(ajustes.cache_dir).clear()
    return {"borrados": borrados, "carpeta": str(ajustes.cache_dir),
            **estado_cache(cache_dir)}


def estado_grabaciones(carpeta: str = "grabaciones") -> dict:
    from .grabacion import resumen

    datos = resumen(carpeta)
    if not datos.get("grabaciones"):
        return {"grabaciones": 0, "carpeta": carpeta,
                "nota": f"No hay nada grabado en {carpeta}. Grábalo con: cancha grabar <partido>"}
    return {"carpeta": carpeta, **datos}


def estado_tls(ajustes: Any = None) -> dict:
    """Con qué certificados se habla, sin pedir nada a nadie."""
    from .tls import ENV_CA, hay_truststore, ruta_ca

    bundle = ruta_ca(getattr(ajustes, "ca_bundle", None) if ajustes else None)
    flojo = bool(getattr(ajustes, "sin_verificar", False)) if ajustes else False
    if flojo:
        lectura = ("⚠ sin comprobar con quién se habla (red.sin_verificar). "
                   "Cualquiera que se ponga en medio puede leer y cambiar lo que pasa.")
    elif bundle:
        lectura = f"los certificados de {bundle}"
    elif hay_truststore():
        lectura = "los del almacén del sistema (truststore está instalado)"
    else:
        lectura = ("los que trae Python. Si algo abre tu HTTPS por el camino "
                   "—antivirus, proxy de empresa, VPN— no vas a poder conectarte: "
                   "pip install truststore lo arregla casi siempre.")
    return {"ca_bundle": bundle, "sin_verificar": flojo,
            "truststore": hay_truststore(), "variable": ENV_CA, "lectura": lectura}


def probar_tls(host: str = "api.telegram.org", ajustes: Any = None) -> dict:
    """¿Hay alguien abriendo el HTTPS por el camino? Esto sí toca la red."""
    from .tls import inspeccionar

    return {**estado_tls(ajustes), **inspeccionar(host)}


def probar_api(cliente) -> list[dict]:
    """Le pregunta a los dos hosts de Sofascore si contestan.

    Un 401 o un 403 no es lo mismo que un 404: el primero dice «existe pero no
    eres nadie» y el segundo «esto no está». Se distinguen porque llevan a
    arreglos distintos.
    """
    salida = []
    for base in cliente.settings.base_urls():
        try:
            respuesta = cliente.transport.request(
                "GET", f"{base}/sport/football/events/live", cliente._headers())
            salida.append({
                "base": base, "http": respuesta.status, "ok": respuesta.ok,
                "lectura": ("contesta" if respuesta.ok else
                            "existe pero pide identificarse"
                            if respuesta.status in (401, 403) else "no contesta bien"),
            })
        except SofascoreError as exc:
            salida.append({"base": base, "http": None, "ok": False, "lectura": str(exc)})
    return salida


def diagnostico(cliente=None, cache_dir: str | Path | None = None,
                carpeta_grabaciones: str = "grabaciones",
                con_red: bool = False) -> dict[str, Any]:
    """Todo junto. Con ``con_red`` también prueba contra la API."""
    salida: dict[str, Any] = {
        "transportes": transportes(),
        "cache": estado_cache(cache_dir),
        "grabaciones": estado_grabaciones(carpeta_grabaciones),
        "tls": estado_tls(getattr(cliente, "settings", None)),
    }
    if cliente is not None:
        en_uso = type(cliente.transport).__name__
        salida["en_uso"] = en_uso
        salida["credenciales"] = cliente.credentials.describe()
        salida["plus"] = cliente.credentials.present
        if en_uso == "UrllibTransport":
            salida["aviso"] = ("Sofascore suele responder 403 a urllib. "
                               "Instala curl_cffi: pip install curl_cffi")
        if con_red:
            salida["api"] = probar_api(cliente)
    return salida


__all__ = ["PARA_QUE", "diagnostico", "estado_cache", "estado_grabaciones",
           "estado_tls", "limpiar_cache", "probar_api", "probar_tls", "transportes"]
