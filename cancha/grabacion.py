"""Grabar lo que de verdad responde la API, y usarlo en los tests.

El punto flaco de este proyecto ha sido siempre el mismo: las respuestas de
ejemplo con las que se prueba están escritas a mano. Los tests demuestran que
el código es coherente **consigo mismo**, no que coincida con la realidad. Eso
dejó pasar dos fallos de verdad: la ruta del histórico pedía el ``customId`` y
no el id (dos rondas rota, en silencio), y un mapa de tiros con un gol que
contradecía el marcador.

Aquí está el arreglo. :class:`Grabadora` envuelve cualquier transporte y guarda
lo que llega; :class:`Reproductor` lo sirve después sin tocar la red. Con eso,
``tests/test_contrato.py`` puede comprobar que lo que el código da por supuesto
está de verdad en la respuesta.

**Solo se guarda la respuesta.** Nunca la petición, que es donde va tu cookie
de Sofascore Plus. Aun así, míralo antes de subir nada a un repositorio: son
datos de un servicio ajeno.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .transport import Response, Transport

#: Cabeceras que sí merece la pena conservar de la respuesta.
CABECERAS_UTILES = ("content-type", "cache-control", "date")


def nombre_de_fichero(url: str) -> str:
    """Un nombre legible y estable a partir de una URL.

    ``.../api/v1/event/12437616/statistics`` se convierte en
    ``sofascore_event_12437616_statistics.json``: se puede abrir y saber qué es
    sin descifrar un hash.

    Lleva delante el nombre de la fuente porque si no chocan entre ellas: el
    ``/Barcelona`` de ClubElo y cualquier otra ruta corta acabarían en el mismo
    fichero.
    """
    anfitrion = re.match(r"^https?://([^/]+)", url)
    fuente = ""
    if anfitrion:
        partes = anfitrion.group(1).split(".")
        # De 'api.sofascore.com' queda 'sofascore'; de 'understat.com', 'understat'.
        significativas = [p for p in partes if p not in ("www", "api", "com", "org", "net")]
        fuente = significativas[-1] if significativas else partes[0]

    ruta = re.sub(r"^https?://[^/]+", "", url)
    ruta = re.sub(r"/api/v\d+", "", ruta)
    ruta = ruta.strip("/") or "raiz"
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", ruta).strip("_").lower()
    entero = f"{fuente}_{limpio}" if fuente else limpio
    return f"{entero[:120]}.json"


@dataclass
class Grabacion:
    """Una respuesta guardada."""

    url: str
    estado: int
    cuerpo: Any
    grabado_en: str = ""
    cabeceras: dict[str, str] = field(default_factory=dict)
    #: ``True`` si el cuerpo se guardó como texto por no ser JSON.
    texto_plano: bool = False

    @classmethod
    def desde_respuesta(cls, respuesta: Response) -> Grabacion:
        try:
            cuerpo, plano = respuesta.json(), False
        except Exception:  # noqa: BLE001 - hay fuentes que sirven CSV o HTML
            cuerpo, plano = respuesta.text(), True
        return cls(
            url=respuesta.url,
            estado=respuesta.status,
            cuerpo=cuerpo,
            texto_plano=plano,
            grabado_en=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            cabeceras={k: v for k, v in respuesta.headers.items() if k in CABECERAS_UTILES},
        )

    def como_respuesta(self) -> Response:
        cuerpo = (
            self.cuerpo.encode("utf-8") if self.texto_plano
            else json.dumps(self.cuerpo, ensure_ascii=False).encode("utf-8")
        )
        return Response(status=self.estado, url=self.url, body=cuerpo,
                        headers=dict(self.cabeceras))

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "estado": self.estado,
            "grabado_en": self.grabado_en,
            "cabeceras": self.cabeceras,
            "texto_plano": self.texto_plano,
            "cuerpo": self.cuerpo,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> Grabacion:
        return cls(
            url=datos["url"],
            estado=datos.get("estado", 200),
            cuerpo=datos.get("cuerpo"),
            grabado_en=datos.get("grabado_en", ""),
            cabeceras=datos.get("cabeceras") or {},
            texto_plano=bool(datos.get("texto_plano")),
        )


class Grabadora:
    """Envuelve un transporte y guarda cada respuesta en una carpeta.

    No cambia nada de lo que pasa: la respuesta se devuelve tal cual y, de
    paso, se escribe a disco. Si escribir falla, la petición sigue su curso.
    """

    def __init__(self, transporte: Transport, carpeta: str | Path,
                 solo_correctas: bool = True) -> None:
        self.transporte = transporte
        self.carpeta = Path(carpeta)
        self.solo_correctas = solo_correctas
        #: Qué se ha guardado en esta sesión, para poder contarlo al final.
        self.guardadas: list[str] = []

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        respuesta = self.transporte.request(method, url, headers)
        if self.solo_correctas and not respuesta.ok:
            return respuesta
        # Grabar es un extra: que falle no puede tumbar la petición.
        with suppress(OSError):
            self._guardar(respuesta)
        return respuesta

    def _guardar(self, respuesta: Response) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        destino = self.carpeta / nombre_de_fichero(respuesta.url)
        grabacion = Grabacion.desde_respuesta(respuesta)
        destino.write_text(
            json.dumps(grabacion.to_dict(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        self.guardadas.append(destino.name)

    def close(self) -> None:
        cerrar = getattr(self.transporte, "close", None)
        if callable(cerrar):
            cerrar()


class Reproductor:
    """Sirve respuestas grabadas, sin tocar la red.

    Si le piden una URL que no está grabada, contesta 404 y lo apunta en
    :attr:`no_encontradas`: así se ve qué le falta a la grabación en vez de
    quedarse esperando a un servidor que nunca se llamó.
    """

    def __init__(self, carpeta: str | Path) -> None:
        self.carpeta = Path(carpeta)
        self.grabaciones = cargar(self.carpeta)
        self.no_encontradas: list[str] = []
        #: URLs servidas, en orden, para poder asertar en un test.
        self.calls: list[str] = []

    def request(self, method: str, url: str, headers: dict[str, str]) -> Response:
        self.calls.append(url)
        grabacion = self.grabaciones.get(nombre_de_fichero(url))
        if grabacion is None:
            self.no_encontradas.append(url)
            return Response(
                status=404, url=url,
                body=json.dumps({"error": "no grabado", "url": url}).encode("utf-8"),
            )
        return grabacion.como_respuesta()


def cargar(carpeta: str | Path) -> dict[str, Grabacion]:
    """Lee una carpeta de grabaciones. Devuelve ``{}`` si no existe."""
    ruta = Path(carpeta)
    if not ruta.is_dir():
        return {}
    salida: dict[str, Grabacion] = {}
    for fichero in sorted(ruta.glob("*.json")):
        try:
            salida[fichero.name] = Grabacion.from_dict(
                json.loads(fichero.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return salida


def resumen(carpeta: str | Path) -> dict:
    """Qué hay grabado: cuántas respuestas, de cuándo y de qué rutas."""
    grabaciones = cargar(carpeta)
    if not grabaciones:
        return {"grabaciones": 0}
    fechas = sorted(g.grabado_en for g in grabaciones.values() if g.grabado_en)
    return {
        "grabaciones": len(grabaciones),
        "desde": fechas[0] if fechas else "",
        "hasta": fechas[-1] if fechas else "",
        "rutas": sorted(g.url.split("/api/v1")[-1] for g in grabaciones.values()),
    }


def preparar_transporte(transporte: Transport, settings) -> Transport:
    """Envuelve o sustituye el transporte según los ajustes.

    Reproducir gana a grabar: si estás sirviendo de una grabación no tiene
    sentido volver a grabarla.
    """
    if getattr(settings, "reproducir_de", ""):
        return Reproductor(settings.reproducir_de)
    if getattr(settings, "grabar_en", ""):
        return Grabadora(transporte, settings.grabar_en)
    return transporte


__all__ = [
    "Grabadora", "Reproductor", "Grabacion", "cargar", "resumen", "nombre_de_fichero",
    "preparar_transporte",
]
