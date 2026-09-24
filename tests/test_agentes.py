"""Agentes analistas: que sean de verdad distintos, y que den números.

Lo que se prueba aquí no es que el modelo conteste bien —eso no depende de
nosotros— sino las tres promesas del apartado:

1. Un agente al que se le recortan las herramientas **no recibe** las demás. Si
   esto falla, dos agentes con estilos distintos son el mismo agente con otro
   prompt, y la clasificación mide ruido.
2. Un agente está obligado a terminar dando probabilidades, y cuando no las da
   su dictamen se guarda pero **no puntúa**. Sin esa frontera, un agente que
   falla el cierre la mitad de las veces parecería igual de bueno que uno que no.
3. Una definición mal escrita se dice en palabras, no se traga.
"""

from __future__ import annotations

import json

import pytest

from cancha.agentes import (
    POR_DEFECTO,
    VUELTAS_MAXIMAS,
    Agente,
    cargar,
    guardar,
    huella,
    validar,
)
from cancha.almacen import Almacen

# ----------------------------------------------------------------- definiciones

def test_sin_fichero_salen_los_de_ejemplo(tmp_path):
    """La primera vez tiene que haber agentes: un apartado vacío no se entiende."""
    agentes = cargar(tmp_path / "no-existe.json")
    assert set(agentes) == set(POR_DEFECTO)
    assert all(a.instrucciones.strip() for a in agentes.values())


def test_los_de_ejemplo_miran_el_partido_de_formas_distintas():
    """Tres agentes que dicen lo mismo con otras palabras no son tres agentes."""
    agentes = cargar("/no/existe")
    assert len({a.crudo for a in agentes.values()}) > 1
    assert len({a.instrucciones for a in agentes.values()}) == len(agentes)
    # Y al menos uno llega solo a unas herramientas: eso es lo que de verdad
    # separa a un agente de otro, no cómo escribe.
    assert any(a.herramientas for a in agentes.values())


def test_un_fichero_roto_no_deja_sin_programa(tmp_path):
    destino = tmp_path / "agentes.json"
    destino.write_text("{esto no es json", encoding="utf-8")
    assert cargar(destino) == {}


def test_un_agente_ilegible_se_salta_y_los_demas_siguen(tmp_path):
    destino = tmp_path / "agentes.json"
    destino.write_text(json.dumps({"bueno": {"instrucciones": "mira"}, "malo": 7}),
                       encoding="utf-8")
    cargados = cargar(destino)
    assert set(cargados) == {"bueno"}


def test_se_guardan_y_se_vuelven_a_leer_igual(tmp_path):
    destino = tmp_path / "agentes.json"
    uno = Agente(clave="el-mio", nombre="El mío", instrucciones="Mira las faltas.",
                 crudo="todo", vueltas=3, herramientas=("casi_seguro",),
                 temperatura=0.4)
    guardar({"el-mio": uno}, destino)
    otra_vez = cargar(destino)["el-mio"]
    assert otra_vez == uno


def test_las_vueltas_se_quedan_dentro_del_tope(tmp_path):
    """Un agente en bucle con una clave de la nube puesta es una factura."""
    destino = tmp_path / "agentes.json"
    destino.write_text(json.dumps({"el-caro": {"instrucciones": "x", "vueltas": 999}}),
                       encoding="utf-8")
    assert cargar(destino)["el-caro"].vueltas == VUELTAS_MAXIMAS


@pytest.mark.parametrize("clave,datos,esperado", [
    ("El Escéptico", {"instrucciones": "x"}, "no vale como nombre corto"),
    ("el-escéptico", {"instrucciones": "x"}, "no vale como nombre corto"),
    ("mercado", {"instrucciones": "x"}, "concursantes fijos"),
    ("calculo", {"instrucciones": "x"}, "concursantes fijos"),
    ("el-vacio", {"instrucciones": "  "}, "Sin instrucciones"),
    ("el-raro", {"instrucciones": "x", "crudo": "mucho"}, "«todo», «tabla» o «no»"),
    ("el-torpe", {"instrucciones": "x", "herramientas": ["no_existe"]},
     "No conozco estas herramientas"),
])
def test_una_definicion_mala_se_dice_en_palabras(clave, datos, esperado):
    problemas = validar(clave, datos)
    assert problemas, f"{clave} tendría que dar problemas"
    assert any(esperado in p for p in problemas), problemas


