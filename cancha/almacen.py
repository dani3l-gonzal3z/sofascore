"""La memoria: una base local con todo lo que se va viendo.

Hasta aquí el framework pedía un partido y lo devolvía. Para decir cosas como
«este equipo lleva cinco partidos sin rematar entre palos desde fuera del área»
o «este árbitro pita el doble de penaltis en casa» hace falta algo que no
teníamos: **acordarse**.

Esto es una base SQLite —biblioteca estándar, ni un paquete más— con lo que se
va trayendo. Lo importante no es guardar, es que **guardar sea idempotente**:
un barrido se puede repetir mil veces y el resultado es el mismo, así que se
puede cortar a mitad y seguir mañana.

    almacen = Almacen("datos/cancha.db")
    almacen.guardar_informe(informe)
    almacen.partidos_de_equipo(2829, ultimos=6)

Las estadísticas se guardan **desnormalizadas a filas** (partido, periodo,
clave, local, visitante) en vez de en columnas: la API añade y quita claves
según el deporte y la competición, y una tabla ancha se rompería con la
primera.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Sube cuando el esquema cambia de forma incompatible.
VERSION_ESQUEMA = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidos (
    id              INTEGER PRIMARY KEY,
    custom_id       TEXT,
    fecha           TEXT,
    momento         INTEGER,
    deporte         TEXT,
    liga_id         INTEGER,
    liga            TEXT,
    temporada_id    INTEGER,
    jornada         INTEGER,
    local_id        INTEGER,
    local           TEXT,
    visitante_id    INTEGER,
    visitante       TEXT,
    goles_local     INTEGER,
    goles_visitante INTEGER,
    estado          TEXT,
    arbitro         TEXT,
    sede            TEXT,
    visto_en        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_partidos_fecha ON partidos(fecha);
CREATE INDEX IF NOT EXISTS idx_partidos_liga ON partidos(liga_id, temporada_id);
CREATE INDEX IF NOT EXISTS idx_partidos_local ON partidos(local_id);
CREATE INDEX IF NOT EXISTS idx_partidos_visitante ON partidos(visitante_id);
CREATE INDEX IF NOT EXISTS idx_partidos_arbitro ON partidos(arbitro);

CREATE TABLE IF NOT EXISTS estadisticas (
    partido_id  INTEGER NOT NULL,
    periodo     TEXT NOT NULL,
    grupo       TEXT,
    clave       TEXT NOT NULL,
    nombre      TEXT,
    local       REAL,
    visitante   REAL,
    local_txt   TEXT,
    visitante_txt TEXT,
    PRIMARY KEY (partido_id, periodo, clave),
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS actuaciones (
    partido_id  INTEGER NOT NULL,
    jugador_id  INTEGER NOT NULL,
    jugador     TEXT,
    equipo_id   INTEGER,
    posicion    TEXT,
    dorsal      INTEGER,
    titular     INTEGER,
    minutos     INTEGER,
    rating      REAL,
    datos       TEXT,
    PRIMARY KEY (partido_id, jugador_id),
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_actuaciones_jugador ON actuaciones(jugador_id);
CREATE INDEX IF NOT EXISTS idx_actuaciones_equipo ON actuaciones(equipo_id);

CREATE TABLE IF NOT EXISTS tiros (
    partido_id   INTEGER NOT NULL,
    orden        INTEGER NOT NULL,
    jugador_id   INTEGER,
    jugador      TEXT,
    equipo_id    INTEGER,
    local        INTEGER,
    minuto       INTEGER,
    xg           REAL,
    xgot         REAL,
    resultado    TEXT,
    situacion    TEXT,
    parte_cuerpo TEXT,
    PRIMARY KEY (partido_id, orden),
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tiros_jugador ON tiros(jugador_id);
CREATE INDEX IF NOT EXISTS idx_tiros_equipo ON tiros(equipo_id);

CREATE TABLE IF NOT EXISTS incidencias (
    partido_id  INTEGER NOT NULL,
    orden       INTEGER NOT NULL,
    minuto      INTEGER,
    tipo        TEXT,
    clase       TEXT,
    local       INTEGER,
    jugador     TEXT,
    jugador_id  INTEGER,
    PRIMARY KEY (partido_id, orden),
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_incidencias_tipo ON incidencias(tipo);

CREATE TABLE IF NOT EXISTS anotaciones (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);
"""


