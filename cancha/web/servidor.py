"""El servidor de la interfaz: una API JSON sobre las herramientas, y estáticos.

Todo cuelga de :mod:`cancha.herramientas`: ``POST /api/herramienta/<nombre>``
ejecuta una con los argumentos del cuerpo, con la misma sesión para toda la
vida del servidor (lo ya traído no se vuelve a pedir). Encima hay cuatro
rutas de conveniencia —estado, briefings, el barrido en segundo plano— y los
ficheros de la página.

Es un servidor para **una persona en su red**: un hilo por petición, las
herramientas en serie (la memoria es SQLite y no le gustan los hilos) y una
clave opcional para cuando se abre a la wifi.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import zlib
from contextlib import suppress
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .. import __version__
from ..sesion import Sesion
from .qr import dibujar as dibujar_qr

ESTATICO = Path(__file__).parent / "estatico"
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".webmanifest": "application/manifest+json",
         ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json"}
#: La página puede con mucho más que el contexto de un modelo.
MAX_CHARS_WEB = 2_000_000


def _huella(clave: str) -> str:
    """Cómo es la clave sin decir cuál es: para comparar de un vistazo.

    Es lo que hace falta cuando alguien jura que ha pegado la buena: ver que la
    que hay guardada mide lo que debe y acaba como debe.
    """
    return f"{len(clave)} caracteres, acaba en …{clave[-4:]}" if clave else "vacía"


def _agente_de(clave: str, datos: dict):
    """Un `Agente` desde lo que llega por la petición, con lo que no venga por
    defecto. La validación ya ha pasado antes de llegar aquí."""
    from ..agentes import construir

    return construir(clave, datos)


class Servidor:
    """Lo que comparten las peticiones: la sesión, el barrido y la clave."""

    def __init__(self, sesion: Sesion | None = None, ruta_almacen: str = "datos/cancha.db",
                 clave: str = "", carpeta_briefings: str = "datos/briefings",
                 modelo: str = "", ollama: str = "", api_key: str = "",
                 ruta_ajustes: str | None = None, ca_bundle: str = "",
                 sin_verificar: bool = False) -> None:
        from ..analista import MODELO_POR_DEFECTO, URL_OLLAMA

        self.sesion = sesion or Sesion(ruta_almacen=ruta_almacen)
        self.clave = clave
        self.carpeta_briefings = carpeta_briefings
        self.modelo = modelo or MODELO_POR_DEFECTO
        self.ollama = ollama or URL_OLLAMA
        self.api_key = api_key
        #: Certificados, para la nube del analista. Ver :mod:`cancha.tls`.
        self.ca_bundle = ca_bundle
        self.sin_verificar = sin_verificar
        self.ruta_ajustes = ruta_ajustes
        #: El bot, si lo hay, para poder decir en Ajustes si está escuchando.
        #: Lo pone ``cancha arrancar``; sin él la página funciona igual.
        self.bot: Any = None
        self._analistas: dict[str, Any] = {}
        #: Los rellena ``arrancar``; la página los usa para el QR de la wifi.
        self.puerto = 8765
        self.abierto = False
        self.cerrojo = threading.Lock()
        self.barrido = {"en_marcha": False, "lineas": [], "resumen": None,
                        "empezado": None, "terminado": None}
        self._hilo_barrido: threading.Thread | None = None
        #: Los trabajos largos que no caben en una petición. El briefing de un
        #: día con doscientos partidos son miles de peticiones y varios minutos:
        #: contestarlo de una sola vez es garantizar que el navegador se rinda
        #: antes. Cada uno va en su hilo, apunta lo que hace y se puede parar.
        self.tareas: dict[str, dict] = {}
        self._hilos: dict[str, threading.Thread] = {}

    # --- herramientas ---

    def ejecutar(self, nombre: str, argumentos: dict) -> Any:
        from ..herramientas import ejecutar

        with self.cerrojo:
            return ejecutar(nombre, argumentos, sesion=self.sesion, max_chars=MAX_CHARS_WEB)

    def esquemas(self) -> list[dict]:
        from ..herramientas import esquemas

        return esquemas()

    def estado(self) -> dict:
        from ..briefing import guardados
        from ..ligas import resumen_catalogo
        from ..sources import FUENTES, disponibles

        with self.cerrojo:
            memoria = self.sesion.almacen.resumen()
        return {
            "version": __version__,
            "memoria": memoria,
            "briefings": guardados(self.carpeta_briefings)[:30],
            "fuentes": sorted(FUENTES),
            "librerias": disponibles(),
            "barrido": self.estado_barrido(),
            "catalogo": resumen_catalogo(self.sesion.almacen),
            "modelo": self.modelo,
            "hora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # --- analista ---

    def analista(self, modelo: str | None = None):
        """El analista, uno por modelo, reaprovechando la sesión del servidor."""
        from ..analista import Analista

        clave = modelo or self.modelo
        if clave not in self._analistas:
            self._analistas[clave] = Analista(
                sesion=self.sesion, modelo=clave, url=self.ollama,
                api_key=self.api_key, ca_bundle=self.ca_bundle,
                sin_verificar=self.sin_verificar)
        return self._analistas[clave]

    def estado_analista(self, modelo: str | None = None) -> dict:
        """Si Ollama está y con qué modelos, sin que su ausencia tumbe la página.

        Se atrapa cualquier fallo y no solo el tipado: aquí se está preguntando
        por algo que puede no existir, y la página tiene que poder explicarlo.
        """
        from ..agentes.langchain import disponible as langchain_disponible

        try:
            estado = self.analista(modelo).comprobar()
        except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde
            estado = {"disponible": False, "nota": f"Ollama no contesta: {exc}",
                      "como": "Instala Ollama (ollama.com), arráncalo y trae un modelo:\n"
                              "    ollama pull hermes3"}
        estado["langchain"] = langchain_disponible()
        estado.setdefault("modelo", modelo or self.modelo)
        return estado

    def preguntar(self, pregunta: str, historial=None, modelo=None, al_paso=None) -> dict:
        with self.cerrojo:
            return self.analista(modelo).preguntar(pregunta, historial=historial,
                                                   al_paso=al_paso)

    # --- dictamen ---

    def dictamen(self, partido: str, pregunta: str = "", crudo: str = "todo") -> dict:
        """El expediente entero a un modelo. Lo más caro que hace el servidor.

        Lo que conteste se guarda en la memoria, atado al id del partido: cuesta
        dinero y tiempo, y sobre todo es lo que dijo **entonces**. Volver mañana
        y encontrarlo igual es la mitad de su valor.
        """
        from ..expediente import a_texto, expediente

        if not partido:
            return {"error": "Falta el partido."}
        with self.cerrojo:
            datos = expediente(self.sesion.almacen, partido, cliente=self.sesion.cliente,
                               crudo=crudo if crudo in ("todo", "tabla", "no") else "todo")
            if not datos.get("disponible"):
                return {"error": datos.get("nota", "No hay expediente de ese partido.")}
            documento = a_texto(datos)
            salida = self.analista().dictaminar(documento, pregunta)
            partido_id = datos["partido"]["id"]
            salida["id"] = self.sesion.almacen.guardar_dictamen(
                partido_id, salida.get("respuesta") or "",
                modelo=salida.get("modelo") or "", pregunta=pregunta,
                expediente=documento, en_la_nube=bool(salida.get("en_la_nube")),
                tokens=salida.get("tokens"))
        salida["partido_id"] = partido_id
        salida["guardado"] = True
        salida["expediente"] = {**datos["tamano"], "texto": documento}
        return salida

    def dictamenes(self, partido: str, con_expediente: bool = False) -> dict:
        """Los dictámenes ya guardados de un partido. Sin pedirle nada a nadie."""
        from ..previa import _resolver

        if not partido:
            return {"error": "Falta el partido."}
        with self.cerrojo:
            evento = _resolver(self.sesion.almacen, partido, self.sesion.cliente)
            if evento is None:
                return {"error": "No encuentro ese partido."}
            guardados = self.sesion.almacen.dictamenes_de(
                evento.id, con_expediente=con_expediente)
        return {"partido_id": evento.id,
                "partido": f"{evento.home} - {evento.away}",
                "dictamenes": guardados, "cuantos": len(guardados)}

    def borrar_dictamen(self, dictamen_id: int) -> dict:
        with self.cerrojo:
            return {"borrado": self.sesion.almacen.borrar_dictamen(int(dictamen_id))}

    # --- trabajos largos ---

    def estado_tarea(self, nombre: str) -> dict:
        """Cómo va un trabajo largo. Las líneas, recortadas a las últimas."""
        tarea = self.tareas.get(nombre)
        if tarea is None:
            return {"nombre": nombre, "en_marcha": False, "lineas": [],
                    "resumen": None, "nunca": True}
        return {k: (v[-60:] if k == "lineas" else v) for k, v in tarea.items()
                if k != "parar"}

    def parar_tarea(self, nombre: str) -> dict:
        """Le pide a un trabajo que pare. No lo mata: le dice que se pare solo.

        Matar un hilo a mitad dejaría la memoria escrita a medias. Lo que se hace
        es levantar una bandera que el trabajo mira entre partido y partido, así
        que parar tarda lo que tarde el que esté en marcha, y ni un paso más.
        """
        tarea = self.tareas.get(nombre)
        if not tarea or not tarea["en_marcha"]:
            return {"error": f"No hay ningún «{nombre}» en marcha."}
        tarea["parar"].set()
        tarea["lineas"].append("Parando en cuanto acabe lo que tiene entre manos…")
        return self.estado_tarea(nombre)

    def _lanzar(self, nombre: str, trabajo) -> dict:
        """Arranca un trabajo en su hilo, si no hay ya uno de lo mismo.

        `trabajo` recibe dos cosas: dónde escribir lo que va haciendo, y una
        función que le dice si puede seguir. Nada más: así el trabajo no sabe
        nada del servidor ni de HTTP, y se puede probar suelto.
        """
        si_hay = self.tareas.get(nombre)
        if si_hay and si_hay["en_marcha"]:
            return {"error": f"Ya hay un «{nombre}» en marcha.",
                    **self.estado_tarea(nombre)}
        parar = threading.Event()
        tarea = {"nombre": nombre, "en_marcha": True, "lineas": [], "resumen": None,
                 "empezado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "terminado": None, "parar": parar}
        self.tareas[nombre] = tarea

        def correr() -> None:
            try:
                tarea["resumen"] = trabajo(tarea["lineas"].append,
                                           lambda: not parar.is_set())
            except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde
                tarea["lineas"].append(f"error: {exc}")
                tarea["resumen"] = {"error": str(exc)}
            finally:
                tarea["en_marcha"] = False
                tarea["terminado"] = datetime.now(timezone.utc).isoformat(
                    timespec="seconds")

        hilo = threading.Thread(target=correr, daemon=True)
        self._hilos[nombre] = hilo
        hilo.start()
        return self.estado_tarea(nombre)

    def esperar_tarea(self, nombre: str, segundos: float = 30) -> None:
        """Para los tests: espera a que un trabajo acabe."""
        hilo = self._hilos.get(nombre)
        if hilo:
            hilo.join(segundos)

    def lanzar_briefing(self, fecha: str | None, grupos: list[str] | None) -> dict:
        """El briefing del día, en segundo plano.

        Antes iba dentro de la petición, y por eso «no funcionaba muy bien»: un
        día normal son doscientos y pico partidos, y de **cada uno** se pide la
        previa, la evolución de los dos equipos y los duelos de sus jugadores.
        Eso son miles de peticiones y varios minutos; el navegador se rinde mucho
        antes, y mientras tanto el cerrojo dejaba la página entera congelada.
        """
        from ..briefing import briefing, guardar

        def trabajo(decir, puede_seguir):
            with self.cerrojo:
                datos = briefing(self.sesion.almacen, self.sesion.cliente,
                                 fecha=fecha, grupos=grupos, avisar=decir,
                                 puede_seguir=puede_seguir)
            guardar(datos, self.carpeta_briefings)
            return {"fecha": datos["fecha"], "partidos": datos["total"],
                    "completo": datos.get("completo", True)}

        return self._lanzar("briefing", trabajo)

    def lanzar_historia(self, anos: int, grupos: list[str] | None,
                        secciones: list[str] | None, maximo: int) -> dict:
        """Traerse años de partidos, en segundo plano. Horas de trabajo."""
        from ..historia import traer

        def trabajo(decir, puede_seguir):
            with self.cerrojo:
                return traer(self.sesion.cliente, self.sesion.almacen, grupos,
                             anos=anos, secciones=secciones, maximo=maximo,
                             avisar=decir, puede_seguir=puede_seguir)

        return self._lanzar("historia", trabajo)

    def plan_historia(self, anos: int, grupos: list[str] | None,
                      secciones: list[str] | None) -> dict:
        """Lo que costaría traerse esa historia, sin traer nada."""
        from ..historia import plan

        with self.cerrojo:
            return plan(self.sesion.cliente, self.sesion.almacen, grupos,
                        anos=anos, secciones=secciones)

    # --- agentes ---

    def agentes(self) -> dict:
        """Los agentes que hay, con lo que tengan mal dicho en palabras."""
        from ..agentes import cargar, huella, ruta, validar
        from ..herramientas import TOOLS

        donde = ruta(None)
        agentes = cargar(donde)
        return {
            "fichero": str(donde),
            "agentes": [{**a.as_dict(), "clave": c, "huella": huella(a),
                         "problemas": validar(c, a.as_dict())}
                        for c, a in sorted(agentes.items())],
            "herramientas": sorted(TOOLS),
        }

    def poner_agente(self, clave: str, datos: dict) -> dict:
        """Guarda un agente. Si la definición no vale, no se escribe nada."""
        from ..agentes import cargar, guardar, ruta, validar

        clave = str(clave or "").strip()
        problemas = validar(clave, datos)
        if problemas:
            return {"problemas": problemas, "guardado": False}
        donde = ruta(None)
        with self.cerrojo:
            agentes = cargar(donde)
            agentes[clave] = _agente_de(clave, datos)
            guardar(agentes, donde)
        return {"guardado": True, "clave": clave}

    def borrar_agente(self, clave: str) -> dict:
        """Quita un agente. Lo que ya predijo se queda: el registro no se reescribe."""
        from ..agentes import cargar, guardar, ruta

        donde = ruta(None)
        with self.cerrojo:
            agentes = cargar(donde)
            if clave not in agentes:
                return {"error": f"No tengo ningún agente «{clave}»."}
            del agentes[clave]
            guardar(agentes, donde)
        return {"borrado": True, "clave": clave,
                "nota": "Sus predicciones siguen en el registro: un historial que se "
                        "puede reescribir no vale nada."}

    def correr_agente(self, clave: str, partido: str) -> dict:
        """Pone a un agente a analizar un partido. Lo más caro que hace esto.

        El cerrojo se coge **por tramos** y no durante toda la llamada al modelo:
        un agente con seis vueltas puede tardar minutos, y sostenerlo entero
        dejaría la página congelada para cualquier otra cosa mientras tanto.
        """
        from ..agentes import cargar, correr, ruta

        agente = cargar(ruta(None)).get(clave)
        if agente is None:
            return {"error": f"No tengo ningún agente «{clave}»."}
        if not partido:
            return {"error": "Falta el partido."}
        analista = self.analista(agente.modelo or None)
        return correr(self.sesion.almacen, self.sesion.cliente, agente, partido,
                      modelo_por_defecto=analista.modelo, api_key=analista.api_key,
                      url=analista.url)

    def clasificacion(self, desde: str | None = None, hasta: str | None = None) -> dict:
        """La tabla: quién acierta más, contra el cálculo y contra el mercado."""
        from ..registro import tabla, texto_tabla

        with self.cerrojo:
            datos = tabla(self.sesion.almacen, desde=desde, hasta=hasta)
        return {**datos, "lineas": texto_tabla(datos)}

    # --- casi seguro ---

    def seguro(self, fecha: str | None = None, grupos=None, calibrar: bool = False,
               umbral: float = 0.65) -> dict:
        from ..seguro import avisos
        from ..seguro import calibrar as calibrar_patrones

        with self.cerrojo:
            if calibrar:
                return calibrar_patrones(self.sesion.almacen)
            return avisos(self.sesion.almacen, self.sesion.cliente, fecha=fecha,
                          grupos=grupos, umbral=umbral)

    # --- ajustes ---

    def ajustes(self) -> dict:
        """Los ajustes, con el catálogo de ligas para poder elegirlas de una lista."""
        from ..ajustes import cargar, revisar, sin_secretos
        from ..ligas import CATALOGO, GRUPOS
        from ..telegrama import vistos

        guardados = cargar(self.ruta_ajustes)
        with self.cerrojo:
            quien_ha_escrito = vistos(self.sesion.almacen)
        return {
            "telegram_vistos": quien_ha_escrito,
            "telegram_estado": self.bot.estado() if self.bot is not None else None,
            "ajustes": sin_secretos({k: v for k, v in guardados.items()
                                     if not k.startswith("_")}),
            "error": guardados.get("_error"),
            "problemas": revisar(guardados),
            "grupos": [{"grupo": g, "competiciones": len(n)} for g, n in GRUPOS.items()],
            "competiciones": [
                {"nombre": c.nombre, "grupo": c.grupo, "genero": c.genero,
                 "pais": c.pais, "alias": list(c.alias)} for c in CATALOGO],
            "modelos": self._modelos_instalados(),
        }

    def _modelos_instalados(self) -> list[str]:
        """Qué modelos tiene Ollama, para elegir de una lista en vez de a ciegas."""
        try:
            estado = self.estado_analista()
        except Exception:  # noqa: BLE001 - sin Ollama la página sigue funcionando
            return []
        # `modelos` es una lista de diccionarios con nombre y tamaño; aquí solo
        # hacen falta los nombres, para pintar un desplegable.
        return [m.get("nombre") or "" for m in (estado.get("modelos") or [])
                if m.get("nombre")]

    def poner_ajustes(self, cambios: dict) -> dict:
        """Guarda lo que llegue de la página. Solo claves conocidas.

        Devuelve lo guardado y qué hace falta reiniciar: la hora de la guardia
        se coge al vuelo, pero el puerto o el token no, y decirlo ahorra el
        «no me funciona» de dentro de un rato.
        """
        from ..ajustes import (
            SecretoRaro,
            aplicar_desde_fuera,
            cargar,
            guardar,
            revisar,
            sin_secretos,
        )

        antes = cargar(self.ruta_ajustes)
        try:
            nuevos = aplicar_desde_fuera(antes, cambios)
        except SecretoRaro as exc:
            # Una clave mal pegada es un problema del formulario, no un fallo
            # del servidor: se enseña arriba, donde se está escribiendo.
            return {"guardado": False, "problemas": [str(exc)]}
        problemas = revisar(nuevos)
        if problemas:
            return {"guardado": False, "problemas": problemas}
        destino = guardar(nuevos, self.ruta_ajustes)
        # Lo que no se puede cambiar en caliente, dicho por su nombre. El token
        # y los chats del bot **sí** se cogen al vuelo —el bot mira los ajustes
        # en cada vuelta—, y decir lo contrario hacía que la gente reiniciase
        # sin necesidad. Lo que queda es lo que se decide al abrir el puerto.
        en_frio = [
            nombre for nombre, camino in (
                ("el puerto", ("web", "puerto")),
                ("abrirlo a la wifi", ("web", "lan")),
                ("la clave", ("web", "clave")),
            ) if antes[camino[0]][camino[1]] != nuevos[camino[0]][camino[1]]
        ]
        return {
            "guardado": True, "fichero": str(destino), "problemas": [],
            "ajustes": sin_secretos({k: v for k, v in nuevos.items()
                                     if not k.startswith("_")}),
            "hace_falta_reiniciar": en_frio,
        }

    # --- diagnóstico y mantenimiento ---

    def tls(self, host: str = "api.telegram.org") -> dict:
        """Si algo está abriendo el HTTPS, para poder verlo desde el móvil."""
        from ..diagnostico import probar_tls
        from ..tls import explicar

        datos = probar_tls(host, self.sesion.cliente.settings)
        if datos.get("interceptado"):
            datos["que_hacer"] = explicar(host)
        return datos

    def probar_nube(self, clave: str = "") -> dict:
        """¿Vale esta clave para la nube de Ollama? La llamada más barata que hay.

        Existe porque el 401 se descubría en mitad de un dictamen, después de
        montar el expediente entero, y ahí no se sabe si falla la clave, el
        modelo o la red.
        """
        from ..ajustes import cargar
        from ..analista import URL_NUBE, OllamaNoDisponible, _pedir_http

        usada = (clave or "").strip() or (cargar(self.ruta_ajustes).get("ollama_api_key")
                                          or self.api_key or "")
        if not usada:
            return {"vale": False, "nota": "No hay ninguna clave que probar."}
        try:
            datos = _pedir_http(f"{URL_NUBE}/api/tags", None, timeout=30.0,
                                api_key=usada, contexto=self._tls())
        except (OllamaNoDisponible, OSError) as exc:
            return {"vale": False, "nota": str(exc), "huella": _huella(usada)}
        modelos = (datos or {}).get("models") or []
        return {"vale": True, "modelos": len(modelos),
                "huella": _huella(usada),
                "nota": f"La clave vale: {len(modelos)} modelos en la nube."}

    def _tls(self):
        from ..tls import contexto

        return contexto(self.ca_bundle, self.sin_verificar)

    def diagnostico(self, con_red: bool = False) -> dict:
        """Lo que dice ``cancha doctor``, para poder verlo desde el móvil."""
        from ..diagnostico import diagnostico

        with self.cerrojo:
            return diagnostico(self.sesion.cliente, con_red=con_red)

    def limpiar_cache(self) -> dict:
        from ..diagnostico import limpiar_cache

        with self.cerrojo:
            return limpiar_cache()

    def descubrir_ligas(self, grupos=None) -> dict:
        """Busca los ids que faltan del catálogo. Necesita red y tarda."""
        from ..ligas import asegurar, resumen_catalogo

        with self.cerrojo:
            # Por nombre y no por posición: los dos primeros argumentos son el
            # cliente y la memoria, y cambiarlos de orden no da un error claro
            # sino un AttributeError a media página. Ya pasó una vez.
            encontradas = asegurar(cliente=self.sesion.cliente,
                                   almacen=self.sesion.almacen, grupos=grupos)
            return {"encontradas": encontradas, "catalogo": resumen_catalogo(self.sesion.almacen)}

    def red(self, puerto: int | None = None) -> dict:
        """Por dónde se llega a este servidor, con el QR ya dibujado.

        Sirve para lo de siempre: estás en el ordenador y quieres abrirlo en el
        móvil. En vez de dictarte una IP, se pinta el mismo QR que el terminal.
        """
        from .qr import NoCabe, matriz

        puerto = puerto or self.puerto
        sufijo = f"/?clave={quote(self.clave)}" if self.clave else "/"
        urls = [f"http://{ip}:{puerto}{sufijo}" for ip in ips_locales()]
        salida: dict[str, Any] = {"urls": urls, "con_clave": bool(self.clave),
                                  "abierto_a_la_red": self.abierto}
        if urls:
            with suppress(NoCabe):
                salida["qr"] = matriz(urls[0])
        return salida

    # --- briefings ---

    def briefing(self, fecha: str) -> dict | None:
        from ..briefing import cargar

        return cargar(fecha, self.carpeta_briefings)

    # --- barrido en segundo plano ---

    def estado_barrido(self) -> dict:
        return {k: (v[-40:] if k == "lineas" else v) for k, v in self.barrido.items()}

    def lanzar_barrido(self, fecha: str | None, grupos: list[str] | None, maximo: int,
                       ultimos: int = 6) -> dict:
        if self.barrido["en_marcha"]:
            return {"error": "Ya hay un barrido en marcha.", **self.estado_barrido()}
        self.barrido.update({"en_marcha": True, "lineas": [], "resumen": None,
                             "empezado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "terminado": None})

        def correr() -> None:
            from ..barrido import barrer

            try:
                with self.cerrojo:
                    resumen = barrer(self.sesion.cliente, self.sesion.almacen, fecha=fecha,
                                     grupos=grupos, ultimos=ultimos, maximo_peticiones=maximo,
                                     avisar=self.barrido["lineas"].append)
                self.barrido["resumen"] = resumen
            except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde
                self.barrido["lineas"].append(f"error: {exc}")
                self.barrido["resumen"] = {"error": str(exc)}
            finally:
                self.barrido["en_marcha"] = False
                self.barrido["terminado"] = datetime.now(timezone.utc).isoformat(
                    timespec="seconds")

        self._hilo_barrido = threading.Thread(target=correr, daemon=True)
        self._hilo_barrido.start()
        return self.estado_barrido()

    def esperar_barrido(self, segundos: float = 30) -> None:
        """Para los tests: espera a que el barrido acabe."""
        if self._hilo_barrido:
            self._hilo_barrido.join(segundos)

    def close(self) -> None:
        self.sesion.close()


# ---------------------------------------------------------------------- icono

def icono_png(lado: int = 192) -> bytes:
    """Un icono dibujado a mano: campo verde, círculo central y línea de medio.

    iOS exige un PNG para la pantalla de inicio y aquí no hay librerías de
    imagen: se escribe el PNG con ``zlib`` y ``struct``, que siempre están.
    """
    fondo, linea = (26, 94, 62), (240, 244, 240)
    centro, radio = lado / 2, lado * 0.22
    filas = []
    for y in range(lado):
        fila = bytearray([0])
        for x in range(lado):
            dx, dy = x - centro + 0.5, y - centro + 0.5
            distancia = (dx * dx + dy * dy) ** 0.5
            en_circulo = abs(distancia - radio) < lado * 0.028
            en_linea = abs(dx) < lado * 0.016 and lado * 0.12 < y < lado * 0.88
            punto = distancia < lado * 0.035
            fila += bytes(linea if (en_circulo or en_linea or punto) else fondo)
        filas.append(bytes(fila))

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    cabecera = struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", cabecera)
            + trozo(b"IDAT", zlib.compress(b"".join(filas), 9)) + trozo(b"IEND", b""))


# ---------------------------------------------------------------- peticiones

class Manejador(BaseHTTPRequestHandler):
    """Una petición. El estado vive en ``self.server.app``."""

    server_version = f"cancha/{__version__}"

    @property
    def app(self) -> Servidor:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, formato: str, *args: Any) -> None:
        if getattr(self.server, "callado", True):
            return
        super().log_message(formato, *args)

    # --- respuestas ---

    #: Si ya se han mandado cabeceras. Sin esto, el guardia de abajo podría
    #: escribir un error encima de una respuesta a medio enviar y dejar al
    #: navegador leyendo basura.
    _respondido = False

    def _json(self, datos: Any, estado: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self._respondido = True
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _fichero(self, nombre: str) -> None:
        ruta = (ESTATICO / nombre).resolve()
        if not str(ruta).startswith(str(ESTATICO.resolve())) or not ruta.is_file():
            self._json({"error": f"No existe {nombre}."}, 404)
            return
        cuerpo = ruta.read_bytes()
        self._respondido = True
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(ruta.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _png(self, lado: int) -> None:
        cuerpo = icono_png(lado)
        self._respondido = True
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _autorizado(self, consulta: dict) -> bool:
        if not self.app.clave:
            return True
        dada = self.headers.get("X-Clave") or (consulta.get("clave") or [""])[0]
        return dada == self.app.clave

    def _cuerpo(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return datos if isinstance(datos, dict) else {}

    def _analista(self, cuerpo: dict) -> None:
        """Contesta en NDJSON, un paso por línea, según van pasando.

        Sin ``Content-Length``: el cuerpo lo cierra la conexión. Así el
        navegador ve «estoy pidiendo los tiros» mientras ocurre, en vez de un
        minuto de reloj girando y luego un párrafo.
        """
        from ..analista import OllamaNoDisponible

        pregunta = str(cuerpo.get("pregunta") or "").strip()
        if not pregunta:
            return self._json({"error": "Falta la pregunta."}, 400)
        self._respondido = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def escribir(objeto: dict) -> None:
            try:
                self.wfile.write(
                    (json.dumps(objeto, ensure_ascii=False, default=str) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        try:
            salida = self.app.preguntar(
                pregunta, historial=cuerpo.get("historial"),
                modelo=cuerpo.get("modelo"),
                al_paso=lambda paso: escribir({"paso": paso.as_dict()}))
            escribir({"fin": {k: v for k, v in salida.items() if k != "pasos"}})
        except OllamaNoDisponible as exc:
            with suppress(OSError):
                escribir({"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - el servidor no se cae por una pregunta
            with suppress(OSError):
                escribir({"error": f"{type(exc).__name__}: {exc}"})

    # --- rutas ---

    def _atender(self, que: Any, nombre: str) -> None:
        """Ejecuta un manejador y convierte cualquier fallo en una respuesta.

        Sin esto, una herramienta que revienta se lleva por delante el hilo de
        la petición: en la consola sale una traza de veinte líneas y en el
        navegador se queda una conexión muerta, sin mensaje y sin saber qué ha
        pasado. La traza se sigue imprimiendo —es tu consola y sirve para
        arreglarlo— pero la página recibe un error que puede enseñar.
        """
        import traceback

        try:
            que()
        except (BrokenPipeError, ConnectionResetError):
            pass                       # se ha ido; no hay a quién contestar
        except Exception as exc:  # noqa: BLE001 - el servidor no se cae por una petición
            traceback.print_exc()
            if not self._respondido:
                with suppress(OSError):
                    self._json({
                        "error": f"{type(exc).__name__}: {exc}",
                        "donde": f"{nombre} {self.path}",
                        "que_hacer": "La traza entera está en la consola del "
                                     "ordenador. Lo demás sigue funcionando.",
                    }, 500)

    def do_GET(self) -> None:  # noqa: N802 - nombre que exige http.server
        self._atender(self._get, "GET")

    def do_POST(self) -> None:  # noqa: N802
        self._atender(self._post, "POST")

    def _get(self) -> None:
        url = urlparse(self.path)
        ruta, consulta = unquote(url.path), parse_qs(url.query)

        if ruta in ("/", "/index.html"):
            return self._fichero("index.html")
        if ruta == "/icono-180.png":
            return self._png(180)
        if ruta == "/icono-192.png":
            return self._png(192)
        if ruta == "/icono-512.png":
            return self._png(512)
        if not ruta.startswith("/api/"):
            return self._fichero(ruta.lstrip("/"))

        if not self._autorizado(consulta):
            return self._json({"error": "Hace falta la clave (cabecera X-Clave)."}, 401)
        if ruta == "/api/estado":
            return self._json(self.app.estado())
        if ruta == "/api/herramientas":
            return self._json(self.app.esquemas())
        if ruta == "/api/barrido":
            return self._json(self.app.estado_barrido())
        if ruta == "/api/analista":
            return self._json(self.app.estado_analista(
                (consulta.get("modelo") or [None])[0]))
        if ruta == "/api/diagnostico":
            con_red = (consulta.get("red") or ["0"])[0] not in ("0", "", "no")
            return self._json(self.app.diagnostico(con_red=con_red))
        if ruta == "/api/tls":
            return self._json(self.app.tls((consulta.get("host") or
                                            ["api.telegram.org"])[0]))
        if ruta == "/api/red":
            return self._json(self.app.red())
        if ruta == "/api/ajustes":
            return self._json(self.app.ajustes())
        if ruta.startswith("/api/tarea/"):
            return self._json(self.app.estado_tarea(ruta.rsplit("/", 1)[-1]))
        if ruta.startswith("/api/briefing/"):
            fecha = ruta.rsplit("/", 1)[-1]
            datos = self.app.briefing(fecha)
            if datos is None:
                return self._json({"error": f"No hay briefing guardado del {fecha}."}, 404)
            return self._json(datos)
        return self._json({"error": f"No existe {ruta}."}, 404)

    def _post(self) -> None:
        url = urlparse(self.path)
        ruta, consulta = unquote(url.path), parse_qs(url.query)
        if not self._autorizado(consulta):
            return self._json({"error": "Hace falta la clave (cabecera X-Clave)."}, 401)
        cuerpo = self._cuerpo()

        if ruta.startswith("/api/herramienta/"):
            nombre = ruta.rsplit("/", 1)[-1]
            resultado = self.app.ejecutar(nombre, cuerpo)
            estado = 404 if (isinstance(resultado, dict) and "disponibles" in resultado
                             and "error" in resultado) else 200
            return self._json(resultado, estado)
        if ruta == "/api/seguro":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.seguro(
                cuerpo.get("fecha") or None, grupos or None,
                calibrar=bool(cuerpo.get("calibrar")),
                umbral=float(cuerpo.get("umbral") or 0.65)))
        if ruta == "/api/analista":
            return self._analista(cuerpo)
        if ruta == "/api/ajustes":
            return self._json(self.app.poner_ajustes(cuerpo))
        if ruta == "/api/dictamenes":
            return self._json(self.app.dictamenes(
                str(cuerpo.get("partido") or ""),
                con_expediente=bool(cuerpo.get("con_expediente"))))
        if ruta == "/api/dictamen/borrar":
            return self._json(self.app.borrar_dictamen(cuerpo.get("id") or 0))
        if ruta == "/api/nube":
            return self._json(self.app.probar_nube(cuerpo.get("clave") or ""))
        if ruta == "/api/dictamen":
            return self._json(self.app.dictamen(str(cuerpo.get("partido") or ""),
                                                str(cuerpo.get("pregunta") or ""),
                                                str(cuerpo.get("crudo") or "todo")))
        if ruta == "/api/agentes":
            return self._json(self.app.agentes())
        if ruta == "/api/agente":
            return self._json(self.app.poner_agente(
                str(cuerpo.get("clave") or ""), cuerpo.get("agente") or {}))
        if ruta == "/api/agente/borrar":
            return self._json(self.app.borrar_agente(str(cuerpo.get("clave") or "")))
        if ruta == "/api/agente/correr":
            return self._json(self.app.correr_agente(
                str(cuerpo.get("clave") or ""), str(cuerpo.get("partido") or "")))
        if ruta == "/api/clasificacion":
            return self._json(self.app.clasificacion(
                cuerpo.get("desde") or None, cuerpo.get("hasta") or None))
        if ruta == "/api/briefing":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.lanzar_briefing(
                cuerpo.get("fecha") or None, grupos or None))
        if ruta == "/api/historia/plan":
            return self._json(self.app.plan_historia(
                int(cuerpo.get("anos") or 3), cuerpo.get("grupos") or None,
                cuerpo.get("secciones") or None))
        if ruta == "/api/historia":
            return self._json(self.app.lanzar_historia(
                int(cuerpo.get("anos") or 3), cuerpo.get("grupos") or None,
                cuerpo.get("secciones") or None, int(cuerpo.get("max") or 0)))
        if ruta == "/api/tarea/parar":
            return self._json(self.app.parar_tarea(str(cuerpo.get("nombre") or "")))
        if ruta == "/api/cache":
            return self._json(self.app.limpiar_cache())
        if ruta == "/api/ligas":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.descubrir_ligas(grupos or None))
        if ruta == "/api/barrido":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.lanzar_barrido(
                cuerpo.get("fecha") or None, grupos or None,
                int(cuerpo.get("max") or 0), int(cuerpo.get("ultimos") or 6)))
        return self._json({"error": f"No existe {ruta}."}, 404)


# ---------------------------------------------------------------- arrancar

def ip_local() -> str:
    """La IP de este ordenador en su red, para teclearla en el móvil."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no envía nada: solo elige interfaz
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


