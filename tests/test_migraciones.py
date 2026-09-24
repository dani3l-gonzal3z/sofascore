"""Que una memoria de ayer se abra hoy sin perder nada.

Nadie debería tener que borrar sus partidos y volver a barrer porque el esquema
creció. Aquí se fabrica una base con la forma antigua, se abre con el código de
hoy y se comprueba fila por fila.

El caso difícil es `predicciones`: pasó de `UNIQUE (partido, mercado, selección)`
a incluir el **autor**, y SQLite no sabe cambiar una restricción. Hay que rehacer
la tabla, y rehacer una tabla con datos dentro es donde se pierden los datos.
"""

from __future__ import annotations

import sqlite3

import pytest

from cancha.almacen import DDL_PREDICCIONES, VERSION_ESQUEMA, Almacen
from cancha.registro import AUTOR_CALCULO

#: `predicciones` tal y como era antes de que existiera el autor.
ESQUEMA_VIEJO = """
PRAGMA foreign_keys = OFF;
DROP TABLE predicciones;
CREATE TABLE predicciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, partido_id INTEGER NOT NULL, fecha TEXT,
    hecha_el TEXT DEFAULT CURRENT_TIMESTAMP, horas_antes REAL, version TEXT,
    mercado TEXT NOT NULL, seleccion TEXT NOT NULL, probabilidad REAL NOT NULL,
    prob_mercado REAL, resuelto INTEGER DEFAULT 0, acerto INTEGER, valor_real TEXT,
    prob_cierre REAL, resuelto_el TEXT,
    UNIQUE (partido_id, mercado, seleccion),
    FOREIGN KEY (partido_id) REFERENCES partidos(id) ON DELETE CASCADE);
INSERT INTO predicciones (partido_id, fecha, mercado, seleccion, probabilidad,
                          prob_mercado, resuelto, acerto, version)
  VALUES (1,'2026-09-20','1x2','local',0.55,0.5,1,1,'poisson-encogido-1'),
         (1,'2026-09-20','1x2','empate',0.25,0.27,1,0,'poisson-encogido-1'),
         (1,'2026-09-20','mas_2_5','si',0.52,NULL,1,1,'poisson-encogido-1'),
         (2,'2026-09-21','1x2','visitante',0.4,0.38,0,NULL,'poisson-encogido-1');
CREATE INDEX idx_predicciones_fecha ON predicciones(fecha);
CREATE INDEX idx_predicciones_resuelto ON predicciones(resuelto);
UPDATE anotaciones SET valor='7' WHERE clave='version_esquema';
"""


@pytest.fixture
def de_ayer(tmp_path):
    """Una base real, con la `predicciones` de antes del autor."""
    ruta = tmp_path / "ayer.db"
    with Almacen(str(ruta)) as base:
        base._conexion.executescript(
            "INSERT INTO partidos (id,fecha) VALUES (1,'2026-09-20'), (2,'2026-09-21');"
            "INSERT INTO dictamenes (partido_id, respuesta, modelo)"
            " VALUES (1, 'Lo veo claro', 'grande');")
        base._conexion.commit()
    crudo = sqlite3.connect(str(ruta))
    crudo.executescript(ESQUEMA_VIEJO)
    crudo.commit()
    crudo.close()
    return str(ruta)


def test_no_se_pierde_ninguna_prediccion(de_ayer):
    with Almacen(de_ayer) as base:
        filas = base.consulta("SELECT * FROM predicciones ORDER BY id")
    assert len(filas) == 4
    assert [f["mercado"] for f in filas] == ["1x2", "1x2", "mas_2_5", "1x2"]
    assert [f["acerto"] for f in filas] == [1, 0, 1, None], "lo resuelto sigue resuelto"
    assert [f["prob_mercado"] for f in filas] == [0.5, 0.27, None, 0.38]


def test_lo_que_habia_pasa_a_ser_del_calculo(de_ayer):
    """Era del Poisson: eso es lo que se le pone, sin inventar un autor."""
    with Almacen(de_ayer) as base:
        autores = {f["autor"] for f in base.consulta("SELECT autor FROM predicciones")}
    assert autores == {AUTOR_CALCULO}


def test_ahora_dos_autores_pueden_opinar_del_mismo_mercado(de_ayer):
    """Es justo lo que el UNIQUE de antes impedía, y de lo que se trata."""
    with Almacen(de_ayer) as base:
        base._conexion.execute(
            "INSERT INTO predicciones (partido_id,fecha,autor,mercado,seleccion,"
            "probabilidad) VALUES (1,'2026-09-20','el-escéptico','1x2','local',0.62)")
        base._conexion.commit()
        dos = base.consulta(
            "SELECT autor, probabilidad FROM predicciones WHERE partido_id=1"
            " AND mercado='1x2' AND seleccion='local' ORDER BY autor")
    assert [(d["autor"], d["probabilidad"]) for d in dos] == [
        (AUTOR_CALCULO, 0.55), ("el-escéptico", 0.62)]