def test_una_definicion_buena_no_da_problemas():
    assert validar("el-bueno", {"instrucciones": "Desconfía de las muestras cortas.",
                                "crudo": "todo", "vueltas": 4,
                                "herramientas": ["casi_seguro"]}) == []


def test_la_huella_cambia_con_lo_que_cambia_la_respuesta():
    """Reescribirle las instrucciones lo convierte en otro analista.

    Y eso importa porque su balance no puede mezclar lo que acertaba antes con
    lo que acierta ahora: serían dos agentes en la misma fila.
    """
    base = Agente(clave="el-mio", instrucciones="Mira A.", modelo="m")
    assert huella(base) == huella(Agente(clave="otra-clave", instrucciones="Mira A.",
                                        modelo="m", nombre="Otro nombre"))
    assert huella(base) != huella(Agente(clave="el-mio", instrucciones="Mira B.",
                                         modelo="m"))
    assert huella(base) != huella(Agente(clave="el-mio", instrucciones="Mira A.",
                                         modelo="m", herramientas=("casi_seguro",)))


# ----------------------------------------------------------------- herramientas

def test_un_agente_recortado_no_ve_las_demas_herramientas():
    """Lo que hace distintos a dos agentes es a qué datos llegan.

    Si el recorte no funciona, un «agente del árbitro» al que se le dan las 45
    herramientas mira lo mismo que todos y solo escribe distinto.
    """
    from cancha.analista import Analista
    from cancha.herramientas import TOOLS

    todas = Analista()._esquemas()
    assert len(todas) == len(TOOLS)
    pocas = Analista(solo_herramientas=("casi_seguro",))._esquemas()
    assert [e["function"]["name"] for e in pocas] == ["casi_seguro"]


def test_una_herramienta_que_no_existe_no_deja_al_agente_sin_ninguna():
    """Una errata en la definición no puede dejarlo ciego en silencio."""
    from cancha.analista import Analista

    assert Analista(solo_herramientas=("no_existe_esta",))._esquemas() == []
    # Y por eso `validar` la caza antes de que se guarde.
    assert validar("el-torpe", {"instrucciones": "x",
                                "herramientas": ["no_existe_esta"]})


# ----------------------------------------------------------------- los números

def test_se_lee_el_bloque_de_numeros_entre_prosa():
    from cancha.analista import extraer_numeros

    texto = ('Lo veo claro, el local llega mejor.\n\n'
             '```json\n{"1x2": {"local": 55, "empate": 25, "visitante": 20}}\n```\n'
             'Y ya está.')
    assert extraer_numeros(texto) == {"1x2": {"local": 55, "empate": 25,
                                              "visitante": 20}}


def test_de_dos_bloques_se_coge_el_ultimo():
    """Un modelo que se explica escribe primero el ejemplo y después el bueno."""
    from cancha.analista import extraer_numeros

    texto = ('Tengo que contestar así:\n```json\n{"1x2": {"local": 0}}\n```\n'
             'Y lo mío es:\n```json\n{"1x2": {"local": 55}}\n```')
    assert extraer_numeros(texto) == {"1x2": {"local": 55}}


def test_la_prosa_con_porcentajes_no_son_sus_numeros():
    """Rebuscar un «45 %» en el análisis convertiría un fallo en un dato inventado."""
    from cancha.analista import extraer_numeros

    assert extraer_numeros("El local ronda el 45 % y el empate un 27 %.") is None
    assert extraer_numeros("") is None


def test_un_bloque_roto_no_se_adivina():
    from cancha.analista import extraer_numeros

    assert extraer_numeros('```json\n{"1x2": {"local": 55,\n```') is None


# ----------------------------------------------------------------- correr uno

@pytest.fixture
def base(tmp_path):
    """Una memoria con un partido dentro, listo para que lo analicen."""
    almacen = Almacen(str(tmp_path / "agentes.db"))
    almacen._conexion.execute(
        "INSERT INTO partidos (id, local, visitante, fecha, liga)"
        " VALUES (1, 'Girona', 'Osasuna', '2026-09-25', 'LaLiga')")
    almacen._conexion.commit()
    yield almacen
    almacen.close()


