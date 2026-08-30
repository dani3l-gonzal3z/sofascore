"""La memoria: guardar, barrer y sacar perfiles de lo guardado.

Un almacén de mentira con varias jornadas inventadas, para poder comprobar lo
que ningún partido suelto permite ver: estilos, rachas y árbitros.
"""

from __future__ import annotations

import json

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from cancha.almacen import Almacen, _numero
from cancha.barrido import Progreso, agenda, guardar_partido, ligas_de
from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.match import build_report
from cancha.models import Event
from cancha.perfiles import estilo_de_equipo, forma_de_jugador, perfil_de_arbitro, rachas
from cancha.previa import previa, texto
from cancha.transport import FakeTransport


@pytest.fixture
def cliente():
    return SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, fallback_base_urls=()),
        transport=FakeTransport(rutas_por_defecto()), cache=MemoryCache(),
        sleep=lambda _s: None,
    )


@pytest.fixture
def almacen():
    with Almacen(":memory:") as base:
        yield base


def _liga_inventada(base: Almacen, jornadas: int = 12, con_balon: int = 100):
    """Una liga donde un equipo tiene mucho más el balón que los demás."""
    for n in range(1, jornadas + 1):
        local, visitante = (con_balon, 200 + n) if n % 2 else (200 + n, con_balon)
        base._conexion.execute(
            """INSERT OR REPLACE INTO partidos (id,fecha,momento,liga_id,liga,temporada_id,
               local_id,local,visitante_id,visitante,goles_local,goles_visitante,estado,arbitro)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (n, f"2026-08-{n:02d}", 1780000000 + n * 86400, 8, "LaLiga", 61643,
             local, "Balón FC" if local == con_balon else f"E{local}",
             visitante, "Balón FC" if visitante == con_balon else f"E{visitante}",
             2 if local == con_balon else 0, 0 if local == con_balon else 2,
             "finished", "César Soto Grado" if n % 2 else "Otro Árbitro"),
        )
        for clave, base_valor in (("ballPossession", 50), ("passes", 400),
                                  ("accurateLongBalls", 25), ("yellowCards", 2.5),
                                  ("fouls", 13), ("expectedGoals", 1.3),
                                  ("totalShotsOnGoal", 12)):
            mio = base_valor * (0.6 if clave == "accurateLongBalls" else 1.4)
            valores = (mio, base_valor) if local == con_balon else (base_valor, mio)
            base._conexion.execute(
                """INSERT OR REPLACE INTO estadisticas
                   (partido_id,periodo,clave,local,visitante) VALUES (?,?,?,?,?)""",
                (n, "ALL", clave, valores[0], valores[1]))
        # Un delantero que dejó de marcar a partir de la jornada 9.
        base._conexion.execute(
            """INSERT OR REPLACE INTO actuaciones
               (partido_id,jugador_id,jugador,equipo_id,titular,minutos,rating,datos)
               VALUES (?,?,?,?,?,?,?,?)""",
            (n, 999, "Delantero X", con_balon, 1, 90, 7.1,
             json.dumps({"goals": 1 if n <= 8 else 0, "totalShots": 3,
                         "onTargetScoringAttempt": 1 if n <= 8 else 0,
                         "expectedGoals": 0.45, "keyPass": 1})))
    base._conexion.commit()


# --------------------------------------------------------------------- almacén

def test_guardar_un_informe_y_repetirlo_da_lo_mismo(almacen, cliente):
    informe = build_report(cliente, EVENT_ID, sections=["all"])
    primero = almacen.guardar_informe(informe)
    segundo = almacen.guardar_informe(informe)
    assert primero == segundo
    assert almacen.resumen()["partidos"] == 1


def test_lo_guardado_se_puede_volver_a_leer(almacen, cliente):
    almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    partidos = almacen.partidos_de_equipo(2829)
    assert partidos and partidos[0]["local"] == "Real Madrid"
    assert almacen.tiene(EVENT_ID)


def test_saber_lo_que_ya_esta_es_lo_que_hace_reanudable(almacen, cliente):
    assert not almacen.tiene(EVENT_ID)
    almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    assert almacen.tiene(EVENT_ID)


@pytest.mark.parametrize("crudo,esperado", [
    ("56%", 56.0), ("40/72 (56%)", 40.0), (1.48, 1.48), ("-1.24", -1.24),
    ("94.3 km", 94.3), ("", None), (None, None), ("nada", None),
])
def test_los_valores_de_la_api_se_guardan_como_numeros(crudo, esperado):
    assert _numero(crudo) == esperado


def test_una_nota_sobrevive(almacen):
    almacen.anotar("ultimo_barrido", "2026-08-30")
    assert almacen.nota("ultimo_barrido") == "2026-08-30"
    assert almacen.nota("no_existe", "vacío") == "vacío"


# --------------------------------------------------------------------- barrido

def test_los_grupos_de_ligas_resuelven_a_ids():
    assert ligas_de(["grandes"]) == {
        8: "Spain La Liga", 17: "England Premier League", 23: "Italy Serie A",
        35: "Germany Bundesliga", 34: "France Ligue 1",
    }
    assert len(ligas_de()) > 20


def test_una_liga_suelta_por_nombre_tambien_vale():
    assert 7 in ligas_de(["champions"])


def test_la_agenda_filtra_por_competicion(cliente):
    partidos = agenda(cliente, "2024-10-26", ["grandes"])
    assert partidos and all(e.unique_tournament_id == 8 for e in partidos)
    assert agenda(cliente, "2024-10-26", ["americas"]) == []


def test_un_partido_ya_guardado_no_se_vuelve_a_pedir(almacen, cliente):
    evento = cliente.event(EVENT_ID)
    progreso = Progreso()
    assert guardar_partido(cliente, almacen, evento, progreso) is True
    peticiones = cliente.stats.requests
    assert guardar_partido(cliente, almacen, evento, progreso) is False
    assert cliente.stats.requests == peticiones
    assert progreso.ya_estaban == 1


def test_un_partido_sin_jugar_se_guarda_pero_no_se_pide_su_detalle(almacen, cliente):
    evento = Event.from_api({"id": 5, "status": {"type": "notstarted"},
                             "homeTeam": {"id": 1, "name": "A"},
                             "awayTeam": {"id": 2, "name": "B"}})
    progreso = Progreso()
    assert guardar_partido(cliente, almacen, evento, progreso) is False
    assert almacen.tiene(5, con_estadisticas=False)


# --------------------------------------------------------------------- perfiles

def test_el_estilo_compara_con_la_liga_y_no_consigo_mismo(almacen):
    _liga_inventada(almacen)
    estilo = estilo_de_equipo(almacen, 100)
    rasgos = {r["dimension"] for r in estilo["lo_que_le_distingue"]}
    assert "posesion" in rasgos
    assert "pases_largos" in rasgos
    # 1.4 veces la media del resto, no 1.4 veces una media que le incluye.
    assert estilo["dimensiones"]["posesion"]["diferencia"] == pytest.approx(0.4, abs=0.01)


def test_el_estilo_dice_lo_que_concede(almacen):
    _liga_inventada(almacen)
    assert estilo_de_equipo(almacen, 100)["concede"]["xg"] > 0


def test_sin_partidos_guardados_lo_dice_en_vez_de_inventar(almacen):
    salida = estilo_de_equipo(almacen, 12345)
    assert salida["disponible"] is False
    assert "barrido" in salida["nota"]


def test_la_racha_de_resultados_va_del_mas_reciente_al_mas_viejo(almacen):
    _liga_inventada(almacen)
    racha = estilo_de_equipo(almacen, 100)["resultados"]["racha"]
    assert len(racha) == 6
    assert set(racha) <= set("GEP")


# --------------------------------------------------------------------- jugadores

def test_detecta_cuantos_partidos_lleva_sin_marcar(almacen):
    _liga_inventada(almacen)
    forma = forma_de_jugador(almacen, 999, ultimas=6)
    rachas_vistas = {r["racha"] for r in forma["rachas"]}
    assert "4 partidos sin marcar" in rachas_vistas
    assert "4 partidos sin tirar entre palos" in rachas_vistas


def test_una_racha_solo_cuenta_partidos_jugados():
    """Cinco sin marcar no vale si en tres se quedó en el banquillo."""
    partidos = [
        {"minutos": 0, "titular": False, "goles": 0, "fecha": "2026-08-10"},
        {"minutos": 90, "titular": True, "goles": 0, "fecha": "2026-08-09"},
        {"minutos": 90, "titular": True, "goles": 0, "fecha": "2026-08-08"},
        {"minutos": 90, "titular": True, "goles": 2, "fecha": "2026-08-07"},
    ]
    sin_marcar = [r for r in rachas(partidos) if "sin marcar" in r["racha"]]
    assert sin_marcar and sin_marcar[0]["partidos"] == 2


def test_tambien_cuenta_las_rachas_buenas():
    partidos = [{"minutos": 90, "titular": True, "goles": 1, "fecha": f"2026-08-0{n}"}
                for n in range(1, 4)]
    assert any("3 partidos marcando" in r["racha"] for r in rachas(partidos))


def test_las_suplencias_seguidas_tambien_son_una_racha():
    partidos = [{"minutos": 10, "titular": False, "goles": 0, "fecha": "2026-08-03"},
                {"minutos": 5, "titular": False, "goles": 0, "fecha": "2026-08-02"},
                {"minutos": 90, "titular": True, "goles": 0, "fecha": "2026-08-01"}]
    assert any("sin ser titular" in r["racha"] for r in rachas(partidos))


def test_sin_haber_jugado_no_hay_rachas():
    assert rachas([{"minutos": 0, "titular": False, "goles": 0, "fecha": "x"}]) == []


# --------------------------------------------------------------------- árbitros

def test_el_perfil_del_arbitro_sale_de_contar_sus_partidos(almacen):
    _liga_inventada(almacen)
    perfil = perfil_de_arbitro(almacen, "César Soto Grado")
    assert perfil["disponible"]
    assert perfil["partidos_mirados"] == 6
    assert perfil["por_partido"]["amarillas"] > 0


def test_con_pocos_partidos_el_arbitro_avisa_de_que_no_es_un_patron(almacen):
    _liga_inventada(almacen, jornadas=4)
    assert "anécdota" in perfil_de_arbitro(almacen, "César Soto Grado")["aviso"]


def test_un_arbitro_desconocido_lo_dice(almacen):
    salida = perfil_de_arbitro(almacen, "Nadie")
    assert salida["disponible"] is False


# ----------------------------------------------------------------------- previa

def test_la_previa_junta_estilo_rachas_y_arbitro(almacen):
    _liga_inventada(almacen)
    evento = Event.from_api({
        "id": 900, "startTimestamp": 1790000000,
        "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
        "status": {"type": "notstarted"},
        "referee": {"name": "César Soto Grado"},
        "homeTeam": {"id": 100, "name": "Balón FC"},
        "awayTeam": {"id": 201, "name": "E201"},
    })
    datos = previa(almacen, evento, ultimos=6)
    assert datos["equipos"]["local"]["disponible"]
    assert datos["arbitro"]["disponible"]
    assert any(j["rachas"] for j in datos["jugadores"]["local"])
    escrito = "\n".join(texto(datos))
    assert "Balón FC" in escrito
    assert "César Soto Grado" in escrito


def test_la_previa_sin_memoria_dice_que_hagas_un_barrido(almacen):
    evento = Event.from_api({"id": 901, "homeTeam": {"id": 7, "name": "A"},
                             "awayTeam": {"id": 8, "name": "B"},
                             "status": {"type": "notstarted"}})
    datos = previa(almacen, evento)
    assert datos["memoria"]["consejo"]
    assert "barrido" in "\n".join(texto(datos))


# ----------------------------------------------- las herramientas que ve la IA

def test_las_herramientas_de_memoria_estan_registradas():
    from cancha.herramientas import TOOLS

    for nombre in ("estilo_de_equipo", "forma_de_jugador", "perfil_de_arbitro",
                   "previa_de_partido", "agenda_del_dia", "estado_de_la_memoria"):
        assert nombre in TOOLS, nombre
        assert len(TOOLS[nombre].description) > 60


def test_el_orden_de_las_herramientas_no_depende_del_formateador():
    """Ruff reordena los imports; el orden que ve el modelo no puede colgar de eso."""
    from cancha.herramientas import TOOLS

    nombres = list(TOOLS)
    assert nombres[0] == "buscar_partido"
    assert nombres.index("analisis_partido") < nombres.index("estilo_de_equipo")
    assert nombres.index("estilo_de_equipo") < nombres.index("contexto_externo")


def test_la_sesion_abre_la_memoria_solo_si_hace_falta(tmp_path):
    from cancha.sesion import Sesion

    sesion = Sesion(settings=Settings(rate_limit=0, offline=True),
                    ruta_almacen=str(tmp_path / "m.db"))
    assert sesion._almacen is None
    assert sesion.almacen.resumen()["partidos"] == 0
    assert sesion._almacen is not None
    sesion.close()
    assert sesion._almacen is None


def test_una_herramienta_de_memoria_sin_barrido_lo_dice(tmp_path):
    from cancha.herramientas import ejecutar
    from cancha.sesion import Sesion

    sesion = Sesion(
        cliente=SofascoreClient(Settings(rate_limit=0, retries=0),
                                transport=FakeTransport({}), cache=MemoryCache(),
                                sleep=lambda _s: None),
        ruta_almacen=str(tmp_path / "vacia.db"),
    )
    try:
        salida = ejecutar("estilo_de_equipo", {"equipo": "12345"}, sesion=sesion)
        assert salida.get("disponible") is False or "error" in salida
    finally:
        sesion.close()
