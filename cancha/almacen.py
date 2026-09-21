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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Sube cuando el esquema cambia de forma incompatible.
VERSION_ESQUEMA = 8

#: El DDL de `predicciones`, aparte del resto del esquema y con un hueco para el
#: nombre de la tabla, porque lo necesitan dos sitios: `ESQUEMA`, que la crea en
#: una base nueva, y la migración del autor, que la rehace. Escribirlo dos veces
#: es exactamente cómo se acaba con una tabla vieja y una nueva que ya no son la
#: misma tabla.
DDL_PREDICCIONES = """
-- El registro: lo que se predijo, cuándo, y cómo acabó. Es la tabla que
-- convierte esto en algo que se puede juzgar. Una predicción se escribe **antes**
-- del partido y no se toca nunca más: lo único que se rellena después es el
-- resultado. Un historial que se puede reescribir no vale nada.
CREATE TABLE IF NOT EXISTS {tabla} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    partido_id      INTEGER NOT NULL,
    fecha           TEXT,            -- la del partido
    hecha_el        TEXT DEFAULT CURRENT_TIMESTAMP,
    horas_antes     REAL,            -- cuánto faltaba para el saque
    version         TEXT,            -- con qué cálculo se hizo
    -- Quién la hizo: «cálculo» (el Poisson), «mercado» (las cuotas) o el nombre
    -- de un agente. Es lo que convierte el registro en una clasificación: la
    -- misma vara de medir para todos, sobre los mismos partidos.
    autor           TEXT NOT NULL,
    mercado         TEXT NOT NULL,   -- 1x2, mas_2_5, ambos_marcan, corners, tarjetas…
    seleccion       TEXT NOT NULL,   -- local, empate, visitante, si, no, "2-1"
    probabilidad    REAL NOT NULL,   -- la nuestra
    prob_mercado    REAL,            -- la del mercado cuando se predijo, si la había
    -- Lo que se rellena al resolver:
    resuelto        INTEGER DEFAULT 0,
    acerto          INTEGER,
    valor_real      TEXT,            -- el marcador, los córners, lo que toque
    prob_cierre     REAL,            -- el mercado en la última cuota vista
    resuelto_el     TEXT,
    UNIQUE (partido_id, autor, mercado, seleccion),
    -- OJO: por este CASCADE, un `INSERT OR REPLACE` sobre `partidos` borraría
    -- las predicciones de ese partido —REPLACE borra la fila y la vuelve a
    -- escribir—. El barrido guarda los partidos cada noche, así que ahí se usa
    -- `ON CONFLICT(id) DO UPDATE`, que actualiza sin borrar. No lo cambies.
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);
"""

#: Sus índices, aparte, por un detalle que muerde en silencio: `ALTER TABLE ...
#: RENAME` **no** renombra los índices de la tabla. Durante la migración los
#: nombres viejos siguen ocupados por índices colgados de la tabla vieja, así que
#: un `CREATE INDEX IF NOT EXISTS` no haría nada y el `DROP` se los llevaría: la
#: tabla se quedaría sin índices y nadie se enteraría. Por eso se crean **después**
#: de tirar la tabla vieja, y por eso tienen que estar aquí y no dentro del texto.
INDICES_PREDICCIONES = (
    "CREATE INDEX IF NOT EXISTS idx_predicciones_fecha ON predicciones(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_predicciones_resuelto ON predicciones(resuelto)",
    # Este es nuevo: la clasificación filtra por autor en cada consulta.
    "CREATE INDEX IF NOT EXISTS idx_predicciones_autor ON predicciones(autor, resuelto)",
)

_ESQUEMA_ANTES = """
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
    -- Se pidió el detalle y no había estadísticas. Pasa de verdad: categorías
    -- menores, partidos viejos, copas pequeñas. Sin esto, ese partido se queda
    -- para siempre en «falta por traer» y se vuelve a pedir cada vez que
    -- alguien abre la pantalla, gastando peticiones en algo que no existe.
    sin_estadisticas    INTEGER DEFAULT 0,
    formacion_local     TEXT,
    formacion_visitante TEXT,
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

CREATE TABLE IF NOT EXISTS cuotas (
    partido_id      INTEGER PRIMARY KEY,
    fuente          TEXT,
    mercado         TEXT,
    -- Cuándo se pidieron, y a cuántas horas del saque estaba el partido. Una
    -- cuota de tres días antes y una de cierre no valen lo mismo, y sin esto
    -- no hay manera de distinguirlas: la fila se sobrescribe y se pierde.
    visto_en        TEXT DEFAULT CURRENT_TIMESTAMP,
    horas_antes     REAL,
    local           REAL,
    empate          REAL,
    visitante       REAL,
    prob_local      REAL,
    prob_empate     REAL,
    prob_visitante  REAL,
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ligas (
    nombre      TEXT PRIMARY KEY,
    id          INTEGER,
    nombre_api  TEXT,
    pais        TEXT,
    genero      TEXT,
    grupo       TEXT,
    visto_en    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ligas_id ON ligas(id);
"""