def _agente_falso(base, monkeypatch, respuesta: str, numeros_al_reparar=None):
    """Un `Analista` que contesta lo que se le diga, sin red y sin modelo."""
    from cancha import agentes as modulo
    from cancha.analista import Analista

    def analizar(self, expediente, pregunta="", instrucciones="", al_paso=None,
                 cabecera=""):
        from cancha.analista import extraer_numeros

        numeros = extraer_numeros(respuesta)
        if numeros is None:
            numeros = numeros_al_reparar
        return {"respuesta": respuesta, "probabilidades": numeros,
                "sin_numeros": numeros is None, "modelo": "falso",
                "vueltas": 1, "tokens": {"prompt_eval_count": 120,
                                         "eval_count": 30, "por_modelo": {}},
                "pasos": [{"tipo": "herramienta", "nombre": "casi_seguro"}]}

    monkeypatch.setattr(Analista, "analizar", analizar)

    def expediente_falso(almacen, partido, cliente=None, ultimos=8, con_seguro=True,
                         crudo="tabla"):
        return {"disponible": True, "partido": {"id": 1, "local": "Girona",
                                                "visitante": "Osasuna",
                                                "fecha": "2026-09-25"},
                "pronostico": {"disponible": True, "mercado": {}},
                "tamano": {"caracteres": 10, "tokens_aprox": 2}}

    monkeypatch.setattr(modulo, "expediente", expediente_falso, raising=False)
    import cancha.expediente as exp

    monkeypatch.setattr(exp, "expediente", expediente_falso)
    monkeypatch.setattr(exp, "a_texto", lambda datos: "EL EXPEDIENTE")
    return modulo


def test_un_agente_apunta_su_dictamen_y_sus_numeros(base, monkeypatch):
    modulo = _agente_falso(
        base, monkeypatch,
        'Lo veo así.\n```json\n{"1x2": {"local": 55, "empate": 25, '
        '"visitante": 20}}\n```')
    agente = cargar("/no/existe")["el-esceptico"]
    salida = modulo.correr(base, None, agente, 1)

    assert salida["disponible"] and not salida["sin_numeros"]
    guardado = base.dictamenes_de(1)[0]
    assert guardado["agente"] == "el-esceptico"
    assert guardado["sin_numeros"] == 0
    assert json.loads(guardado["pasos"])[0]["nombre"] == "casi_seguro"

    filas = base.consulta("SELECT * FROM predicciones WHERE autor = 'el-esceptico'")
    assert {f["seleccion"] for f in filas} >= {"local", "empate", "visitante"}
    # Y la versión lleva su huella: el día que le cambies el prompt, se sabrá.
    assert filas[0]["version"] == f"el-esceptico@{huella(agente)}"


def test_sin_numeros_se_guarda_el_dictamen_y_no_se_puntua(base, monkeypatch):
    """La frontera del apartado: se lee, pero no entra en la clasificación.

    Guardar medio análisis como si puntuara sería premiar a un agente por no
    haber terminado su trabajo.
    """
    modulo = _agente_falso(base, monkeypatch, "Me parece que gana el Girona y ya.")
    agente = cargar("/no/existe")["el-esceptico"]
    salida = modulo.correr(base, None, agente, 1)

    assert salida["sin_numeros"] and salida["apuntadas"] == 0
    guardado = base.dictamenes_de(1)[0]
    assert guardado["sin_numeros"] == 1
    assert guardado["respuesta"].startswith("Me parece")
    assert base.consulta("SELECT * FROM predicciones") == []


def test_dos_agentes_pueden_opinar_del_mismo_partido(base, monkeypatch):
    """Es para lo que se amplió el UNIQUE, y es lo que hace posible la tabla."""
    numeros = ('```json\n{"1x2": {"local": 55, "empate": 25, "visitante": 20}}\n```')
    modulo = _agente_falso(base, monkeypatch, numeros)
    agentes = cargar("/no/existe")
    modulo.correr(base, None, agentes["el-esceptico"], 1)
    modulo.correr(base, None, agentes["el-del-crudo"], 1)

    autores = {f["autor"] for f in base.consulta(
        "SELECT autor FROM predicciones WHERE mercado='1x2' AND seleccion='local'")}
    assert {"el-esceptico", "el-del-crudo"} <= autores


def test_un_partido_que_no_esta_se_dice_y_no_se_gasta_nada(base, monkeypatch):
    import cancha.expediente as exp
    from cancha import agentes as modulo

    monkeypatch.setattr(exp, "expediente", lambda *a, **k: {
        "disponible": False, "nota": "No encuentro ese partido."})
    salida = modulo.correr(base, None, cargar("/no/existe")["el-esceptico"], 999)
    assert not salida["disponible"]
    assert "No encuentro" in salida["nota"]
    assert base.dictamenes_de(1) == []


