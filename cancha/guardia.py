"""La guardia nocturna: dejarlo encendido y que prepare el día siguiente solo.

La idea es sencilla. Por la noche no hay prisa y la API está tranquila, así que
es el momento de traerse los partidos de mañana y todo lo que cuesta
entenderlos. Por la mañana abres la interfaz y está hecho.

Una vuelta de guardia hace cuatro cosas, en este orden:

1. **Barrido** del día que viene: la agenda y el historial de quien juega.
2. **Abastecimiento** de los partidos que elijas, que es lo caro y lo que de
   verdad llena la memoria.
3. **Briefing** del día, guardado en disco.
4. **Casi seguro**, calibrado, para que abrir la pestaña no tenga que contar
   miles de partidos en ese momento.

**Lo de la suspensión, que es lo importante.** Si el ordenador se duerme de
verdad, Python deja de ejecutarse: no hay demonio que lo impida. Por eso
:func:`despierto` le pide al sistema que no suspenda mientras la guardia
trabaja. En Windows se hace con ``SetThreadExecutionState`` y funciona sin
instalar nada; la pantalla sí puede apagarse, que es lo que uno quiere de
noche. Fuera de Windows se avisa en vez de fingir que se ha hecho algo.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .almacen import Almacen
from .client import SofascoreClient
from .errors import SofascoreError

#: A qué hora se prepara el día siguiente, en hora local. Las tres de la
#: mañana: el ordenador está quieto y los partidos de mañana ya están puestos.
HORA_POR_DEFECTO = "03:00"
#: Cuántos partidos del día se abastecen a fondo. Todos sería caro y casi
#: siempre innecesario; los que juegan las competiciones que sigues, no.
ABASTECER_POR_DEFECTO = 12
#: Dónde queda escrito lo que hace, para poder mirarlo por la mañana.
REGISTRO_POR_DEFECTO = "datos/guardia.log"


# --------------------------------------------------------------- el registro

@dataclass
class Diario:
    """Escribe a la vez en pantalla y en un fichero, y se acuerda de los fallos.

    Un demonio que solo imprime no sirve: por la mañana la consola ya no está.
    Y uno que solo escribe a fichero tampoco, porque mientras lo miras quieres
    verlo. Los errores se guardan aparte para poder resumirlos al final, que es
    lo que de verdad se lee.
    """

    ruta: str | Path | None = REGISTRO_POR_DEFECTO
    en_pantalla: bool = True
    errores: list[str] = field(default_factory=list)
    _fichero: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.ruta:
            destino = Path(self.ruta)
            destino.parent.mkdir(parents=True, exist_ok=True)
            self._fichero = destino.open("a", encoding="utf-8")

    def __call__(self, texto: str, nivel: str = "·") -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        linea = f"{marca} {nivel} {texto}"
        if self.en_pantalla:
            print(linea, flush=True)
        if self._fichero:
            self._fichero.write(f"{datetime.now():%Y-%m-%d} {linea}\n")
            self._fichero.flush()

    def error(self, texto: str) -> None:
        """Un fallo. Se marca para que se vea de un vistazo entre cien líneas."""
        self.errores.append(texto)
        self(texto, nivel="✗ ERROR")

    def aviso(self, texto: str) -> None:
        self(texto, nivel="⚠")

    def titulo(self, texto: str) -> None:
        self("")
        self(f"── {texto} " + "─" * max(0, 56 - len(texto)))

    def cerrar(self) -> None:
        if self._fichero:
            self._fichero.close()
            self._fichero = None


# ----------------------------------------------------------- no te me duermas

def puede_impedir_suspension() -> bool:
    """¿Sabemos decirle a este sistema que no se duerma? Solo en Windows."""
    import ctypes

    return getattr(ctypes, "windll", None) is not None


@contextmanager
def despierto(avisar: Callable[[str], None] | None = None):
    """Pide al sistema que no se suspenda mientras dure el bloque.

    Esto es lo que hace que «lo dejo encendido por la noche» signifique algo. Un
    proceso de Python no impide la suspensión por sí solo: si el equipo se
    duerme, el proceso se congela con él y por la mañana no ha hecho nada.

    En Windows se le dice al sistema con ``SetThreadExecutionState``. Se pide
    ``ES_SYSTEM_REQUIRED`` pero **no** ``ES_DISPLAY_REQUIRED``: la máquina sigue
    despierta y la pantalla se apaga, que de noche es exactamente lo que se
    quiere. Fuera de Windows no se toca nada y se dice en voz alta, porque
    fingir que se ha hecho algo es peor que no hacerlo.
    """
    decir = avisar or (lambda _t: None)
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        decir("No puedo impedir la suspensión en este sistema (solo sé hacerlo en "
              "Windows). Si el equipo se duerme, la guardia se duerme con él: "
              "desactiva la suspensión en los ajustes de energía.")
        yield False
        return

    continuo, sistema = 0x80000000, 0x00000001
    try:
        anterior = windll.kernel32.SetThreadExecutionState(continuo | sistema)
    except OSError as exc:            # noqa: BLE001 - se enseña, no se esconde
        decir(f"No he podido pedir que no se suspenda: {exc}")
        yield False
        return
    decir("El equipo no se suspenderá mientras la guardia esté en marcha "
          "(la pantalla sí puede apagarse).")
    try:
        yield True
    finally:
        if anterior:
            windll.kernel32.SetThreadExecutionState(continuo)


# ------------------------------------------------------------- una vuelta

def preparar_dia(cliente: SofascoreClient, almacen: Almacen, fecha: str | None = None,
                 grupos: list[str] | None = None, ultimos: int = 6,
                 abastecer_partidos: int = ABASTECER_POR_DEFECTO,
                 maximo_peticiones: int = 0,
                 carpeta_briefings: str = "datos/briefings",
                 diario: Diario | None = None) -> dict:
    """Todo lo que hace falta para que mañana esté listo. Se puede repetir.

    El tope de peticiones se reparte entre las cuatro fases y se comprueba
    entre partido y partido, así que cortar por la mitad no rompe nada: lo
    guardado queda guardado y la vuelta siguiente sigue por donde falte.
    """
    from .barrido import agenda, barrer

    decir = diario or Diario(ruta=None)
    dia = fecha or _manana()
    inicio = cliente.stats.requests

    def gastadas() -> int:
        return cliente.stats.requests - inicio

    def queda_cupo() -> bool:
        return not maximo_peticiones or gastadas() < maximo_peticiones

    resumen: dict[str, Any] = {"fecha": dia, "empezado": _ahora()}
    decir.titulo(f"Preparando el {dia}")

    # 1. El barrido: la agenda del día y el historial de quien juega.
    try:
        resumen["barrido"] = barrer(
            cliente, almacen, fecha=dia, grupos=grupos, ultimos=ultimos,
            maximo_peticiones=maximo_peticiones, avisar=lambda t: decir(t))
        decir(f"Barrido: {resumen['barrido']['guardados']} partidos nuevos, "
              f"{resumen['barrido']['peticiones']} peticiones.")
    except (SofascoreError, OSError) as exc:
        decir.error(f"El barrido ha fallado: {exc}")
        resumen["barrido"] = {"error": str(exc)}

    # 2. El abastecimiento: lo caro, y lo que de verdad llena la memoria.
    resumen["abastecidos"] = []
    if abastecer_partidos and queda_cupo():
        decir.titulo(f"Abasteciendo hasta {abastecer_partidos} partidos")
        try:
            partidos = agenda(cliente, dia, grupos, almacen)[:abastecer_partidos]
        except (SofascoreError, OSError) as exc:
            decir.error(f"No he podido leer la agenda del {dia}: {exc}")
            partidos = []
        for evento in partidos:
            if not queda_cupo():
                decir.aviso(f"Tope de {maximo_peticiones} peticiones alcanzado "
                            f"({gastadas()} gastadas). Sigo mañana por donde falte.")
                break
            resumen["abastecidos"].append(
                _abastecer_uno(cliente, almacen, evento, maximo_peticiones,
                               gastadas(), decir))

    # 3. El briefing del día, escrito en disco.
    if queda_cupo():
        decir.titulo("Briefing")
        try:
            from .briefing import briefing, guardar

            datos = briefing(almacen, cliente, fecha=dia, grupos=grupos)
            rutas = guardar(datos, carpeta_briefings)
            resumen["briefing"] = {"partidos": len(datos.get("partidos") or []),
                                   "fichero": str(rutas.get("markdown", ""))}
            decir(f"Briefing del {dia} con {resumen['briefing']['partidos']} partidos.")
        except (SofascoreError, OSError, KeyError) as exc:
            decir.error(f"El briefing ha fallado: {exc}")
            resumen["briefing"] = {"error": str(exc)}

    # 4. El registro: apuntar lo que se predice hoy y resolver lo de ayer.
    #    Este es el paso que convierte esto en algo que se puede juzgar: sin
    #    apuntar antes, nadie puede decir después si acertaba.
    decir.titulo("Registro de predicciones")
    try:
        from .registro import anotar, resolver

        apuntadas = 0
        for evento in agenda(cliente, dia, grupos, almacen):
            apuntadas += anotar(almacen, evento, cliente=cliente).get("guardadas", 0)
        resueltas = resolver(almacen)
        resumen["registro"] = {"apuntadas": apuntadas, **resueltas}
        decir(f"{apuntadas} predicciones apuntadas para el {dia}; "
              f"{resueltas['resueltas']} resueltas de días anteriores.")
    except (SofascoreError, OSError, KeyError, ValueError) as exc:
        decir.error(f"El registro ha fallado: {exc}")
        resumen["registro"] = {"error": str(exc)}

    # 5. Casi seguro, calibrado, para que abrirlo mañana sea instantáneo.
    decir.titulo("Casi seguro")
    try:
        from .seguro import calibrar

        calibracion = calibrar(almacen)
        resumen["seguro"] = {
            "partidos_mirados": calibracion["partidos_mirados"],
            "utiles": calibracion["utiles"],
            "aguantan_fuera_de_muestra": calibracion.get("aguantan_fuera_de_muestra", []),
        }
        decir(f"Calibrado con {calibracion['partidos_mirados']} partidos: "
              f"{len(calibracion['utiles'])} patrones útiles, "
              f"{len(resumen['seguro']['aguantan_fuera_de_muestra'])} aguantan fuera "
              "de muestra.")
    except (SofascoreError, OSError, KeyError) as exc:
        decir.error(f"La calibración ha fallado: {exc}")
        resumen["seguro"] = {"error": str(exc)}

    resumen["peticiones"] = gastadas()
    resumen["terminado"] = _ahora()
    resumen["errores"] = list(decir.errores)
    decir.titulo("Resumen")
    decir(f"{gastadas()} peticiones · {len(decir.errores)} errores")
    for error in decir.errores:
        decir(f"    {error}")
    almacen.anotar("ultima_guardia", resumen["terminado"])
    almacen.anotar("ultima_guardia_fecha", dia)
    return resumen


def _abastecer_uno(cliente, almacen, evento, maximo_peticiones: int,
                   ya_gastadas: int, decir: Diario) -> dict:
    """Un partido del día, con su contexto. Los fallos no tumban la vuelta."""
    from .abastecer import abastecer

    nombre = f"{evento.home} - {evento.away}"
    try:
        restante = max(0, maximo_peticiones - ya_gastadas) if maximo_peticiones else 0
        salida = abastecer(cliente, almacen, evento, maximo_peticiones=restante,
                           avisar=lambda t: decir(f"  {t}"))
        decir(f"{nombre}: {salida['guardados']} traídos, "
              f"{salida['ya_estaban']} ya estaban.")
        return {"partido": nombre, "id": evento.id, **{
            k: salida[k] for k in ("guardados", "ya_estaban", "peticiones", "completo")}}
    except (SofascoreError, OSError) as exc:
        decir.error(f"{nombre}: {exc}")
        return {"partido": nombre, "id": evento.id, "error": str(exc)}


# ------------------------------------------------------------------ vigilar

def vigilar(cliente: SofascoreClient, almacen: Almacen, a_las: str = HORA_POR_DEFECTO,
            dias_vista: int = 1, grupos: list[str] | None = None, ultimos: int = 6,
            abastecer_partidos: int = ABASTECER_POR_DEFECTO,
            maximo_peticiones: int = 0, carpeta_briefings: str = "datos/briefings",
            registro: str | Path | None = REGISTRO_POR_DEFECTO,
            ahora: bool = False, vueltas: int = 0,
            en_pantalla: bool = True, dormir=time.sleep,
            releer: Callable[[], dict] | None = None) -> dict:
    """Se queda esperando y prepara el día siguiente cada noche.

    ``vueltas`` limita cuántas hace y luego sale; ``0`` es para siempre.
    ``ahora`` hace una en cuanto arranca, sin esperar a la hora, que es como se
    comprueba que funciona sin quedarse hasta las tres de la mañana.

    ``releer`` devuelve los ajustes actuales y se consulta mientras espera. Es
    lo que hace que cambiar la hora desde el móvil valga para algo: sin esto,
    el ajuste no se miraría hasta la vuelta siguiente, que es dentro de un día.
    """
    decir = Diario(ruta=registro, en_pantalla=en_pantalla)
    hechas: list[dict] = []
    try:
        decir.titulo("Guardia en marcha")
        decir(f"Cada día a las {a_las}, preparo el día +{dias_vista}.")
        if registro:
            decir(f"Lo que vaya haciendo queda en {registro}.")
        with despierto(decir.aviso):
            while True:
                if ahora and not hechas:
                    pendiente = 0.0
                else:
                    a_las, dias_vista = _relectura(releer, a_las, dias_vista)
                    pendiente = segundos_hasta(a_las)
                    decir(f"Siguiente vuelta en {_legible(pendiente)} "
                          f"(a las {a_las}).")
                    # Las variables se atan aquí a propósito: una lambda que
                    # cierre sobre la variable del bucle mira el valor de la
                    # última vuelta, no el de esta.
                    def _la_han_cambiado(puesta=a_las, dias=dias_vista) -> bool:
                        return _relectura(releer, puesta, dias)[0] != puesta

                    if _dormir_a_trozos(pendiente, dormir, cambiado=_la_han_cambiado):
                        a_las, dias_vista = _relectura(releer, a_las, dias_vista)
                        decir(f"La hora ha cambiado a las {a_las}; recalculo.")
                        continue
                fecha = (datetime.now() + timedelta(days=dias_vista)).strftime("%Y-%m-%d")
                decir.errores.clear()
                hechas.append(preparar_dia(
                    cliente, almacen, fecha=fecha, grupos=grupos, ultimos=ultimos,
                    abastecer_partidos=abastecer_partidos,
                    maximo_peticiones=maximo_peticiones,
                    carpeta_briefings=carpeta_briefings, diario=decir))
                if vueltas and len(hechas) >= vueltas:
                    break
    except KeyboardInterrupt:
        decir("")
        decir("Guardia detenida. Lo guardado queda guardado.")
    finally:
        decir.cerrar()
    return {"vueltas": hechas, "cuantas": len(hechas)}


def _relectura(releer, hora: str, dias: int) -> tuple[str, int]:
    """La hora y los días que digan los ajustes ahora mismo, si hay quien lo diga."""
    if releer is None:
        return (hora, dias)
    try:
        frescos = releer() or {}
        suya = (frescos.get("guardia") or {})
        return (suya.get("hora") or hora, suya.get("dias", dias))
    except Exception:  # noqa: BLE001 - unos ajustes rotos no paran la guardia
        return (hora, dias)


def segundos_hasta(hora: str, desde: datetime | None = None) -> float:
    """Cuánto falta para la próxima vez que sean las ``HH:MM``, en local."""
    ahora = desde or datetime.now()
    try:
        h, m = (int(x) for x in hora.split(":", 1))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Hora {hora!r}: se escribe como 03:00.") from exc
    objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if objetivo <= ahora:
        objetivo += timedelta(days=1)
    return (objetivo - ahora).total_seconds()


def _dormir_a_trozos(segundos: float, dormir=time.sleep, trozo: float = 5.0,
                     cambiado: Callable[[], bool] | None = None) -> bool:
    """Dormir en trozos, mirando de reojo si algo ha cambiado.

    Dos razones para no dormir de una sentada: que Ctrl+C responda al momento
    y no dentro de ocho horas, y que cambiar la hora de la guardia desde el
    móvil sirva de algo. Si `cambiado` dice que sí, se despierta y devuelve
    True para que quien llama vuelva a calcular cuándo toca.
    """
    restante = segundos
    while restante > 0:
        dormir(min(trozo, restante))
        restante -= trozo
        if cambiado is not None and cambiado():
            return True
    return False


def _legible(segundos: float) -> str:
    if segundos < 60:
        return f"{int(segundos)} s"
    horas, resto = divmod(int(segundos), 3600)
    minutos = resto // 60
    return f"{horas} h {minutos} min" if horas else f"{minutos} min"


def _manana() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = ["ABASTECER_POR_DEFECTO", "HORA_POR_DEFECTO", "REGISTRO_POR_DEFECTO",
           "Diario", "despierto", "preparar_dia", "puede_impedir_suspension",
           "segundos_hasta", "vigilar"]