def test_el_mismo_autor_no_se_duplica(de_ayer):
    """Y lo que sí tiene que seguir impidiendo: predecir dos veces lo mismo."""
    with Almacen(de_ayer) as base:
        cursor = base._conexion.execute(
            "INSERT OR IGNORE INTO predicciones (partido_id,fecha,autor,mercado,"
            "seleccion,probabilidad) VALUES (1,'2026-09-20','calculo','1x2','local',0.9)")
        assert cursor.rowcount == 0
        fila = base.consulta("SELECT probabilidad FROM predicciones WHERE partido_id=1"
                             " AND autor='calculo' AND mercado='1x2' AND seleccion='local'")
    assert fila[0]["probabilidad"] == 0.55, "la primera es la que cuenta"


def test_los_dictamenes_sobreviven_y_ganan_sus_columnas(de_ayer):
    with Almacen(de_ayer) as base:
        assert len(base.consulta("SELECT * FROM dictamenes")) == 1
        columnas = {f["name"] for f in base.consulta("PRAGMA table_info(dictamenes)")}
    assert {"agente", "pasos", "sin_numeros"} <= columnas


def test_abrirla_dos_veces_no_vuelve_a_migrar(de_ayer):
    """Una migración que se repite es una migración que duplica o borra."""
    with Almacen(de_ayer) as base:
        base._conexion.execute(
            "INSERT INTO predicciones (partido_id,fecha,autor,mercado,seleccion,"
            "probabilidad) VALUES (2,'2026-09-21','otro','1x2','local',0.5)")
        base._conexion.commit()
    with Almacen(de_ayer) as base:
        assert len(base.consulta("SELECT * FROM predicciones")) == 5
        assert base.nota("version_esquema") == str(VERSION_ESQUEMA)


def test_una_base_nueva_ya_nace_con_el_autor(tmp_path):
    with Almacen(str(tmp_path / "hoy.db")) as base:
        columnas = {f["name"] for f in base.consulta("PRAGMA table_info(predicciones)")}
    assert "autor" in columnas


def indices_de(ruta: str) -> set[str]:
    crudo = sqlite3.connect(ruta)
    try:
        return {f[0] for f in crudo.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='predicciones' AND name NOT LIKE 'sqlite_%'")}
    finally:
        crudo.close()


def test_la_tabla_rehecha_conserva_sus_indices(de_ayer):
    """Rehacer una tabla se lleva sus índices por delante, y no avisa.

    `ALTER TABLE ... RENAME` **no** renombra los índices: se quedan con el nombre
    viejo colgados de la tabla vieja. Así que un `CREATE INDEX IF NOT EXISTS` con
    ese mismo nombre no hace nada —ya existe—, y el `DROP TABLE` se lo lleva. La
    tabla se quedaba sin un solo índice y la única señal era que todo iba lento.
    """
    assert indices_de(de_ayer) == {"idx_predicciones_fecha", "idx_predicciones_resuelto"}
    with Almacen(de_ayer):
        pass
    assert indices_de(de_ayer) == {"idx_predicciones_fecha", "idx_predicciones_resuelto",
                                   "idx_predicciones_autor"}


def test_una_migracion_cortada_por_la_mitad_se_reanuda(de_ayer):
    """Si el proceso muere rehaciendo la tabla, las filas no se quedan huérfanas.

    Es un momento verosímil: un Ctrl-C al arrancar `cancha web`. Lo que había
    pasaba a `predicciones_vieja`, la nueva quedaba vacía y —porque ya tenía la
    columna `autor`— la siguiente apertura se daba por migrada y nadie volvía a
    mirar ahí. Las predicciones estaban en la base, invisibles para siempre.
    """
    with Almacen(de_ayer):
        pass
    crudo = sqlite3.connect(de_ayer)
    crudo.execute("ALTER TABLE predicciones RENAME TO predicciones_vieja")
    crudo.executescript(DDL_PREDICCIONES.format(tabla="predicciones"))
    crudo.commit()
    assert crudo.execute("SELECT COUNT(*) FROM predicciones").fetchone()[0] == 0
    crudo.close()

    with Almacen(de_ayer) as base:
        assert len(base.consulta("SELECT * FROM predicciones")) == 4
        assert not base.consulta("SELECT 1 FROM sqlite_master "
                                 "WHERE name='predicciones_vieja'")