#: Los rangos que una wifi de casa usa de verdad. Una máquina con Docker, una
#: VPN o WSL tiene varias IP y solo una sirve, así que se ordenan en vez de
#: adivinar una y dejar al otro probando.
_PRIVADAS = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
             "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
             "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")


def ips_locales() -> list[str]:
    """Todas las IP por las que se puede llegar a este ordenador, la mejor primero.

    ``ip_local`` devuelve la de la ruta por defecto, que es la buena casi
    siempre. Casi: con una VPN levantada o Docker instalado hay varias, y si se
    enseña solo una y resulta ser la que no es, el móvil no entra y nadie sabe
    por qué. Se enseñan todas.
    """
    candidatas: list[str] = []

    def añadir(ip: str) -> None:
        if ip and ip not in candidatas and not ip.startswith("127."):
            candidatas.append(ip)

    añadir(ip_local())
    with suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            añadir(info[4][0])
    # Las privadas primero, manteniendo el orden dentro de cada grupo: la de la
    # ruta por defecto sigue siendo la primera de las suyas.
    return sorted(candidatas, key=lambda ip: 0 if ip.startswith(_PRIVADAS) else 1)


def construir(app: Servidor, host: str = "127.0.0.1", puerto: int = 8765,
              callado: bool = True) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.app = app  # type: ignore[attr-defined]
    servidor.callado = callado  # type: ignore[attr-defined]
    servidor.daemon_threads = True
    return servidor


