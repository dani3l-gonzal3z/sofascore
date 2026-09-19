"""football-data.co.uk: resultados y cuotas de cierre desde 1993.

Es la fuente más vieja y más aburrida del fútbol, y por eso vale tanto: un
CSV por liga y temporada, sin anti-bot, sin sesión, sin JSON que cambie de
forma. Trae el resultado, los tiros, los córners, las tarjetas, el árbitro y
—lo que aquí importa— **las cuotas de cierre de varias casas**, que es la
mejor previsión pública que existe de un partido.

Para el framework tiene dos usos:

* **rellenar las cuotas** de los partidos ya guardados en la memoria, que es
  lo que permite separar «rinde mal contra bloque bajo» de «rinde mal siendo
  favorito» también en partidos barridos antes de que se pidieran cuotas;
* **el historial largo** de cualquier equipo: veinte temporadas en veinte
  peticiones.

Las columnas están explicadas en https://www.football-data.co.uk/notes.txt.
Cubre las cinco grandes, sus segundas, Países Bajos, Portugal, Turquía,
Bélgica, Escocia y Grecia. No cubre MLS ni Arabia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..cuotas import favorito, probabilidades
from .base import Fuente, _numero, registrar

#: Código de fichero por competición de Sofascore.
CODIGOS: dict[int, str] = {
    8: "SP1", 54: "SP2",          # España
    17: "E0", 18: "E1",           # Inglaterra
    23: "I1", 53: "I2",           # Italia
    35: "D1", 44: "D2",           # Alemania
    34: "F1", 182: "F2",          # Francia
    37: "N1",                     # Países Bajos
    238: "P1",                    # Portugal
    52: "T1",                     # Turquía
}

#: Alias por nombre, para la consola.
ALIAS: dict[str, str] = {
    "laliga": "SP1", "la liga": "SP1", "segunda": "SP2", "premier": "E0",
    "championship": "E1", "serie a": "I1", "serie b": "I2", "bundesliga": "D1",
    "2.bundesliga": "D2", "ligue 1": "F1", "ligue 2": "F2", "eredivisie": "N1",
    "primeira": "P1", "super lig": "T1", "belgica": "B1", "escocia": "SC0",
    "grecia": "G1",
}

#: Casas cuyas cuotas se leen, en orden de preferencia. La media del mercado
#: (``Avg``) es la más estable; Pinnacle (``PS``) la más afilada.
CASAS = (("Avg", "media del mercado"), ("PS", "Pinnacle"), ("B365", "Bet365"),
         ("Max", "máxima del mercado"))


@registrar
@dataclass
class FutbolData(Fuente):
    """Resultados y cuotas históricas, en CSV."""

    NOMBRE = "futboldata"

    nombre: str = "futboldata"
    base_url: str = "https://www.football-data.co.uk"
    rate_limit: float = 2.0
    #: Una temporada cerrada no cambia nunca; la abierta, cada jornada.
    ttl: int = 6 * 3600
    #: CSV público: nada que sortear, y el disfraz solo añade formas de fallar.
    transporte_preferido: str = "urllib"
    descripcion: str = (
        "Resultados, tiros, tarjetas, árbitro y cuotas de cierre de varias casas, "
        "por liga y temporada desde 1993. Sin anti-bot: un CSV por temporada. "
        "Rellena las cuotas de la memoria y da el historial largo de un equipo."
    )
    headers: dict[str, str] = field(default_factory=dict)

    # --- consultas ---

    def temporada(self, liga: int | str, año: int) -> list[dict]:
        """Todos los partidos de una liga en una temporada, ya traducidos.

        ``año`` es el de inicio: 2024 para la 24/25. ``liga`` puede ser el id
        de Sofascore, el código del fichero (``SP1``) o un alias (``laliga``).
        """
        codigo = self.codigo(liga)
        filas = self.csv(f"/mmz4281/{self.temporada_codigo(año)}/{codigo}.csv")
        salida = [self._fila(f, codigo, año) for f in filas]
        return [f for f in salida if f["local"] and f["visitante"]]

    def equipo(self, liga: int | str, año: int, nombre: str) -> list[dict]:
        """Los partidos de un equipo en una temporada, del más reciente atrás."""
        from ..resolve import parecido

        partidos = [p for p in self.temporada(liga, año)
                    if max(parecido(p["local"], nombre), parecido(p["visitante"], nombre)) >= 0.6]
        partidos.sort(key=lambda p: p["fecha"] or "", reverse=True)
        return partidos

    def buscar_partido(self, liga: int | str, año: int, local: str, visitante: str,
                       fecha: str | None = None) -> dict | None:
        """Encuentra un partido por equipos (y fecha, si se da).

        Los nombres aquí son cortos y sin acentos (``Ath Madrid``, ``Sociedad``),
        así que se empareja por parecido, no por igualdad.
        """
        from ..resolve import parecido

        mejor, mejor_puntos = None, 0.0
        for partido in self.temporada(liga, año):
            if fecha and partido["fecha"] and partido["fecha"] != fecha:
                continue
            uno, otro = parecido(partido["local"], local), parecido(partido["visitante"], visitante)
            # Los dos lados tienen que parecerse: con uno exacto y otro cualquiera,
            # «Girona - Osasuna» encajaría con «Sevilla - Osasuna».
            puntos = (uno + otro) / 2 if min(uno, otro) >= 0.4 else 0.0
            if puntos > mejor_puntos:
                mejor, mejor_puntos = partido, puntos
        if mejor and mejor_puntos >= 0.55:
            return {**mejor, "encaje": round(mejor_puntos, 2)}
        return None

    def cuotas_de(self, evento) -> dict | None:
        """El 1X2 de cierre de un partido de Sofascore, si la liga está cubierta.

        Devuelve el bloque que entiende ``Almacen.guardar_cuotas``, o ``None``.
        """
        from .cruce import temporada_de

        codigo = CODIGOS.get(evento.unique_tournament_id or 0)
        año = temporada_de(evento)
        if not (codigo and año):
            return None
        partido = self.buscar_partido(codigo, año, evento.home.name, evento.away.name,
                                      fecha=evento.date or None)
        if not partido or not partido.get("cuotas"):
            return None
        return {"fuente": "futboldata", "mercado": partido["casa"],
                "cuotas": partido["cuotas"], "probabilidades": partido["probabilidades"],
                "favorito": favorito(partido["probabilidades"]),
                "arbitro": partido.get("arbitro"), "encaje": partido["encaje"]}

    # --- traducción ---

    @staticmethod
    def codigo(liga: int | str) -> str:
        if isinstance(liga, int) or str(liga).isdigit():
            codigo = CODIGOS.get(int(liga))
            if not codigo:
                raise ValueError(f"football-data.co.uk no cubre la competición {liga}.")
            return codigo
        texto = " ".join(str(liga).lower().split())
        if texto in ALIAS:
            return ALIAS[texto]
        if str(liga).upper() in CODIGOS.values() or str(liga).upper() in ALIAS.values():
            return str(liga).upper()
        from ..catalog import find_league

        encontrada = find_league(texto)
        if encontrada and encontrada in CODIGOS:
            return CODIGOS[encontrada]
        raise ValueError(f"No sé qué liga es '{liga}' para football-data.co.uk. "
                         f"Códigos: {', '.join(sorted(set(CODIGOS.values())))}.")

    @staticmethod
    def temporada_codigo(año: int) -> str:
        """``2024`` → ``2425``: así nombra la fuente sus carpetas."""
        return f"{año % 100:02d}{(año + 1) % 100:02d}"

    @staticmethod
    def _fecha(texto: str | None) -> str | None:
        """``26/10/2024`` (o ``26/10/24``) → ``2024-10-26``."""
        if not texto:
            return None
        for formato in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(texto.strip(), formato).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    @classmethod
    def _fila(cls, fila: dict, codigo: str, año: int) -> dict:
        """De las columnas del CSV a nombres que se entiendan."""
        limpia = {(k or "").strip().lstrip("﻿"): (v or "").strip() for k, v in fila.items()}
        cuotas, casa = cls._cuotas(limpia)
        probs = probabilidades(cuotas) if cuotas else {}
        return {
            "liga": codigo,
            "temporada": año,
            "fecha": cls._fecha(limpia.get("Date")),
            "hora": limpia.get("Time") or None,
            "local": limpia.get("HomeTeam"),
            "visitante": limpia.get("AwayTeam"),
            "goles_local": _numero(limpia.get("FTHG")),
            "goles_visitante": _numero(limpia.get("FTAG")),
            "resultado": {"H": "local", "D": "empate", "A": "visitante"}.get(limpia.get("FTR")),
            "descanso": (_numero(limpia.get("HTHG")), _numero(limpia.get("HTAG"))),
            "tiros": (_numero(limpia.get("HS")), _numero(limpia.get("AS"))),
            "tiros_a_puerta": (_numero(limpia.get("HST")), _numero(limpia.get("AST"))),
            "corners": (_numero(limpia.get("HC")), _numero(limpia.get("AC"))),
            "faltas": (_numero(limpia.get("HF")), _numero(limpia.get("AF"))),
            "amarillas": (_numero(limpia.get("HY")), _numero(limpia.get("AY"))),
            "rojas": (_numero(limpia.get("HR")), _numero(limpia.get("AR"))),
            "arbitro": limpia.get("Referee") or None,
            "casa": casa,
            "cuotas": cuotas,
            "probabilidades": probs,
            "favorito": favorito(probs) if probs else None,
            "mas_de_2_5": _numero(limpia.get("AvgC>2.5") or limpia.get("Avg>2.5")),
        }

    @staticmethod
    def _cuotas(fila: dict) -> tuple[dict | None, str | None]:
        """El 1X2 de cierre de la primera casa que lo traiga completo.

        Las columnas con ``C`` (``AvgCH``) son las de cierre; sin ``C``, las de
        apertura. Se prefiere el cierre, que ya incorpora las alineaciones.
        """
        for prefijo, nombre in CASAS:
            for sufijo, etiqueta in (("C", "cierre"), ("", "apertura")):
                cuotas = {lado: _numero(fila.get(f"{prefijo}{sufijo}{letra}"))
                          for lado, letra in (("local", "H"), ("empate", "D"),
                                              ("visitante", "A"))}
                if all(isinstance(v, (int, float)) and v > 1 for v in cuotas.values()):
                    return {k: float(v) for k, v in cuotas.items()}, f"{nombre} ({etiqueta})"
        return None, None


def rellenar_cuotas(almacen, fuente: FutbolData | None = None, liga_id: int | None = None,
                    maximo: int = 0, avisar=None) -> dict:
    """Pone cuotas a los partidos guardados que no las tienen.

    Recorre la memoria liga a liga y temporada a temporada, pide cada CSV una
    sola vez y empareja partido a partido. Es lo que hace que el desglose por
    favorito funcione también con lo barrido antes de que se pidieran cuotas.
    """
    from ..models import Event
    from ..previa import _evento_desde_fila
    from ..sources.cruce import temporada_de

    decir = avisar or (lambda _t: None)
    fuente = fuente or FutbolData()
    sql = """SELECT p.* FROM partidos p LEFT JOIN cuotas c ON c.partido_id = p.id
             WHERE c.partido_id IS NULL AND p.estado = 'finished'"""
    parametros: tuple = ()
    if liga_id:
        sql += " AND p.liga_id = ?"
        parametros = (liga_id,)
    filas = almacen.consulta(sql + " ORDER BY p.momento DESC", parametros)

    resumen = {"candidatos": 0, "rellenados": 0, "sin_cobertura": 0, "no_encontrados": 0,
               "fallos": []}
    temporadas_fallidas: set[tuple[str, int]] = set()
    for fila in filas:
        if maximo and resumen["rellenados"] >= maximo:
            break
        codigo = CODIGOS.get(fila.get("liga_id") or 0)
        if not codigo:
            resumen["sin_cobertura"] += 1
            continue
        evento: Event = _evento_desde_fila(fila)
        año = temporada_de(evento)
        if not año or (codigo, año) in temporadas_fallidas:
            resumen["no_encontrados"] += 1
            continue
        resumen["candidatos"] += 1
        try:
            bloque = fuente.cuotas_de(evento)
        except Exception as exc:  # noqa: BLE001 - una temporada que falle no para el resto
            temporadas_fallidas.add((codigo, año))
            resumen["fallos"].append(f"{codigo} {año}: {exc}")
            decir(f"  {codigo} {año}: {exc}")
            continue
        if not bloque:
            resumen["no_encontrados"] += 1
            continue
        almacen.guardar_cuotas(evento.id, bloque, fuente="futboldata")
        resumen["rellenados"] += 1
        decir(f"  {evento.home.name} - {evento.away.name} ({evento.date}): "
              f"{bloque['favorito']['lectura']}")
    almacen._conexion.commit()
    return resumen


__all__ = ["FutbolData", "rellenar_cuotas", "CODIGOS", "ALIAS", "CASAS"]