def _numero(valor: Any) -> float | None:
    """Saca el número de un valor de la API: ``"56%"`` o ``"40/72 (56%)"``."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if not isinstance(valor, str):
        return None
    encontrado = re.search(r"-?\d+(?:[.,]\d+)?", valor.replace(",", "."))
    return float(encontrado.group()) if encontrado else None


@dataclass
class Almacen:
    """La base local. Abrirla la crea si no está."""

    ruta: str | Path = "datos/cancha.db"

    def __post_init__(self) -> None:
        self.ruta = Path(self.ruta)
        if str(self.ruta) != ":memory:":
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._conexion = sqlite3.connect(str(self.ruta))
        self._conexion.row_factory = sqlite3.Row
        self._conexion.executescript(ESQUEMA)
        self._conexion.execute("PRAGMA foreign_keys = ON")
        self.anotar("version_esquema", str(VERSION_ESQUEMA))

    # --- contexto ---

    def __enter__(self) -> Almacen:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        with suppress(sqlite3.Error):
            self._conexion.commit()
            self._conexion.close()

    # --- escribir ---

    def guardar_evento(self, evento) -> int:
        """Guarda la cabecera de un partido. Repetirlo lo actualiza."""
        self._conexion.execute(
            """INSERT INTO partidos (id, custom_id, fecha, momento, deporte, liga_id, liga,
                   temporada_id, jornada, local_id, local, visitante_id, visitante,
                   goles_local, goles_visitante, estado, arbitro, sede)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   goles_local=excluded.goles_local,
                   goles_visitante=excluded.goles_visitante,
                   estado=excluded.estado,
                   arbitro=COALESCE(NULLIF(excluded.arbitro,''), partidos.arbitro),
                   visto_en=CURRENT_TIMESTAMP""",
            (evento.id, evento.custom_id, evento.date, evento.start_timestamp,
             evento.sport, evento.unique_tournament_id, evento.tournament,
             evento.season_id, evento.round if isinstance(evento.round, int) else None,
             evento.home.id, evento.home.name, evento.away.id, evento.away.name,
             evento.home_score.current, evento.away_score.current,
             evento.status_type, evento.referee, evento.venue),
        )
        return evento.id

    def guardar_informe(self, informe) -> dict:
        """Guarda todo lo que traiga un informe de partido.

        Devuelve cuántas filas ha metido de cada cosa, para poder enseñar
        progreso durante un barrido largo.
        """
        evento = informe.event
        self.guardar_evento(evento)
        cuenta = {"estadisticas": 0, "actuaciones": 0, "tiros": 0, "incidencias": 0}

        for fila in informe.statistics_table(periodo=""):
            self._conexion.execute(
                """INSERT OR REPLACE INTO estadisticas
                   (partido_id, periodo, grupo, clave, nombre, local, visitante,
                    local_txt, visitante_txt) VALUES (?,?,?,?,?,?,?,?,?)""",
                (evento.id, fila.get("periodo") or "ALL", fila.get("grupo"),
                 fila.get("clave"), fila.get("nombre"),
                 _numero(fila.get("local")), _numero(fila.get("visitante")),
                 str(fila.get("local", "")), str(fila.get("visitante", ""))),
            )
            cuenta["estadisticas"] += 1

        for jugador in informe.players():
            if not jugador.id:
                continue
            estadisticas = (jugador.raw or {}).get("statistics") or {}
            self._conexion.execute(
                """INSERT OR REPLACE INTO actuaciones
                   (partido_id, jugador_id, jugador, equipo_id, posicion, dorsal,
                    titular, minutos, rating, datos) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (evento.id, jugador.id, jugador.name, jugador.team_id,
                 jugador.position, jugador.shirt_number,
                 0 if jugador.substitute else 1,
                 estadisticas.get("minutesPlayed"), estadisticas.get("rating"),
                 json.dumps(estadisticas, ensure_ascii=False)),
            )
            cuenta["actuaciones"] += 1

        for orden, tiro in enumerate(informe.shots()):
            jugador = tiro.get("player") or {}
            es_local = bool(tiro.get("isHome"))
            self._conexion.execute(
                """INSERT OR REPLACE INTO tiros
                   (partido_id, orden, jugador_id, jugador, equipo_id, local, minuto,
                    xg, xgot, resultado, situacion, parte_cuerpo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evento.id, orden, jugador.get("id"), jugador.get("name"),
                 evento.home.id if es_local else evento.away.id, int(es_local),
                 tiro.get("time"), tiro.get("xg"), tiro.get("xgot"),
                 tiro.get("shotType"), tiro.get("situation"), tiro.get("bodyPart")),
            )
            cuenta["tiros"] += 1

        for orden, incidencia in enumerate(informe.incidents()):
            jugador = (incidencia.get("player") or incidencia.get("playerIn") or {})
            self._conexion.execute(
                """INSERT OR REPLACE INTO incidencias
                   (partido_id, orden, minuto, tipo, clase, local, jugador, jugador_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (evento.id, orden, incidencia.get("time"),
                 incidencia.get("incidentType"), incidencia.get("incidentClass"),
                 None if incidencia.get("isHome") is None else int(incidencia["isHome"]),
                 jugador.get("name"), jugador.get("id")),
            )
            cuenta["incidencias"] += 1

        self._conexion.commit()
        return cuenta

    def anotar(self, clave: str, valor: str) -> None:
        """Deja una nota (última fecha barrida, versión del esquema...)."""
        self._conexion.execute(
            "INSERT OR REPLACE INTO anotaciones (clave, valor) VALUES (?,?)",
            (clave, str(valor)),
        )
        self._conexion.commit()

    def nota(self, clave: str, por_defecto: str = "") -> str:
        fila = self._conexion.execute(
            "SELECT valor FROM anotaciones WHERE clave = ?", (clave,)
        ).fetchone()
        return fila["valor"] if fila else por_defecto

    # --- leer ---

    def consulta(self, sql: str, parametros: tuple = ()) -> list[dict]:
        """Una consulta cualquiera, devuelta como lista de diccionarios."""
        with closing(self._conexion.execute(sql, parametros)) as cursor:
            return [dict(fila) for fila in cursor.fetchall()]

    def tiene(self, partido_id: int, con_estadisticas: bool = True) -> bool:
        """¿Está ya guardado este partido? Lo que evita rebajar el mismo dato."""
        if not con_estadisticas:
            return bool(self.consulta("SELECT 1 FROM partidos WHERE id = ?", (partido_id,)))
        return bool(self.consulta(
            "SELECT 1 FROM estadisticas WHERE partido_id = ? LIMIT 1", (partido_id,)))

    def partidos_de_equipo(self, equipo_id: int, ultimos: int = 6,
                           antes_de: str | None = None) -> list[dict]:
        """Los últimos partidos jugados de un equipo, del más reciente atrás."""
        sql = """SELECT * FROM partidos
                 WHERE (local_id = ? OR visitante_id = ?) AND estado = 'finished'"""
        parametros: tuple = (equipo_id, equipo_id)
        if antes_de:
            sql += " AND fecha < ?"
            parametros += (antes_de,)
        sql += " ORDER BY momento DESC LIMIT ?"
        return self.consulta(sql, parametros + (ultimos,))

    def actuaciones_de_jugador(self, jugador_id: int, ultimas: int = 6) -> list[dict]:
        """Lo que ha hecho un jugador en sus últimos partidos."""
        return self.consulta(
            """SELECT a.*, p.fecha, p.liga, p.local, p.visitante, p.momento
               FROM actuaciones a JOIN partidos p ON p.id = a.partido_id
               WHERE a.jugador_id = ?
               ORDER BY p.momento DESC LIMIT ?""",
            (jugador_id, ultimas),
        )

    def partidos_de_arbitro(self, arbitro: str, ultimos: int = 20) -> list[dict]:
        """Los partidos que ha pitado alguien, de los que estén guardados."""
        return self.consulta(
            """SELECT * FROM partidos WHERE arbitro = ? AND estado = 'finished'
               ORDER BY momento DESC LIMIT ?""",
            (arbitro, ultimos),
        )

    def estadisticas_de_partidos(self, partido_ids: list[int],
                                 claves: list[str] | None = None,
                                 periodo: str = "ALL") -> list[dict]:
        """Estadísticas de varios partidos de una vez, para promediar."""
        if not partido_ids:
            return []
        huecos = ",".join("?" * len(partido_ids))
        sql = (f"SELECT e.*, p.local_id, p.visitante_id FROM estadisticas e "
               f"JOIN partidos p ON p.id = e.partido_id "
               f"WHERE e.partido_id IN ({huecos}) AND e.periodo = ?")
        parametros = (*partido_ids, periodo)
        if claves:
            sql += f" AND e.clave IN ({','.join('?' * len(claves))})"
            parametros += tuple(claves)
        return self.consulta(sql, parametros)

    def resumen(self) -> dict:
        """Qué hay dentro. Lo primero que se mira cuando algo no cuadra."""
        def cuantos(tabla: str) -> int:
            return self.consulta(f"SELECT COUNT(*) AS n FROM {tabla}")[0]["n"]

        rango = self.consulta(
            "SELECT MIN(fecha) AS desde, MAX(fecha) AS hasta FROM partidos")[0]
        ligas = self.consulta(
            """SELECT liga, COUNT(*) AS partidos FROM partidos
               WHERE liga IS NOT NULL GROUP BY liga ORDER BY partidos DESC""")
        return {
            "ruta": str(self.ruta),
            "partidos": cuantos("partidos"),
            "con_estadisticas": self.consulta(
                "SELECT COUNT(DISTINCT partido_id) AS n FROM estadisticas")[0]["n"],
            "actuaciones": cuantos("actuaciones"),
            "tiros": cuantos("tiros"),
            "desde": rango["desde"],
            "hasta": rango["hasta"],
            "ligas": {f["liga"]: f["partidos"] for f in ligas},
            "ultimo_barrido": self.nota("ultimo_barrido", "nunca"),
        }


__all__ = ["Almacen", "VERSION_ESQUEMA"]
