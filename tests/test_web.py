"""La interfaz: el servidor, su API y lo que sirve.

Se levanta el servidor de verdad en un puerto libre, con el cliente de mentira
y una memoria en un fichero temporal, y se le habla por HTTP con
``http.client`` (no con ``urllib``, que el guardián de red de los tests corta).
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest
from conftest import EVENT_ID

from cancha.match import build_report
from cancha.sesion import Sesion
from cancha.web.servidor import Servidor, construir, icono_png, ip_local


@pytest.fixture
def servidor(cliente, tmp_path):
    """El servidor en marcha, con un partido guardado en la memoria."""
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "web.db"))
    sesion.almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    app = Servidor(sesion=sesion, carpeta_briefings=str(tmp_path / "briefings"))
    http = construir(app, "127.0.0.1", 0)
    hilo = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.02), daemon=True)
    hilo.start()
    app.puerto = http.server_address[1]
    try:
        yield app
    finally:
        http.shutdown()
        http.server_close()
        app.close()


def _pedir(app, metodo, ruta, cuerpo=None, cabeceras=None):
    conexion = HTTPConnection("127.0.0.1", app.puerto, timeout=10)
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json", **(cabeceras or {})}
    conexion.request(metodo, ruta, body=datos, headers=cabeceras)
    respuesta = conexion.getresponse()
    crudo = respuesta.read()
    conexion.close()
    tipo = respuesta.getheader("Content-Type") or ""
    return respuesta.status, tipo, (json.loads(crudo) if "json" in tipo else crudo)


# ------------------------------------------------------------------ estáticos

def test_la_pagina_se_sirve_y_es_una_pwa(servidor):
    estado, tipo, cuerpo = _pedir(servidor, "GET", "/")
    assert estado == 200 and tipo.startswith("text/html")
    html = cuerpo.decode("utf-8")
    assert "<title>cancha</title>" in html
    assert 'rel="manifest"' in html and "apple-touch-icon" in html
    assert "serviceWorker" in html


def test_el_manifiesto_y_el_service_worker(servidor):
    estado, tipo, cuerpo = _pedir(servidor, "GET", "/manifest.webmanifest")
    assert estado == 200 and "manifest" in tipo
    manifiesto = cuerpo if isinstance(cuerpo, dict) else json.loads(cuerpo)
    assert manifiesto["display"] == "standalone" and manifiesto["start_url"] == "/"
    estado, tipo, _ = _pedir(servidor, "GET", "/sw.js")
    assert estado == 200 and "javascript" in tipo


@pytest.mark.parametrize("ruta", ["/icono-180.png", "/icono-192.png", "/icono-512.png"])
def test_los_iconos_son_png_de_verdad(servidor, ruta):
    estado, tipo, cuerpo = _pedir(servidor, "GET", ruta)
    assert estado == 200 and tipo == "image/png"
    assert cuerpo[:8] == b"\x89PNG\r\n\x1a\n"


def test_el_icono_se_dibuja_con_el_lado_pedido():
    png = icono_png(32)
    # Ancho y alto en la cabecera IHDR, big-endian.
    assert int.from_bytes(png[16:20], "big") == 32 and int.from_bytes(png[20:24], "big") == 32


def test_no_se_sale_de_la_carpeta_de_estaticos(servidor):
    estado, _, _ = _pedir(servidor, "GET", "/../servidor.py")
    assert estado == 404
    estado, _, _ = _pedir(servidor, "GET", "/no-existe.css")
    assert estado == 404


# ------------------------------------------------------------------------ API

def test_el_estado_dice_que_hay_en_la_memoria(servidor):
    estado, _, datos = _pedir(servidor, "GET", "/api/estado")
    assert estado == 200
    assert datos["memoria"]["partidos"] == 1
    assert "futboldata" in datos["fuentes"] and "scraperfc" in datos["librerias"]
    assert datos["version"] and datos["barrido"]["en_marcha"] is False


def test_las_herramientas_se_listan(servidor):
    estado, _, datos = _pedir(servidor, "GET", "/api/herramientas")
    assert estado == 200
    nombres = {t["name"] for t in datos}
    assert {"resumen_partido", "duelo_jugador_rival", "briefing_del_dia"} <= nombres


def test_una_herramienta_se_ejecuta_por_http(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/resumen_partido",
                              {"partido": str(EVENT_ID)})
    assert estado == 200
    assert datos["partido"]["home"]["name"] == "Real Madrid"
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/estilo_de_equipo",
                              {"equipo": "Real Madrid"})
    assert estado == 200 and datos["disponible"]


def test_una_herramienta_que_no_existe_da_404(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/inventada", {})
    assert estado == 404 and "disponibles" in datos


def test_un_cuerpo_que_no_es_json_no_tumba_nada(servidor):
    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=10)
    conexion.request("POST", "/api/herramienta/estado_de_la_memoria", body=b"esto no es json",
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    assert respuesta.status == 200
    assert json.loads(respuesta.read())["partidos"] == 1


def test_una_ruta_desconocida_de_la_api_da_404(servidor):
    assert _pedir(servidor, "GET", "/api/nada")[0] == 404
    assert _pedir(servidor, "POST", "/api/nada", {})[0] == 404


def test_la_sesion_se_comparte_entre_peticiones(servidor):
    peticiones = servidor.sesion.cliente.stats.requests
    _pedir(servidor, "POST", "/api/herramienta/resumen_partido", {"partido": str(EVENT_ID)})
    tras_una = servidor.sesion.cliente.stats.requests
    _pedir(servidor, "POST", "/api/herramienta/resumen_partido", {"partido": str(EVENT_ID)})
    assert servidor.sesion.cliente.stats.requests == tras_una
    assert tras_una >= peticiones


def test_el_briefing_guardado_se_sirve_y_el_que_no_existe_lo_dice(servidor):
    assert _pedir(servidor, "GET", "/api/briefing/2024-10-26")[0] == 404
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/briefing_del_dia",
                              {"fecha": "2024-10-26", "grupos": "grandes"})
    assert estado == 200 and datos["total"] == 1


def test_el_barrido_corre_en_segundo_plano(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/barrido",
                              {"fecha": "2024-10-26", "grupos": "grandes", "max": 50})
    assert estado == 200 and "error" not in datos
    servidor.esperar_barrido()
    estado, _, datos = _pedir(servidor, "GET", "/api/barrido")
    assert datos["en_marcha"] is False
    assert datos["resumen"]["partidos_del_dia"] == 1
    assert any("partidos el 2024-10-26" in linea for linea in datos["lineas"])


def test_no_se_lanzan_dos_barridos_a_la_vez(servidor):
    servidor.barrido["en_marcha"] = True
    try:
        _, _, datos = _pedir(servidor, "POST", "/api/barrido", {})
        assert "error" in datos
    finally:
        servidor.barrido["en_marcha"] = False


def test_con_clave_la_api_la_exige_y_la_pagina_no(servidor):
    servidor.clave = "secreto"
    try:
        assert _pedir(servidor, "GET", "/api/estado")[0] == 401
        assert _pedir(servidor, "POST", "/api/herramienta/estado_de_la_memoria", {})[0] == 401
        assert _pedir(servidor, "GET", "/api/estado", cabeceras={"X-Clave": "secreto"})[0] == 200
        assert _pedir(servidor, "GET", "/api/estado?clave=secreto")[0] == 200
        assert _pedir(servidor, "GET", "/")[0] == 200
    finally:
        servidor.clave = ""


def test_la_ip_local_es_una_ip():
    partes = ip_local().split(".")
    assert len(partes) == 4 and all(p.isdigit() for p in partes)


def test_el_comando_web_existe_y_tiene_sus_opciones():
    from cancha.cli import build_parser

    args = build_parser().parse_args(["web", "--lan", "--port", "9000", "--clave", "x"])
    assert args.lan and args.port == 9000 and args.clave == "x"


# ------------------------------------------------------- casi seguro y analista

def test_el_estado_lleva_el_catalogo_y_el_modelo(servidor):
    _, _, datos = _pedir(servidor, "GET", "/api/estado")
    catalogo = datos["catalogo"]
    assert catalogo["competiciones"] >= 60 and catalogo["femeninas"] >= 15
    assert "grandes_f" in catalogo["por_grupo"]
    assert datos["modelo"]


def test_casi_seguro_por_http(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/seguro", {"calibrar": True})
    assert estado == 200
    assert len(datos["patrones"]) >= 10
    assert "Wilson" in datos["como_leerlo"]

    estado, _, datos = _pedir(servidor, "POST", "/api/seguro", {"fecha": "2024-10-26"})
    assert estado == 200 and "avisos" in datos
    assert "apuesta segura" in datos["lo_que_no_dice"]


def test_el_estado_del_analista_dice_que_falta_ollama(servidor):
    """Sin Ollama detrás, la página tiene que poder explicarlo en vez de colgarse."""
    estado, _, datos = _pedir(servidor, "GET", "/api/analista")
    assert estado == 200
    assert datos["disponible"] is False
    assert "Ollama" in datos["nota"] or "ollama" in datos["nota"]
    assert "langchain" in datos


def test_el_analista_contesta_en_ndjson_paso_a_paso(servidor):
    """El formato que lee la interfaz: una línea por paso, según van pasando."""
    from cancha.analista import Analista

    guion = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "estado_de_la_memoria",
                                                  "arguments": {}}}]}},
        {"message": {"role": "assistant", "content": "Hay un partido guardado."}},
    ]
    servidor._analistas[servidor.modelo] = Analista(
        sesion=servidor.sesion, pedir=lambda ruta, cuerpo=None: guion.pop(0))

    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=15)
    conexion.request("POST", "/api/analista", body=json.dumps({"pregunta": "¿qué hay?"}).encode(),
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    assert respuesta.status == 200
    assert "ndjson" in (respuesta.getheader("Content-Type") or "")
    lineas = [json.loads(x) for x in respuesta.read().decode().splitlines() if x.strip()]
    conexion.close()

    tipos = [x["paso"]["tipo"] for x in lineas if "paso" in x]
    assert tipos == ["herramienta", "resultado", "respuesta"]
    fin = next(x["fin"] for x in lineas if "fin" in x)
    assert fin["respuesta"] == "Hay un partido guardado."
    assert fin["historial"][0]["role"] == "system"


def test_una_pregunta_vacia_se_rechaza(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/analista", {"pregunta": "  "})
    assert estado == 400 and "Falta la pregunta" in datos["error"]


def test_si_ollama_falla_el_error_viaja_por_la_misma_linea(servidor):
    from cancha.analista import Analista, OllamaNoDisponible

    def roto(ruta, cuerpo=None):
        raise OllamaNoDisponible("No hay nadie escuchando.")

    servidor._analistas[servidor.modelo] = Analista(sesion=servidor.sesion, pedir=roto)
    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=15)
    conexion.request("POST", "/api/analista", body=json.dumps({"pregunta": "hola"}).encode(),
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    lineas = [json.loads(x) for x in respuesta.read().decode().splitlines() if x.strip()]
    conexion.close()
    assert lineas and "escuchando" in lineas[-1]["error"]


def test_la_pagina_trae_las_cinco_pestanas_y_el_tema(servidor):
    _, _, cuerpo = _pedir(servidor, "GET", "/")
    html = cuerpo.decode("utf-8")
    for pestana in ("Hoy", "Seguro", "Analista", "Buscar", "Memoria"):
        assert f'"{pestana}"' in html, pestana
    # Los tres estados del tema: claro, oscuro por sistema y oscuro elegido.
    assert "prefers-color-scheme: dark" in html
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    assert "prefers-reduced-motion" in html


# ------------------------------------------------------- llegar desde el móvil

def test_se_enseñan_todas_las_ip_y_la_primera_es_privada():
    """Con VPN o Docker hay varias IP; enseñar solo una y fallar es lo peor."""
    from cancha.web.servidor import ips_locales

    ips = ips_locales()
    assert ip_local() in ips or ip_local().startswith("127.")
    assert not any(ip.startswith("127.") for ip in ips), "el bucle local no sirve"
    privadas = [i for i, ip in enumerate(ips)
                if ip.startswith(("192.168.", "10.", "172."))]
    if privadas and len(privadas) < len(ips):
        assert max(privadas) < min(set(range(len(ips))) - set(privadas))


def test_al_abrir_a_la_red_se_dibuja_el_qr_con_la_clave_dentro(cliente, tmp_path):
    """Escanear y entrar, sin teclear la clave en el móvil."""
    from cancha.web.qr import matriz
    from cancha.web.servidor import arrancar

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "qr.db"))
    app = Servidor(sesion=sesion, clave="s3creta")
    lineas: list[str] = []

    class Falso:
        server_address = ("0.0.0.0", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    import cancha.web.servidor as servidor_modulo

    antes = servidor_modulo.construir
    servidor_modulo.construir = lambda *a, **k: Falso()
    try:
        arrancar(app, host="0.0.0.0", puerto=8765, avisar=lineas.append)
    finally:
        servidor_modulo.construir = antes

    texto = "\n".join(lineas)
    assert "clave=s3creta" in texto, "la clave tiene que ir en la dirección del QR"
    assert "\x1b[" in texto, "el QR se dibuja con colores fijos"
    assert "pantalla de inicio" in texto
    # Y lo dibujado es un QR de verdad del tamaño que toca para esa dirección.
    url = next(x.strip() for x in lineas
               if x.strip().startswith("http://") and "clave=" in x)
    assert len(matriz(url)) >= 25


def test_sin_qr_se_siguen_dando_las_direcciones(cliente, tmp_path):
    from cancha.web.servidor import arrancar

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "qr2.db"))
    app = Servidor(sesion=sesion)
    lineas: list[str] = []

    class Falso:
        server_address = ("0.0.0.0", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    import cancha.web.servidor as servidor_modulo

    antes = servidor_modulo.construir
    servidor_modulo.construir = lambda *a, **k: Falso()
    try:
        arrancar(app, host="0.0.0.0", puerto=8765, avisar=lineas.append, qr=False)
    finally:
        servidor_modulo.construir = antes

    texto = "\n".join(lineas)
    assert "\x1b[" not in texto
    assert ":8765/" in texto


def test_la_pagina_coge_la_clave_de_la_direccion_y_la_borra(servidor):
    """Es lo que hace que escanear el QR sea un solo gesto."""
    _, _, cuerpo = _pedir(servidor, "GET", "/")
    html = cuerpo.decode("utf-8")
    assert "claveDeLaUrl" in html
    assert 'URLSearchParams(location.search).get("clave")' in html
    assert "history.replaceState" in html, "la clave no se queda en la barra"


# --------------------------------------------- todo, también desde el móvil

#: Las cuatro herramientas que la página no llama por su nombre, y por qué. Si
#: una más se cuela aquí sin razón escrita, el test de abajo lo dice.
POR_OTRO_CAMINO = {
    "puntos_esperados": "viene dentro de analisis_partido, que la vista del partido ya pinta",
    "carrera_xg": "viene dentro de analisis_partido",
    "estado_de_la_memoria": "la página usa /api/estado, que es lo mismo con el barrido dentro",
    "casi_seguro": "la página usa /api/seguro, que además permite calibrar",
}


def _pagina() -> str:
    from cancha.web.servidor import ESTATICO

    return (ESTATICO / "index.html").read_text(encoding="utf-8")


def test_todas_las_herramientas_se_pueden_usar_desde_la_pagina():
    """El móvil tiene que llegar a todo, no a la mitad.

    Cada herramienta o tiene su sitio en una vista, o está en la lista de las
    que llegan por otro camino —y esa lista lleva escrito el camino—.
    """
    from cancha.herramientas import esquemas

    html = _pagina()
    sin_sitio = [e["name"] for e in esquemas()
                 if f'"{e["name"]}"' not in html and e["name"] not in POR_OTRO_CAMINO]
    assert not sin_sitio, f"sin manera de usarlas desde la página: {sin_sitio}"
    # Y la lista de excepciones no se queda con nombres que ya no existen.
    nombres = {e["name"] for e in esquemas()}
    assert set(POR_OTRO_CAMINO) <= nombres


def test_la_consola_alcanza_cualquier_herramienta_futura():
    """Las vistas cubren lo de cada día; la consola cubre el resto, y lo que venga."""
    html = _pagina()
    assert "tarjetaConsola" in html
    assert '/api/herramientas' in html, "la lista se pide al servidor, no está escrita a mano"
    assert "input_schema" in html, "los campos se montan desde el esquema de cada herramienta"


def test_la_pagina_llega_a_lo_que_antes_solo_estaba_en_el_terminal(servidor):
    """doctor, cache, el directo, la clasificación y descubrir ligas."""
    html = _pagina()
    for pieza in ("/api/diagnostico", "/api/cache", "/api/ligas", "/api/red",
                  "pintarDirecto", "pintarLiga", "ficha_equipo", "ficha_jugador"):
        assert pieza in html, pieza


def test_el_diagnostico_se_sirve_sin_tocar_la_red(servidor):
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/diagnostico")
    assert estado == 200
    assert [t["nombre"] for t in cuerpo["transportes"]] == ["curl", "httpx", "urllib"]
    assert "credenciales" in cuerpo and "cache" in cuerpo
    assert "api" not in cuerpo, "sin ?red=1 no se pide nada a nadie"


def test_el_qr_de_la_red_sale_del_servidor(servidor):
    servidor.abierto = True
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/red")
    assert estado == 200
    assert cuerpo["abierto_a_la_red"] is True
    if cuerpo["urls"]:
        assert len(cuerpo["qr"]) >= 21
        assert set(cuerpo["qr"][0]) <= {0, 1}


def test_cerrado_a_la_red_el_qr_lo_dice_en_vez_de_enganar(servidor):
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/red")
    assert estado == 200 and cuerpo["abierto_a_la_red"] is False


def test_vaciar_la_cache_desde_la_pagina(servidor):
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/cache", {})
    assert estado == 200 and "borrados" in cuerpo


def test_el_directo_no_se_queda_pidiendo_cuando_te_vas_de_la_vista():
    """Un temporizador que sobrevive a la vista se come la batería del móvil."""
    html = _pagina()
    desde = html.index("async function pintarDirecto")
    hasta = html.index("async function generarBriefing")
    trozo = html[desde:hasta]
    assert trozo.count("location.hash !== mio") >= 1
    assert trozo.count("location.hash === mio") >= 2


# ------------------------------------------------------------------ ajustes

def test_los_ajustes_se_leen_con_el_catalogo_de_ligas(servidor, tmp_path):
    servidor.ruta_ajustes = str(tmp_path / "aj.json")
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert estado == 200
    assert cuerpo["ajustes"]["guardia"]["hora"] == "03:00"
    assert len(cuerpo["competiciones"]) == 71, "para poder elegirlas de una lista"
    assert {"grupo", "competiciones"} <= set(cuerpo["grupos"][0])
    assert cuerpo["problemas"] == []


def test_los_ajustes_se_guardan_desde_la_pagina(servidor, tmp_path):
    ruta = tmp_path / "aj2.json"
    servidor.ruta_ajustes = str(ruta)
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes", {
        "guardia": {"hora": "02:15", "partidos": 4},
        "ligas": ["grandes", "uefa"], "modelo": "qwen2.5:7b"})
    assert estado == 200 and cuerpo["guardado"] is True
    assert ruta.is_file()

    from cancha.ajustes import cargar

    guardados = cargar(ruta)
    assert guardados["guardia"]["hora"] == "02:15"
    assert guardados["ligas"] == ["grandes", "uefa"]
    assert guardados["modelo"] == "qwen2.5:7b"


def test_unos_ajustes_imposibles_no_se_guardan_y_se_explican(servidor, tmp_path):
    ruta = tmp_path / "aj3.json"
    servidor.ruta_ajustes = str(ruta)
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"guardia": {"hora": "a las tres"}})
    assert cuerpo["guardado"] is False
    assert any("03:00" in p for p in cuerpo["problemas"])
    assert not ruta.is_file(), "no puede quedarse escrito algo que no vale"


def test_se_dice_qué_cambios_necesitan_reiniciar(servidor, tmp_path):
    """La hora se coge al vuelo; el puerto no. Callárselo es el «no me funciona»."""
    servidor.ruta_ajustes = str(tmp_path / "aj4.json")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"web": {"puerto": 9100}, "guardia": {"hora": "01:00"}})
    assert cuerpo["guardado"] is True
    assert "el puerto" in cuerpo["hace_falta_reiniciar"]
    assert not any("hora" in x for x in cuerpo["hace_falta_reiniciar"])


def test_el_token_del_bot_no_sale_por_la_api(servidor, tmp_path):
    ruta = tmp_path / "aj5.json"
    servidor.ruta_ajustes = str(ruta)
    _pedir(servidor, "POST", "/api/ajustes", {"telegram": {"token": "123:SECRETISIMO"}})
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert "SECRETISIMO" not in json.dumps(cuerpo)
    assert cuerpo["ajustes"]["telegram"]["token_puesto"] is True


def test_la_pagina_tiene_el_panel_de_ajustes(servidor):
    html = _pagina()
    assert "tarjetaAjustes" in html
    assert "/api/ajustes" in html
    for pieza in ("a qué hora", "Ligas que sigues", "modelo de ollama",
                  "token del bot de telegram"):
        assert pieza in html, pieza