def arrancar(app: Servidor, host: str = "127.0.0.1", puerto: int = 8765,
             abrir: bool = False, avisar=print, qr: bool = True,
             color: bool = True) -> int:
    """Sirve hasta Ctrl+C."""
    servidor = construir(app, host, puerto)
    puerto_real = servidor.server_address[1]
    # La página también enseña el QR, así que necesita saber esto.
    app.puerto = puerto_real
    app.abierto = host not in ("127.0.0.1", "localhost")
    avisar(f"cancha {__version__} · interfaz en http://127.0.0.1:{puerto_real}")
    if host not in ("127.0.0.1", "localhost"):
        sufijo = f"/?clave={quote(app.clave)}" if app.clave else "/"
        urls = [f"http://{ip}:{puerto_real}{sufijo}" for ip in ips_locales()]
        if urls:
            avisar("")
            avisar("  Desde el móvil, en la misma wifi. Apunta la cámara:")
            if qr:
                avisar("")
                for linea in dibujar_qr(urls[0], color=color).splitlines():
                    avisar("  " + linea)
                avisar("")
            for url in urls:
                avisar(f"    {url}")
            if len(urls) > 1:
                avisar("    (varias IP: el QR lleva a la primera; si no entra, prueba las otras)")
            avisar("  En iOS: Safari → Compartir → «Añadir a pantalla de inicio»")
        if not app.clave:
            avisar("  (sin clave: cualquiera en tu red puede usarla; pon --clave si te importa)")
    avisar("Ctrl+C para parar.")
    if abrir:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{puerto_real}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        app.close()
    return 0


__all__ = ["Servidor", "Manejador", "construir", "arrancar", "icono_png",
           "ip_local", "ips_locales"]
