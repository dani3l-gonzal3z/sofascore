"""La maquinaria común a todos los informes.

Un informe —de un partido, de un equipo, de un jugador, de una competición— es
siempre lo mismo: una lista de secciones, cada una con su estado. Aquí vive esa
mecánica; lo específico de cada tipo está en :mod:`sofascore.match` y
:mod:`sofascore.entities`.

La regla de oro: **una sección que falla nunca tumba el informe**. Se queda
marcada y las demás siguen.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .endpoints import Section
from .errors import NotFound, PlusRequired, SofascoreError

#: Estados posibles de una sección.
OK = "ok"
EMPTY = "empty"
PLUS_REQUIRED = "plus_required"
UNAVAILABLE = "unavailable"
ERROR = "error"

ICONOS = {OK: "✓", EMPTY: "·", PLUS_REQUIRED: "🔒", UNAVAILABLE: "–", ERROR: "✗"}


@dataclass
class SectionResult:
    """Qué ha pasado con una sección concreta."""

    name: str
    scope: str
    status: str
    data: Any = None
    error: str = ""
    endpoint: str = ""
    description: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self, include_data: bool = True) -> dict:
        salida = {
            "seccion": self.name,
            "ambito": self.scope,
            "estado": self.status,
            "endpoint": self.endpoint,
            "descripcion": self.description,
        }
        if self.error:
            salida["error"] = self.error
        if include_data:
            salida["datos"] = self.data
        return salida


def vacio(datos: Any) -> bool:
    """¿La respuesta llegó bien pero sin nada dentro?"""
    return datos is None or (isinstance(datos, (list, dict, str)) and len(datos) == 0)


def run_section(seccion: Section, traer: Callable[[Section], Any]) -> SectionResult:
    """Ejecuta ``traer`` y traduce lo que pase a un :class:`SectionResult`."""
    resultado = SectionResult(
        name=seccion.name,
        scope=seccion.scope,
        status=OK,
        endpoint=seccion.path,
        description=seccion.description,
    )
    try:
        datos = traer(seccion)
        resultado.data = datos
        resultado.status = EMPTY if vacio(datos) else OK
    except PlusRequired as exc:
        resultado.status = PLUS_REQUIRED
        resultado.error = str(exc)
    except NotFound as exc:
        resultado.status = UNAVAILABLE
        resultado.error = f"No disponible aquí ({exc.status})."
    except SofascoreError as exc:
        resultado.status = ERROR
        resultado.error = str(exc)
    return resultado


def run_all(
    tareas: list[tuple[Section, Callable[[Section], Any]]],
    hilos: int = 4,
) -> list[SectionResult]:
    """Ejecuta las secciones en paralelo (o en fila si ``hilos <= 1``)."""
    if hilos <= 1 or len(tareas) <= 1:
        return [run_section(s, f) for s, f in tareas]
    with ThreadPoolExecutor(max_workers=min(hilos, len(tareas))) as pool:
        futuros = [pool.submit(run_section, s, f) for s, f in tareas]
        return [f.result() for f in futuros]


@dataclass
class BaseReport:
    """Lo que todo informe sabe hacer con sus secciones."""

    sections: dict[str, SectionResult] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def __getitem__(self, nombre: str) -> Any:
        return self.sections[nombre].data

    def __contains__(self, nombre: str) -> bool:
        return nombre in self.sections and self.sections[nombre].ok

    def get(self, nombre: str, default: Any = None) -> Any:
        """Datos de una sección, o ``default`` si no está disponible."""
        resultado = self.sections.get(nombre)
        return resultado.data if resultado and resultado.ok else default

    def available(self) -> list[str]:
        """Secciones que sí traen datos."""
        return [n for n, r in self.sections.items() if r.ok]

    def empty(self) -> list[str]:
        """Secciones que existen pero vienen vacías."""
        return [n for n, r in self.sections.items() if r.status == EMPTY]

    def locked(self) -> list[str]:
        """Secciones que necesitan Sofascore Plus y no se han podido traer."""
        return [n for n, r in self.sections.items() if r.status == PLUS_REQUIRED]

    def failed(self) -> list[str]:
        """Secciones que han fallado o que no existen para esto."""
        return [n for n, r in self.sections.items() if r.status in (ERROR, UNAVAILABLE)]

    def resumen_estados(self) -> dict[str, list[str]]:
        return {
            "disponibles": self.available(),
            "vacias": self.empty(),
            "requieren_plus": self.locked(),
            "fallidas": self.failed(),
        }

    def lineas_estado(self) -> list[str]:
        """Una línea por sección, con su icono de estado."""
        lineas = []
        for nombre, resultado in self.sections.items():
            icono = ICONOS.get(resultado.status, "?")
            detalle = f" — {resultado.error}" if resultado.error else ""
            lineas.append(f" {icono} {nombre:<20} {resultado.status}{detalle}")
        return lineas

    def reordenar(self, pedidas: list[str]) -> None:
        """Deja las secciones en el orden en que se pidieron.

        Las que se trajeron sin pedirlas (un requisito previo) van justo
        detrás de la primera, que es de donde cuelgan.
        """
        extras = [n for n in self.sections if n not in pedidas]
        orden = [pedidas[0], *extras, *pedidas[1:]] if pedidas else extras
        self.sections = {
            nombre: self.sections[nombre]
            for nombre in dict.fromkeys(orden)
            if nombre in self.sections
        }