# ------------------------------------------------- repartir entre dos modelos

def test_el_reparto_entra_en_la_huella():
    """Un agente con dos modelos no es el mismo analista que con uno.

    Si no entrara, la tabla mezclaría en la misma fila lo que acertaba pagando el
    modelo bueno todas las vueltas con lo que acierta pagando dos.
    """
    solo = Agente(clave="el-mio", instrucciones="Mira A.", modelo="local")
    con_jefe = Agente(clave="el-mio", instrucciones="Mira A.", modelo="local",
                      modelo_director="grande")
    con_techo = Agente(clave="el-mio", instrucciones="Mira A.", modelo="local",
                       techo_tokens=20000)
    assert len({huella(solo), huella(con_jefe), huella(con_techo)}) == 3


def test_el_reparto_se_guarda_y_se_vuelve_a_leer(tmp_path):
    destino = tmp_path / "agentes.json"
    guardar({"el-mio": Agente(clave="el-mio", instrucciones="x", modelo="local",
                              modelo_director="grande", techo_tokens=30000)}, destino)
    otra_vez = cargar(destino)["el-mio"]
    assert otra_vez.modelo_director == "grande"
    assert otra_vez.techo_tokens == 30000


def test_el_techo_de_tokens_no_se_recorta_como_las_vueltas(tmp_path):
    """Las vueltas van de 1 a 20; un techo de tokens son decenas de miles."""
    destino = tmp_path / "agentes.json"
    destino.write_text(json.dumps({"el-mio": {"instrucciones": "x",
                                             "techo_tokens": 50000}}),
                       encoding="utf-8")
    assert cargar(destino)["el-mio"].techo_tokens == 50000


def test_un_agente_con_reparto_llega_hasta_el_analista(base, monkeypatch):
    """De punta a punta: que lo que se configura acabe donde tiene que acabar."""
    import cancha.expediente as exp
    from cancha import agentes as modulo
    from cancha.analista import Analista

    visto = {}

    def espia(self, expediente, pregunta="", instrucciones="", al_paso=None,
              cabecera=""):
        visto["director"] = self.modelo_director
        visto["techo"] = self.techo_tokens
        visto["sandwich"] = self.en_sandwich
        visto["cabecera"] = cabecera
        return {"respuesta": "x", "probabilidades": None, "sin_numeros": True,
                "modelo": self.modelo_de_cierre, "vueltas": 2, "pasos": [],
                "sandwich": True, "tokens": {"prompt_eval_count": 5000}}

    monkeypatch.setattr(Analista, "analizar", espia)
    monkeypatch.setattr(exp, "expediente", lambda *a, **k: {
        "disponible": True,
        "partido": {"id": 1, "local": "Girona", "visitante": "Osasuna",
                    "fecha": "2026-09-25", "competicion": "LaLiga"},
        "tamano": {"caracteres": 10, "tokens_aprox": 2}})
    monkeypatch.setattr(exp, "a_texto", lambda datos: "EL EXPEDIENTE")

    agente = Agente(clave="el-mio", nombre="El mío", instrucciones="Mira A.",
                    modelo="local", modelo_director="grande", techo_tokens=40000)
    salida = modulo.correr(base, None, agente, 1)

    assert visto["director"] == "grande"
    assert visto["techo"] == 40000
    assert visto["sandwich"] is True
    assert "Girona vs Osasuna" in visto["cabecera"], "y su cabecera, no el expediente"
    assert salida["en_sandwich"] is True
    assert salida["segundos"] >= 0


def test_lo_que_cuesta_un_agente_queda_guardado(base, monkeypatch):
    """Sin esto, el ahorro es una opinión: la clasificación necesita el coste."""
    modulo = _agente_falso(
        base, monkeypatch,
        '```json\n{"1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}\n```')
    modulo.correr(base, None, cargar("/no/existe")["el-esceptico"], 1)
    guardado = base.dictamenes_de(1)[0]
    assert guardado["tokens_prompt"] == 120
    assert guardado["segundos"] is not None


def test_el_calculo_y_el_mercado_no_tienen_coste_que_ensenar(base):
    """Son aritmética: un cero ahí parecería un mérito, y no lo es."""
    from cancha.registro import AUTOR_CALCULO, _lo_que_cuesta

    assert _lo_que_cuesta(base, AUTOR_CALCULO)["tokens_por_analisis"] is None
    assert _lo_que_cuesta(base, "el-que-no-ha-corrido")["segundos_por_analisis"] is None
