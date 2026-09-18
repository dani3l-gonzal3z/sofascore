"""ESPN: una segunda agenda, clasificaciones y —lo que nadie más da— noticias.

ESPN sirve un JSON público por liga: el marcador del día, la clasificación,
el resumen de un partido y las noticias. No pide sesión ni disfraz. Es la
misma API que usa ``soccerdata`` para su lector de ESPN.

Para el framework aporta tres cosas que Sofascore no:

* **una agenda independiente**: cuando la ruta del calendario de Sofascore
  se cayó (pasó), esta seguía en pie;
* **noticias**: lesiones, destituciones, sanciones. Es el contexto que
  ningún número trae y que una IA sí puede leer;
* **la línea de ESPN** (favorito y más/menos de goles) como segunda opinión
  del mercado.

Los ids de ESPN no son los de Sofascore: los partidos se emparejan por
nombre y fecha, como con las demás fuentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..cuotas import favorito, probabilidades
from .base import Fuente, _numero, registrar

#: Código de ESPN por competición de Sofascore.
LIGAS: dict[int, str] = {
    8: "esp.1", 54: "esp.2",
    17: "eng.1", 18: "eng.2",
    23: "ita.1", 53: "ita.2",
    35: "ger.1", 44: "ger.2",
    34: "fra.1", 182: "fra.2",
    37: "ned.1", 238: "por.1", 52: "tur.1",
    242: "usa.1", 955: "ksa.1",
    11620: "mex.1", 11621: "mex.1", 155: "arg.1",
    7: "uefa.champions", 679: "uefa.europa", 17015: "uefa.europa.conf",
    384: "conmebol.libertadores",
}

ALIAS: dict[str, str] = {
    "laliga": "esp.1", "la liga": "esp.1", "premier": "eng.1", "serie a": "ita.1",
    "bundesliga": "ger.1", "ligue 1": "fra.1", "mls": "usa.1", "arabia": "ksa.1",
    "saudi": "ksa.1", "champions": "uefa.champions", "europa league": "uefa.europa",
    "conference": "uefa.europa.conf", "eredivisie": "ned.1", "primeira": "por.1",
    "super lig": "tur.1", "libertadores": "conmebol.libertadores",
}


def moneyline_a_decimal(valor: Any) -> float | None:
    """La cuota americana (``-150``, ``+400``) a decimal (``1.67``, ``5.0``)."""
    numero = _numero(valor)
    if not isinstance(numero, (int, float)) or numero == 0:
        return None
    return round(1 + (numero / 100 if numero > 0 else 100 / abs(numero)), 3)


@registrar
@dataclass
class ESPN(Fuente):
    """Agenda, clasificación, resumen y noticias por liga."""

    NOMBRE = "espn"

    nombre: str = "espn"
    base_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    rate_limit: float = 3.0
    ttl: int = 30 * 60
    descripcion: str = (
        "Agenda del día, clasificación, resumen de partido y NOTICIAS por liga, "
        "de un JSON público. Es la segunda agenda cuando Sofascore no contesta y "
        "el único sitio de donde salen lesiones y destituciones."
    )
    headers: dict[str, str] = field(default_factory=dict)

    # --- consultas ---

    def agenda(self, liga: int | str, fecha: str | None = None) -> list[dict]:
        """Los partidos de una liga un día (``AAAA-MM-DD``; por defecto, hoy)."""
        ruta = f"/{self.codigo(liga)}/scoreboard"
        if fecha:
            ruta += f"?dates={fecha.replace('-', '')}"
        datos = self.json(ruta)
        return [self._evento(e, self.codigo(liga)) for e in (datos or {}).get("events", []) or []]

    def agenda_del_dia(self, fecha: str | None = None,
                       ligas: list[int | str] | None = None) -> list[dict]:
        """La agenda de varias ligas a la vez. Una liga que falle no para el resto."""
        from ..errors import SofascoreError

        salida = []
        for liga in ligas or sorted(set(LIGAS.values())):
            try:
                salida.extend(self.agenda(liga, fecha))
            except SofascoreError:
                continue
        salida.sort(key=lambda e: e.get("fecha_hora") or "")
        return salida

    def clasificacion(self, liga: int | str) -> list[dict]:
        """La tabla, con puntos, partidos, goles y forma."""
        datos = self.json(f"/{self.codigo(liga)}/standings")
        filas = []
        for grupo in (datos or {}).get("children", []) or []:
            entradas = ((grupo.get("standings") or {}).get("entries")) or []
            for entrada in entradas:
                estadisticas = {s.get("name"): s for s in entrada.get("stats", []) or []}

                def valor(nombre: str, tabla: dict = estadisticas) -> Any:
                    bloque = tabla.get(nombre) or {}
                    return _numero(bloque.get("value", bloque.get("displayValue")))

                filas.append({
                    "grupo": grupo.get("name"),
                    "puesto": valor("rank"),
                    "equipo": (entrada.get("team") or {}).get("displayName"),
                    "equipo_id_espn": _numero((entrada.get("team") or {}).get("id")),
                    "partidos": valor("gamesPlayed"),
                    "puntos": valor("points"),
                    "ganados": valor("wins"), "empatados": valor("ties"),
                    "perdidos": valor("losses"),
                    "goles_favor": valor("pointsFor"), "goles_contra": valor("pointsAgainst"),
                    "diferencia": valor("pointDifferential"),
                })
        filas.sort(key=lambda f: (f["grupo"] or "", f["puesto"] or 999))
        return filas

    def noticias(self, liga: int | str, cuantas: int = 20, equipo: str | None = None) -> list[dict]:
        """Los titulares de una liga; con ``equipo``, solo los que lo mencionen."""
        from ..resolve import normalizar

        datos = self.json(f"/{self.codigo(liga)}/news?limit={int(cuantas)}", ttl=15 * 60)
        salida = []
        buscado = normalizar(equipo) if equipo else ""
        for articulo in (datos or {}).get("articles", []) or []:
            texto = f"{articulo.get('headline', '')} {articulo.get('description', '')}"
            equipos = [c.get("description") for c in articulo.get("categories", []) or []
                       if c.get("type") == "team" and c.get("description")]
            if buscado and buscado not in normalizar(texto + " " + " ".join(equipos)):
                continue
            salida.append({
                "titulo": articulo.get("headline"),
                "resumen": articulo.get("description"),
                "fecha": articulo.get("published"),
                "equipos": equipos,
                "enlace": ((articulo.get("links") or {}).get("web") or {}).get("href"),
            })
        return salida

    def partido(self, liga: int | str, partido_id: int | str) -> dict:
        """El resumen de un partido: estadísticas por equipo y momentos clave."""
        datos = self.json(f"/{self.codigo(liga)}/summary?event={int(partido_id)}", ttl=3600)
        boxscore = (datos or {}).get("boxscore") or {}
        equipos = []
        for bloque in boxscore.get("teams", []) or []:
            equipos.append({
                "equipo": (bloque.get("team") or {}).get("displayName"),
                "estadisticas": {s.get("name"): s.get("displayValue")
                                 for s in bloque.get("statistics", []) or []},
            })
        momentos = []
        for evento in (datos or {}).get("keyEvents", []) or []:
            momentos.append({
                "minuto": (evento.get("clock") or {}).get("displayValue"),
                "tipo": (evento.get("type") or {}).get("text"),
                "texto": evento.get("text"),
                "equipo": (evento.get("team") or {}).get("displayName"),
            })
        info = (datos or {}).get("gameInfo") or {}
        return {
            "fuente": "espn",
            "partido_id": int(partido_id),
            "estadio": (info.get("venue") or {}).get("fullName"),
            "asistencia": info.get("attendance"),
            "equipos": equipos,
            "momentos": momentos,
        }

    def buscar_partido(self, liga: int | str, fecha: str, local: str,
                       visitante: str) -> dict | None:
        """El partido de ESPN que corresponde a uno de Sofascore, por nombres y día."""
        from ..resolve import parecido

        mejor, mejor_puntos = None, 0.0
        for partido in self.agenda(liga, fecha):
            uno, otro = parecido(partido["local"], local), parecido(partido["visitante"], visitante)
            # Los dos lados tienen que parecerse: con uno exacto y otro cualquiera,
            # «Girona - Osasuna» encajaría con «Sevilla - Osasuna».
            puntos = (uno + otro) / 2 if min(uno, otro) >= 0.4 else 0.0
            if puntos > mejor_puntos:
                mejor, mejor_puntos = partido, puntos
        if mejor and mejor_puntos >= 0.55:
            return {**mejor, "encaje": round(mejor_puntos, 2)}
        return None

    # --- traducción ---

    @staticmethod
    def codigo(liga: int | str) -> str:
        if isinstance(liga, int) or str(liga).isdigit():
            codigo = LIGAS.get(int(liga))
            if not codigo:
                raise ValueError(f"ESPN no tiene código para la competición {liga}.")
            return codigo
        texto = " ".join(str(liga).lower().split())
        if texto in ALIAS:
            return ALIAS[texto]
        if "." in texto:
            return texto
        from ..catalog import find_league

        encontrada = find_league(texto)
        if encontrada and encontrada in LIGAS:
            return LIGAS[encontrada]
        raise ValueError(f"No sé qué liga es '{liga}' para ESPN.")

    @classmethod
    def _evento(cls, crudo: dict, codigo: str) -> dict:
        competicion = ((crudo.get("competitions") or [{}])[0]) or {}
        lados = {"local": {}, "visitante": {}}
        for competidor in competicion.get("competitors", []) or []:
            lado = "local" if competidor.get("homeAway") == "home" else "visitante"
            equipo = competidor.get("team") or {}
            lados[lado] = {
                "nombre": equipo.get("displayName") or equipo.get("name"),
                "corto": equipo.get("shortDisplayName") or equipo.get("abbreviation"),
                "id_espn": _numero(equipo.get("id")),
                "goles": _numero(competidor.get("score")),
                "ganador": competidor.get("winner"),
                "forma": competidor.get("form"),
            }
        estado = ((crudo.get("status") or {}).get("type")) or {}
        fecha_hora = crudo.get("date") or ""
        return {
            "fuente": "espn",
            "liga": codigo,
            "partido_id": _numero(crudo.get("id")),
            "fecha_hora": fecha_hora,
            "fecha": fecha_hora[:10] or None,
            "hora_utc": fecha_hora[11:16] or None,
            "local": lados["local"].get("nombre"),
            "visitante": lados["visitante"].get("nombre"),
            "goles_local": lados["local"].get("goles"),
            "goles_visitante": lados["visitante"].get("goles"),
            "estado": estado.get("description") or estado.get("state"),
            "terminado": bool(estado.get("completed")),
            "estadio": (competicion.get("venue") or {}).get("fullName"),
            "equipos": lados,
            "mercado": cls._mercado(competicion),
        }

    @staticmethod
    def _mercado(competicion: dict) -> dict | None:
        """La línea de ESPN, traducida a cuotas decimales y probabilidades."""
        lineas = competicion.get("odds") or []
        if not lineas:
            return None
        linea = lineas[0] or {}
        cuotas = {
            "local": moneyline_a_decimal((linea.get("homeTeamOdds") or {}).get("moneyLine")),
            "empate": moneyline_a_decimal((linea.get("drawOdds") or {}).get("moneyLine")),
            "visitante": moneyline_a_decimal((linea.get("awayTeamOdds") or {}).get("moneyLine")),
        }
        probs = probabilidades(cuotas) if all(cuotas.values()) else {}
        return {
            "casa": (linea.get("provider") or {}).get("name"),
            "linea": linea.get("details"),
            "mas_menos": _numero(linea.get("overUnder")),
            "cuotas": cuotas if all(cuotas.values()) else None,
            "probabilidades": probs or None,
            "favorito": favorito(probs) if probs else None,
        }


__all__ = ["ESPN", "LIGAS", "ALIAS", "moneyline_a_decimal"]