_ESQUEMA_DESPUES = """

-- Lo que ha dicho un modelo sobre un partido. Se guarda entero y para siempre:
-- cuesta dinero (si va por la nube) y tiempo, y sobre todo es lo que dijo
-- **entonces**, con la memoria que había entonces. Volver mañana y encontrarlo
-- igual es la mitad de su valor; la otra mitad es poder comparar lo que dijo
-- con lo que pasó.
CREATE TABLE IF NOT EXISTS dictamenes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    partido_id      INTEGER NOT NULL,
    hecho_el        TEXT DEFAULT CURRENT_TIMESTAMP,
    modelo          TEXT,
    en_la_nube      INTEGER DEFAULT 0,
    pregunta        TEXT,
    respuesta       TEXT NOT NULL,
    -- El expediente que se le dio, entero. Sin esto no se puede saber con qué
    -- datos habló: el mismo partido con más memoria detrás da otro dictamen.
    expediente      TEXT,
    caracteres      INTEGER,
    tokens_prompt   INTEGER,
    tokens_respuesta INTEGER,
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dictamenes_partido ON dictamenes(partido_id);

CREATE TABLE IF NOT EXISTS anotaciones (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);"""

#: Los índices de `predicciones` **no** van aquí: `idx_predicciones_autor` no se
#: puede crear sobre una tabla vieja que todavía no tiene esa columna, y este
#: texto se ejecuta antes de migrar. Los crea `_indices_de_predicciones()` al
#: final de la migración, que es cuando la tabla ya tiene su forma definitiva.
ESQUEMA = (_ESQUEMA_ANTES + DDL_PREDICCIONES.format(tabla="predicciones")
           + _ESQUEMA_DESPUES)


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
        # Sin atar la conexión al hilo que la abrió: la interfaz web atiende
        # cada petición en un hilo y serializa el acceso con un cerrojo. Aun
        # así, **una conexión por cosa**: la web, la guardia y el bot abren la
        # suya. Compartir una sola entre hilos es pedir problemas, y el cerrojo
        # de la web no protege a quien no pasa por ella.
        self._conexion = sqlite3.connect(str(self.ruta), check_same_thread=False)
        self._conexion.row_factory = sqlite3.Row
        if str(self.ruta) != ":memory:":
            # WAL es justo la forma que tiene esto: uno escribiendo —la
            # guardia— y varios leyendo a la vez. Sin él, la guardia de las
            # tres de la mañana bloquea a quien abra la página en ese momento.
            # Y un tiempo de espera, para que coincidir sea esperar un poco y
            # no un «database is locked» en la cara.
            with suppress(sqlite3.DatabaseError):
                self._conexion.execute("PRAGMA journal_mode = WAL")
        self._conexion.execute("PRAGMA busy_timeout = 10000")
        self._conexion.executescript(ESQUEMA)
        self._conexion.execute("PRAGMA foreign_keys = ON")
        self._migrar()
        self.anotar("version_esquema", str(VERSION_ESQUEMA))

    def _migrar(self) -> None:
        """Añade las columnas que falten en una base creada por una versión vieja.

        SQLite no tiene un ALTER que sea idempotente, así que se mira antes qué
        columnas hay: nadie debería tener que borrar su memoria y volver a
        barrer porque el esquema creció.
        """
        columnas = {f["name"] for f in self.consulta("PRAGMA table_info(partidos)")}
        for columna in ("formacion_local", "formacion_visitante"):
            if columna not in columnas:
                self._conexion.execute(f"ALTER TABLE partidos ADD COLUMN {columna} TEXT")
        if "sin_estadisticas" not in columnas:
            self._conexion.execute(
                "ALTER TABLE partidos ADD COLUMN sin_estadisticas INTEGER DEFAULT 0")
        self._migrar_autor_de_predicciones()
        self._indices_de_predicciones()
        de_dictamenes = {f["name"] for f in self.consulta("PRAGMA table_info(dictamenes)")}
        for columna, tipo in (("agente", "TEXT"), ("pasos", "TEXT"),
                              ("sin_numeros", "INTEGER DEFAULT 0"),
                              ("segundos", "REAL"), ("en_sandwich", "INTEGER DEFAULT 0")):
            if columna not in de_dictamenes:
                self._conexion.execute(
                    f"ALTER TABLE dictamenes ADD COLUMN {columna} {tipo}")
        de_cuotas = {f["name"] for f in self.consulta("PRAGMA table_info(cuotas)")}
        if "visto_en" not in de_cuotas:
            self._conexion.execute("ALTER TABLE cuotas ADD COLUMN visto_en TEXT")
        if "horas_antes" not in de_cuotas:
            self._conexion.execute("ALTER TABLE cuotas ADD COLUMN horas_antes REAL")
        self._conexion.commit()

    def _indices_de_predicciones(self) -> None:
        """Los índices de `predicciones`, después de migrar y no antes.

        Van aquí por dos razones que se olvidan enseguida. Una: el de `autor` no
        se puede crear sobre una tabla que todavía no tiene esa columna, y el
        esquema se ejecuta antes de migrar. Y dos: `ALTER TABLE ... RENAME` **no**
        renombra los índices de la tabla, así que mientras la migración tenía la
        tabla vieja delante los nombres seguían ocupados y un `CREATE INDEX IF
        NOT EXISTS` no hacía nada; el `DROP` se los llevaba y la tabla se quedaba
        sin índices sin que nadie se enterara.
        """
        for sql in INDICES_PREDICCIONES:
            self._conexion.execute(sql)

    def _migrar_autor_de_predicciones(self) -> None:
        """Le añade el autor a `predicciones`, rehaciendo la tabla.

        SQLite no sabe cambiar una restricción `UNIQUE`, y aquí hay que hacerlo:
        pasa de `(partido, mercado, selección)` a `(partido, **autor**, mercado,
        selección)`, porque si no dos agentes no pueden opinar del mismo partido
        y el segundo se pierde en silencio. Rehacer la tabla es el camino que
        documenta SQLite, y se hace una sola vez: a partir de ahí `ESQUEMA` ya la
        crea con la forma nueva.

        Lo que había era del cálculo de Poisson, así que eso es lo que se le
        pone: no se inventa un autor ni se pierde una fila.

        Lo delicado de esto no es el SQL, es que se puede **cortar por la mitad**.
        Si el proceso muere entre el renombrado y el copiado, las predicciones se
        quedan en la tabla vieja y, como la tabla nueva ya tiene la columna
        `autor`, la siguiente apertura se da por migrada y nadie vuelve a mirar
        ahí. Por eso todo va en **una** transacción, por eso se entra también
        cuando existe la tabla vieja —una migración a medias se reanuda— y por
        eso el copiado es `OR IGNORE`: reanudar es repetir.
        """
        columnas = {f["name"] for f in self.consulta("PRAGMA table_info(predicciones)")}
        if not columnas:
            return
        a_medias = bool(self.consulta(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='predicciones_vieja'"))
        if "autor" in columnas and not a_medias:
            return

        # El PRAGMA de las claves ajenas es un no-op dentro de una transacción, y
        # no se queja: se queda como estaba. Así que primero se cierra lo que
        # haya abierto, y después se lee de vuelta para confirmar que ha calado.
        # Más vale no migrar que migrar con las claves puestas y la tabla a medias.
        self._conexion.commit()
        self._conexion.execute("PRAGMA foreign_keys = OFF")
        if self.consulta("PRAGMA foreign_keys")[0]["foreign_keys"]:
            raise sqlite3.DatabaseError(
                "No he podido apagar las claves ajenas para rehacer `predicciones`, "
                "así que no toco nada. Cierra lo que esté usando la memoria y "
                "vuelve a abrirla.")
        try:
            self._conexion.execute("BEGIN IMMEDIATE")
            if not a_medias:
                self._conexion.execute(
                    "ALTER TABLE predicciones RENAME TO predicciones_vieja")
                self._conexion.execute(DDL_PREDICCIONES.format(tabla="predicciones"))
            de_la_vieja = {f["name"] for f in
                           self.consulta("PRAGMA table_info(predicciones_vieja)")}
            viejas = [c for c in (
                "id", "partido_id", "fecha", "hecha_el", "horas_antes", "version",
                "mercado", "seleccion", "probabilidad", "prob_mercado", "resuelto",
                "acerto", "valor_real", "prob_cierre", "resuelto_el")
                if c in de_la_vieja]
            lista = ", ".join(viejas)
            # Los `id` se copian tal cual: es lo que hace que lo que ya apuntaba a
            # una fila siga apuntando a la misma. `AUTOINCREMENT` se recupera solo,
            # porque SQLite reconstruye su cuenta a partir del máximo que ve.
            self._conexion.execute(
                f"INSERT OR IGNORE INTO predicciones (autor, {lista}) "
                f"SELECT ?, {lista} FROM predicciones_vieja", ("calculo",))
            self._conexion.execute("DROP TABLE predicciones_vieja")
            self._conexion.execute("COMMIT")
        except BaseException:
            self._conexion.execute("ROLLBACK")
            raise
        finally:
            self._conexion.execute("PRAGMA foreign_keys = ON")

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

    def guardar_formaciones(self, partido_id: int, alineaciones: dict | None) -> None:
        """Guarda con qué dibujo salió cada equipo, si las alineaciones lo traen."""
        if not isinstance(alineaciones, dict):
            return
        local = (alineaciones.get("home") or {}).get("formation")
        visitante = (alineaciones.get("away") or {}).get("formation")
        if not (local or visitante):
            return
        self._conexion.execute(
            """UPDATE partidos SET
                   formacion_local = COALESCE(?, formacion_local),
                   formacion_visitante = COALESCE(?, formacion_visitante)
               WHERE id = ?""",
            (local, visitante, partido_id),
        )

    def guardar_cuotas(self, partido_id: int, datos: Any, fuente: str = "sofascore") -> bool:
        """Guarda el 1X2 de un partido, si la respuesta trae uno.

        Lo que se guarda son las cuotas y su probabilidad ya sin margen: es lo
        que hace falta para saber quién era favorito, que es para lo que sirven.
        """
        from .cuotas import extraer_1x2

        mercado = extraer_1x2(datos) if not (isinstance(datos, dict) and "cuotas" in datos
                                             and "probabilidades" in datos) else datos
        if not mercado:
            return False
        cuotas, probs = mercado["cuotas"], mercado["probabilidades"]
        self._conexion.execute(
            """INSERT OR REPLACE INTO cuotas
               (partido_id, fuente, mercado, visto_en, horas_antes, local, empate,
                visitante, prob_local, prob_empate, prob_visitante)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (partido_id, fuente, mercado.get("mercado"),
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             self._horas_antes(partido_id),
             cuotas.get("local"), cuotas.get("empate"), cuotas.get("visitante"),
             probs.get("local"), probs.get("empate"), probs.get("visitante")),
        )
        return True

    def _horas_antes(self, partido_id: int) -> float | None:
        """A cuántas horas del saque se pidieron estas cuotas.

        Es una sola columna y vale mucho: sin ella, una cuota de apertura y una
        de cierre son la misma fila y no hay forma de saber cuál tienes. Para
        cualquier cosa que se quiera entrenar algún día, la de cierre es la
        buena, porque es la que ya ha absorbido las alineaciones y las bajas.
        """
        filas = self.consulta("SELECT momento FROM partidos WHERE id = ?", (partido_id,))
        if not filas or not filas[0].get("momento"):
            return None
        ahora = datetime.now(timezone.utc).timestamp()
        return round((filas[0]["momento"] - ahora) / 3600, 2)

    def cuotas_de(self, partido_id: int) -> dict | None:
        """El 1X2 guardado de un partido, con quién era favorito."""
        from .cuotas import desde_fila

        filas = self.consulta("SELECT * FROM cuotas WHERE partido_id = ?", (partido_id,))
        return desde_fila(filas[0]) if filas else None

    def guardar_informe(self, informe) -> dict:
        """Guarda todo lo que traiga un informe de partido.

        Devuelve cuántas filas ha metido de cada cosa, para poder enseñar
        progreso durante un barrido largo.
        """
        evento = informe.event
        self.guardar_evento(evento)
        cuenta = {"estadisticas": 0, "actuaciones": 0, "tiros": 0, "incidencias": 0,
                  "cuotas": 0}

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

        self.guardar_formaciones(evento.id, informe.get("lineups"))
        for seccion in ("odds_featured", "odds"):
            if self.guardar_cuotas(evento.id, informe.get(seccion)):
                cuenta["cuotas"] = 1
                break

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

    def guardar_liga(self, competicion, identificador: int, entidad: dict | None = None) -> None:
        """Apunta qué id tiene una competición del catálogo.

        Lo guarda por su nombre del catálogo, no por el de la API: el nuestro
        no cambia y el suyo sí.
        """
        entidad = entidad or {}
        self._conexion.execute(
            """INSERT OR REPLACE INTO ligas
               (nombre, id, nombre_api, pais, genero, grupo, visto_en)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (competicion.nombre, int(identificador), entidad.get("name"),
             ((entidad.get("category") or {}).get("name")) or competicion.pais,
             competicion.genero, competicion.grupo),
        )
        self._conexion.commit()

    def ligas_aprendidas(self) -> list[dict]:
        """Las competiciones que se descubrieron, de la más reciente atrás."""
        return self.consulta("SELECT * FROM ligas ORDER BY visto_en DESC")

    def olvidar_ligas(self) -> int:
        """Borra lo descubierto, para volver a buscarlo."""
        cuantas = self.consulta("SELECT COUNT(*) AS n FROM ligas")[0]["n"]
        self._conexion.execute("DELETE FROM ligas")
        self._conexion.commit()
        return cuantas

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

    # --- dictámenes ---

    def guardar_dictamen(self, partido_id: int, respuesta: str, modelo: str = "",
                         pregunta: str = "", expediente: str = "",
                         en_la_nube: bool = False, tokens: dict | None = None,
                         agente: str = "", pasos: Any = None,
                         sin_numeros: bool = False, segundos: float | None = None,
                         en_sandwich: bool = False) -> int:
        """Guarda lo que ha dicho un modelo de un partido. Devuelve su id.

        No sustituye al anterior: se apilan. Pedir otro dictamen es querer otra
        opinión, no borrar la primera.

        `agente` es quién lo dijo, con el **mismo nombre** que lleva en
        `predicciones.autor`: es lo que permite leer en la misma frase lo que
        escribió y lo que acertó. `sin_numeros` marca el dictamen que no terminó
        dando probabilidades: se guarda igual, porque se lee, pero no puntúa.
        """
        cuentas = tokens or {}
        cursor = self._conexion.execute(
            """INSERT INTO dictamenes
               (partido_id, modelo, en_la_nube, pregunta, respuesta, expediente,
                caracteres, tokens_prompt, tokens_respuesta, agente, pasos,
                sin_numeros, segundos, en_sandwich)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (partido_id, modelo, 1 if en_la_nube else 0, pregunta, respuesta,
             expediente, len(expediente or ""), cuentas.get("prompt_eval_count"),
             cuentas.get("eval_count"), agente,
             json.dumps(pasos, ensure_ascii=False) if pasos else None,
             1 if sin_numeros else 0, segundos, 1 if en_sandwich else 0))
        self._conexion.commit()
        return int(cursor.lastrowid or 0)

    def dictamenes_de(self, partido_id: int, limite: int = 10,
                      con_expediente: bool = False) -> list[dict]:
        """Los dictámenes guardados de un partido, del más reciente atrás."""
        columnas = ("id, partido_id, hecho_el, modelo, en_la_nube, pregunta, "
                    "respuesta, caracteres, tokens_prompt, tokens_respuesta, "
                    "agente, pasos, sin_numeros, segundos, en_sandwich"
                    + (", expediente" if con_expediente else ""))
        return self.consulta(
            f"""SELECT {columnas} FROM dictamenes WHERE partido_id = ?
                ORDER BY hecho_el DESC, id DESC LIMIT ?""", (partido_id, limite))

    def borrar_dictamen(self, dictamen_id: int) -> bool:
        cursor = self._conexion.execute(
            "DELETE FROM dictamenes WHERE id = ?", (dictamen_id,))
        self._conexion.commit()
        return bool(cursor.rowcount)

    def sin_estadisticas(self, partido_id: int) -> bool:
        """¿Ya se pidió su detalle y resultó que no las tiene?

        Distinguir esto de «no lo he pedido todavía» es lo que impide volver a
        pedir eternamente algo que no existe.
        """
        filas = self.consulta(
            "SELECT sin_estadisticas FROM partidos WHERE id = ?", (partido_id,))
        return bool(filas and filas[0]["sin_estadisticas"])

    def marcar_sin_estadisticas(self, partido_id: int, si: bool = True) -> None:
        """Deja constancia de que se pidió y no había nada que guardar."""
        self._conexion.execute(
            "UPDATE partidos SET sin_estadisticas = ? WHERE id = ?",
            (1 if si else 0, partido_id))
        self._conexion.commit()

    def dado_por_hecho(self, partido_id: int) -> bool:
        """¿Está hecho? Con estadísticas, o pedido y sin ellas.

        Es la pregunta que hay que hacerse antes de volver a pedir algo: la otra
        —«¿tengo sus estadísticas?»— deja en bucle a los partidos que no tienen.
        """
        return self.tiene(partido_id) or self.sin_estadisticas(partido_id)

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
            "con_cuotas": cuantos("cuotas"),
            "desde": rango["desde"],
            "hasta": rango["hasta"],
            "ligas": {f["liga"]: f["partidos"] for f in ligas},
            "ultimo_barrido": self.nota("ultimo_barrido", "nunca"),
        }


__all__ = ["Almacen", "VERSION_ESQUEMA"]
