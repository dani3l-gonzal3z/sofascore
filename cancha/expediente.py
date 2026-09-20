"""Todo lo que se sabe de un partido, en un documento, para dárselo a un modelo.

El analista de casa trabaja a cachitos: pide una herramienta, lee, pide otra.
Con un modelo de 8B es lo correcto —no le cabe más— pero con uno grande es
desperdiciarlo: lo que se quiere de un modelo así no es que sepa qué pedir,
sino que **vea todo a la vez y ate cabos**. Que se dé cuenta de que el equipo
que mejor llega es el que peor defiende los córners y enfrente hay alguien que
vive de eso.

Así que esto monta el expediente entero de una sola vez —pronóstico, estilos,
cruces, jugadores, árbitro, mercado, lo que casi siempre pasa y los últimos
partidos de los dos— y lo escribe en un texto compacto que cabe en un prompt.

**Los números ya están calculados.** El expediente no trae datos en bruto para
que el modelo los promedie: trae las cuentas hechas, con su muestra al lado.
El modelo pone el razonamiento; la aritmética la pone Python. Es la misma
línea de siempre, y con un modelo grande importa más, no menos: se equivoca
con más aplomo.

**Y ojo con el tamaño.** Medido: 2.263 caracteres —565 tokens aproximados— en
un partido sin historia detrás, y unos 1.100 más cuando la memoria ya tiene los
seis anteriores de cada equipo y los seis cruces, que es como se usa. O sea del
orden de 3.500 caracteres y 900 tokens por partido. Si lo mandas a la nube, eso
es lo que pagas; ``tamano`` lo dice antes de que lo mandes, y
``--solo-expediente`` lo enseña entero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .almacen import Almacen

#: Cuántos partidos anteriores de cada equipo se listan uno a uno.
ULTIMOS = 6
#: Y cuántos enfrentamientos entre ellos.
ENTRE_ELLOS = 6
#: Cuántos jugadores a seguir por equipo.
JUGADORES = 4


def expediente(almacen: Almacen, partido, cliente=None, ultimos: int = ULTIMOS,
               con_seguro: bool = True) -> dict:
    """Reúne todo lo que hay de un partido. Cada parte, si falla, se dice."""
    from .previa import _resolver, previa
    from .pronostico import pronostico

    evento = partido if hasattr(partido, "home") else _resolver(almacen, partido, cliente)
    if evento is None:
        return {"disponible": False,
                "nota": "No encuentro ese partido ni en la memoria ni en la API."}

    local = evento.kickoff_local
    salida: dict[str, Any] = {
        "disponible": True,
        # Un informe lleva su fecha y de qué se ha sacado. Sin esto, un
        # expediente guardado no se puede fechar y un modelo no sabe si lo que
        # lee es de esta mañana o de hace tres semanas.
        "preparado_el": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "partidos_en_memoria": _cuantos_hay(almacen),
        "partido": {
            "id": evento.id,
            "local": evento.home.name,
            "visitante": evento.away.name,
            "fecha": evento.date,
            "hora_local": local.strftime("%H:%M") if local else None,
            "hora_utc": evento.kickoff.strftime("%H:%M") if evento.kickoff else None,
            "competicion": evento.tournament,
            "sede": evento.venue,
            "arbitro": evento.referee,
            "estado": evento.status_description or evento.status_type,
        },
    }
    salida["pronostico"] = _o_nota(lambda: pronostico(almacen, evento, cliente=cliente))
    salida["previa"] = _o_nota(lambda: previa(almacen, evento, cliente=cliente,
                                              ultimos=ultimos,
                                              jugadores_por_equipo=JUGADORES))
    salida["ultimos_partidos"] = _ultimos_de_los_dos(almacen, evento, ultimos)
    salida["entre_ellos"] = _entre_ellos(almacen, evento)
    if con_seguro:
        salida["casi_seguro"] = _o_nota(lambda: _seguro_de(almacen, cliente, evento))

    texto = a_texto(salida)
    salida["tamano"] = {
        "caracteres": len(texto),
        # Regla gruesa y suficiente: cuatro caracteres por token en castellano.
        # Para decidir si mandarlo a un sitio donde se paga, sobra.
        "tokens_aprox": len(texto) // 4,
    }
    return salida


def _cuantos_hay(almacen) -> int | str:
    """Cuántos partidos hay guardados. Si no se puede saber, se dice."""
    try:
        return almacen.resumen()["partidos"]
    except Exception:  # noqa: BLE001 - un dato de cabecera no tumba el expediente
        return "?"


def _o_nota(traer) -> dict:
    """Ejecuta una parte del expediente; si falla, lo cuenta en vez de caerse.

    Un expediente al que le falta el árbitro sigue valiendo. Uno que revienta
    entero porque faltaba el árbitro, no.
    """
    from .errors import SofascoreError

    try:
        return traer()
    except (SofascoreError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"disponible": False, "nota": f"No se ha podido montar: {exc}"}


def _ultimos_de_los_dos(almacen: Almacen, evento, ultimos: int) -> dict:
    salida = {}
    for lado, equipo in (("local", evento.home), ("visitante", evento.away)):
        if not equipo.id:
            continue
        filas = almacen.partidos_de_equipo(equipo.id, ultimos=ultimos,
                                           antes_de=evento.date or None)
        salida[lado] = {
            "equipo": equipo.name,
            "partidos": [_resumir(f, equipo.id) for f in filas],
        }
    return salida


def _entre_ellos(almacen: Almacen, evento) -> dict:
    if not (evento.home.id and evento.away.id):
        return {"partidos": []}
    filas = almacen.consulta(
        """SELECT * FROM partidos
           WHERE ((local_id = ? AND visitante_id = ?) OR (local_id = ? AND visitante_id = ?))
             AND estado = 'finished' AND (? = '' OR fecha < ?)
           ORDER BY momento DESC LIMIT ?""",
        (evento.home.id, evento.away.id, evento.away.id, evento.home.id,
         evento.date or "", evento.date or "", ENTRE_ELLOS))
    return {"partidos": [_resumir(f, evento.home.id) for f in filas]}


def _resumir(fila: dict, desde: int | None) -> dict:
    """Un partido en una línea, visto desde uno de los dos equipos."""
    es_local = fila.get("local_id") == desde
    favor = fila.get("goles_local") if es_local else fila.get("goles_visitante")
    contra = fila.get("goles_visitante") if es_local else fila.get("goles_local")
    return {
        "fecha": fila.get("fecha"),
        "partido": f"{fila.get('local')} {fila.get('goles_local')}-"
                   f"{fila.get('goles_visitante')} {fila.get('visitante')}",
        "donde": "casa" if es_local else "fuera",
        "resultado": ("G" if (favor or 0) > (contra or 0) else
                      "E" if favor == contra else "P"),
        "competicion": fila.get("liga"),
    }


def _seguro_de(almacen: Almacen, cliente, evento) -> dict:
    """Los patrones que se cumplen en **este** partido, no los del día entero."""
    from .seguro import avisos

    datos = avisos(almacen, cliente, eventos=[evento], umbral=0.6)
    return {
        "avisos": datos.get("avisos") or [],
        "calibrado_con": datos.get("calibrado_con"),
        "lo_que_no_dice": datos.get("lo_que_no_dice"),
    }


# --------------------------------------------------------------- el documento

#: Cómo leer el documento. Va dentro del propio expediente, antes de los datos,
#: porque un modelo que no sabe qué es «n=» o qué significa «suelo» se inventa
#: la interpretación, y eso no se arregla en las instrucciones: se arregla
#: diciéndolo al lado de los números.
CLAVE_DE_LECTURA = """\
CÓMO LEER ESTE DOCUMENTO
- n=X es el número de partidos sobre los que está medida esa cifra. Una cifra
  con n bajo no es una cifra: es un indicio. Nada por debajo de n=4 se afirma.
- Las probabilidades van en % y salen de un cálculo, no de una opinión.
- xG = goles esperados. «concede» = lo que le hacen a él, no lo que hace.
- «sobre su liga» = diferencia porcentual contra la media de su competición,
  excluyéndose a sí mismo de esa media.
- «suelo» = extremo inferior del intervalo de Wilson al 95 %: lo que la muestra
  sostiene, no lo que se observó.
- «fuera de muestra» = el patrón se midió con el 70 % más antiguo del historial
  y se comprobó en el 30 % más nuevo, que no participó en elegirlo.
- Las horas son locales y, entre paréntesis, UTC.
- Todo está cortado en la fecha del partido: aquí no hay nada posterior."""

#: Los apartados, en orden y numerados. Numerarlos no es cosmética: hace que se
#: pueda citar «el apartado 3 dice» y que el modelo no confunda el perfil de un
#: equipo con el del rival cuando el documento es largo.
APARTADOS = ("Ficha del partido", "Pronóstico calculado", "Mercado",
             "Perfil de los dos equipos", "Últimos partidos", "Árbitro",
             "Patrones medidos sobre el historial", "Límites de este expediente")


def a_texto(datos: dict) -> str:
    """El expediente como documento para un modelo: ordenado, fechado y con su n.

    La estructura es la de un informe y no la de un volcado a propósito. Un
    modelo grande lee mejor un documento con apartados numerados, una clave de
    lectura delante y la muestra pegada a cada número, y —lo que más importa—
    se inventa menos: cuando el documento dice de dónde sale cada cifra, es más
    difícil colar una que no está.
    """
    if not datos.get("disponible"):
        return datos.get("nota", "No hay expediente.")

    p = datos["partido"]
    hora = p.get("hora_local") or p.get("hora_utc") or ""
    utc = f" ({p['hora_utc']} UTC)" if p.get("hora_utc") and p.get("hora_local") else ""
    lineas = [
        f"EXPEDIENTE DE PARTIDO — {p['local']} vs {p['visitante']}",
        f"Competición: {p['competicion']} · Fecha: {p['fecha']} {hora}{utc}",
        (f"Sede: {p['sede']}" if p.get("sede") else "Sede: no consta")
        + (f" · Árbitro designado: {p['arbitro']}" if p.get("arbitro")
           else " · Árbitro: no consta"),
        f"Preparado por cancha el {datos.get('preparado_el', '')} "
        f"con {datos.get('partidos_en_memoria', '?')} partidos en memoria",
        "",
        CLAVE_DE_LECTURA,
        "",
        "ÍNDICE",
    ]
    lineas += [f"  {n}. {titulo}" for n, titulo in enumerate(APARTADOS, 1)]
    lineas += ["", f"## 1. {APARTADOS[0]}",
               f"{p['local']} (local) contra {p['visitante']} (visitante), "
               f"{p['competicion']}, {p['fecha']}.", ""]
    lineas += _texto_pronostico(datos.get("pronostico") or {})
    # Aparte del pronóstico a propósito: aunque no haya pronóstico, el mercado
    # es lo primero que hay que mirar, y antes se iba con él.
    lineas += _texto_mercado(datos.get("pronostico") or {})
    lineas += _texto_equipos(datos.get("previa") or {})
    lineas += _texto_ultimos(datos.get("ultimos_partidos") or {},
                             datos.get("entre_ellos") or {})
    lineas += _texto_arbitro(datos.get("previa") or {})
    lineas += _texto_seguro(datos.get("casi_seguro") or {})
    lineas += [
        "",
        f"## {len(APARTADOS)}. {APARTADOS[-1]}",
        "Lo que este expediente NO contiene, y por tanto no se puede afirmar:",
        "- Alineaciones de hoy, lesiones, sanciones ni rotaciones.",
        "- Si el partido se juega a algo: puesto en la tabla, eliminatoria, descenso.",
        "- El tiempo que va a hacer, ni el estado del campo.",
        "- Nada posterior a la fecha del partido: está cortado ahí a propósito,",
        "  para que no se cuele el futuro en el análisis.",
        "- Nada que no esté escrito arriba. Si una cifra no aparece, no existe",
        "  para este análisis.",
    ]
    return "\n".join(lineas)


def _texto_pronostico(pron: dict) -> list[str]:
    if not pron.get("disponible"):
        return [f"## 2. {APARTADOS[1]}", pron.get("nota", "No disponible."), ""]
    g = pron["goles"]
    uno = g["1x2"]
    lineas = [
        f"## 2. {APARTADOS[1]}",
        "Método: dos Poisson independientes, una por equipo, con las fuerzas de "
        "ataque y defensa encogidas hacia la media de la liga. El marcador exacto "
        "es el producto de las dos.",
        f"Goles esperados: {g['esperados']['local']} - {g['esperados']['visitante']} "
        f"(medido en {g['medido_en']})",
        f"1X2: {uno['local']:.0%} local / {uno['empate']:.0%} empate / "
        f"{uno['visitante']:.0%} visitante",
        "Marcadores más probables: " + " · ".join(
            f"{m['marcador']} {m['probabilidad']:.1%}" for m in g["marcadores"][:5]),
        "Más de N goles: " + " · ".join(
            f"{k} {v:.0%}" for k, v in g["mas_de"].items()),
        f"Marcan los dos: {g['ambos_marcan']:.0%}",
    ]
    fuerzas = g.get("fuerzas") or {}
    for lado in ("local", "visitante"):
        f = fuerzas.get(lado) or {}
        if f:
            lineas.append(
                f"Fuerza {lado} ({f['equipo']}): ataque {f['ataque']} "
                f"(sin encoger {f['ataque_sin_encoger']}), defensa {f['defensa']} "
                f"(sin encoger {f['defensa_sin_encoger']}), sobre {f['partidos']} partidos")

    corners = pron.get("corners") or {}
    if corners.get("disponible"):
        lineas.append(f"Córners esperados: {corners['esperado_total']} "
                      f"({corners['esperado_local']} - {corners['esperado_visitante']}) · "
                      + " · ".join(f"+{k} {v:.0%}" for k, v in corners["mas_de"].items()))
    tarjetas = pron.get("tarjetas") or {}
    if tarjetas.get("disponible"):
        total = tarjetas.get("esperado_total_con_arbitro", tarjetas["esperado_total"])
        lineas.append(f"Amarillas esperadas: {total} · "
                      + " · ".join(f"+{k} {v:.0%}" for k, v in tarjetas["mas_de"].items()))
        arbitro = tarjetas.get("arbitro") or {}
        if arbitro.get("lectura"):
            lineas.append(f"  {arbitro['lectura']} ({arbitro['partidos_mirados']} partidos)")

    lineas += ["", f"Cómo se calcula: {pron.get('como_se_calcula', '')}",
               f"Lo que no dice: {pron.get('lo_que_no_dice', '')}", ""]
    return lineas


def _texto_mercado(pron: dict) -> list[str]:
    """El mercado, en su propio apartado.

    Iba dentro del pronóstico, en una línea que empezaba por «MERCADO:». Es lo
    que hay que contrastar con todo lo demás, así que va aparte y con su nombre:
    un apartado se cita, una línea perdida en otro no.
    """
    mercado = pron.get("mercado") or {}
    lineas = [f"## 3. {APARTADOS[2]}"]
    if not mercado.get("disponible"):
        lineas += [mercado.get("nota", "No hay cuotas guardadas de este partido."),
                   "Sin cuotas no hay con qué contrastar el cálculo: dilo si es "
                   "relevante para tu lectura.", ""]
        return lineas
    suyas = mercado["mercado"]
    lineas += [
        "Probabilidades implícitas en las cuotas, ya sin el margen de la casa:",
        f"  Local {suyas.get('local', 0):.0%} · Empate {suyas.get('empate', 0):.0%} "
        f"· Visitante {suyas.get('visitante', 0):.0%}",
        f"Lectura: {mercado['lectura']}",
        "El mercado sabe cosas que no están en este documento —alineaciones, "
        "bajas, dinero—. Donde coincide con el cálculo, no hay nada que ganar; "
        "donde no, lo más probable sigue siendo que se equivoque el cálculo.",
        "",
    ]
    return lineas


def _texto_equipos(prev: dict) -> list[str]:
    equipos = prev.get("equipos") or {}
    if not equipos:
        return []
    lineas = [f"## 4. {APARTADOS[3]}",
              "Cada rasgo es una diferencia contra la media de su propia "
              "competición, con la muestra de las dos partes al lado."]
    for lado in ("local", "visitante"):
        e = equipos.get(lado) or {}
        if not e.get("disponible"):
            lineas.append(f"{lado}: {e.get('nota', 'sin datos guardados')}")
            continue
        r = e.get("resultados") or {}
        lineas.append(f"### {e['equipo']} ({lado})")
        lineas.append(f"Medido sobre n={e['partidos_mirados']} partidos suyos "
                      f"(media de su liga: n={e.get('partidos_en_la_media_de_liga', 0)})"
                      f" · racha {r.get('racha', '?')} · goles "
                      f"{r.get('goles_favor')}-{r.get('goles_contra')} · "
                      f"competición: {e.get('liga')}")
        rasgos = e.get("lo_que_le_distingue") or []
        if rasgos:
            for rasgo in rasgos:
                lineas.append(f"  · {rasgo['rasgo']} ({rasgo['cuanto']})")
        elif e.get("aviso"):
            # Y esto es lo que hay que decir, no «no se sale en nada»: son dos
            # cosas distintas y confundirlas es afirmar sin muestra.
            lineas.append(f"  · SIN MUESTRA PARA RETRATARLO: {e['aviso']}")
        else:
            lineas.append("  · no se sale de la media de su liga en nada llamativo")
        concede = e.get("concede") or {}
        lineas.append(f"  concede por partido: {concede.get('xg')} xG, "
                      f"{concede.get('tiros')} tiros, "
                      f"{concede.get('ocasiones_claras')} ocasiones claras "
                      f"(n={e['partidos_mirados']})")
        if e.get("aviso") and rasgos:
            # Sin rasgos el aviso ya se ha dicho arriba, en su sitio.
            lineas.append(f"  aviso: {e['aviso']}")

    cruces = prev.get("donde_se_hacen_dano") or []
    if cruces:
        lineas += ["", "### Dónde se pueden hacer daño (los dos lados medidos)"]
        for cruce in cruces:
            lineas.append(f"  · {cruce['aviso']} ({cruce['cuanto']:+.0%} sobre su liga, "
                          f"el rival concede {cruce['concede_el_rival']:+.0%})")

    jugadores = prev.get("jugadores") or {}
    hay = any(jugadores.get(lado) for lado in ("local", "visitante"))
    if hay:
        lineas += ["", "### Jugadores a seguir"]
        for lado in ("local", "visitante"):
            for j in (jugadores.get(lado) or [])[:JUGADORES]:
                # `rachas` ya viene como lista de cadenas de `_a_seguir`.
                rachas = ", ".join(str(x) for x in (j.get("rachas") or []))
                por = j.get("por_partido") or {}
                numeros = " · ".join(
                    f"{clave.replace('_', ' ')} {por[clave]}"
                    for clave in ("goles", "asistencias", "tiros", "tiros_a_puerta", "xg")
                    if por.get(clave) is not None)
                lineas.append(
                    f"  · {j.get('jugador')} ({lado}): n={j.get('partidos')}, "
                    f"nota media {j.get('rating_medio')}"
                    + (f" · {numeros}" if numeros else "")
                    + (f" — {rachas}" if rachas else ""))
    lineas.append("")
    return lineas


def _texto_ultimos(ultimos: dict, entre: dict) -> list[str]:
    lineas = [f"## 5. {APARTADOS[4]}",
              "Del más reciente al más antiguo. Todo anterior a la fecha del partido."]
    for lado in ("local", "visitante"):
        bloque = ultimos.get(lado) or {}
        if not bloque.get("partidos"):
            continue
        lineas.append(f"### {bloque['equipo']} ({lado})")
        for x in bloque["partidos"]:
            lineas.append(f"  {x['fecha']}  {x['resultado']}  {x['partido']} "
                          f"({x['donde']}, {x['competicion']})")
    anteriores = entre.get("partidos") or []
    if anteriores:
        lineas.append("### Entre ellos")
        for x in anteriores:
            lineas.append(f"  {x['fecha']}  {x['partido']} ({x['competicion']})")
    else:
        lineas.append("### Entre ellos: no hay ninguno guardado.")
    lineas.append("")
    return lineas


def _texto_arbitro(prev: dict) -> list[str]:
    a = prev.get("arbitro") or {}
    if not a.get("disponible"):
        return [f"## 6. {APARTADOS[5]}", a.get("nota", "sin datos"), ""]
    por = a.get("por_partido") or {}
    reparto = a.get("reparto_de_tarjetas") or {}
    return [
        f"## 6. {APARTADOS[5]}",
        f"{a['arbitro']} · n={a['partidos_mirados']} partidos suyos vistos",
        f"Por partido: {por.get('amarillas')} amarillas, {por.get('rojas')} rojas, "
        f"{por.get('penaltis')} penaltis, {por.get('faltas')} faltas",
        f"Reparto: {reparto.get('al_local')} al local / "
        f"{reparto.get('al_visitante')} al visitante · "
        f"gana el local {a.get('victorias_locales')}",
        f"{a.get('aviso') or ''}",
        "",
    ]


def _texto_seguro(seguro: dict) -> list[str]:
    avisos = seguro.get("avisos") or []
    if not avisos:
        return [f"## 7. {APARTADOS[6]}",
                "Ningún patrón medido se cumple en este partido con muestra "
                "suficiente.", ""]
    lineas = [f"## 7. {APARTADOS[6]} "
              f"(calibrado con {seguro.get('calibrado_con')} partidos de la memoria)",
              "Cada patrón se mide una sola vez sobre todo el historial: la "
              "frecuencia y el suelo son del patrón, no de este partido. Lo propio "
              "de este partido es que la condición se cumple."]
    for a in avisos:
        fuera = (a.get("fuera_de_muestra") or {}).get("veredicto") or "sin comprobar"
        lineas.append(
            f"  · {a['sujeto']}: {a['dice']} — {a['frecuencia']:.0%} en {a['casos']} "
            f"casos, suelo {a['suelo']:.0%}, {a['elevacion']:+.0%} sobre su "
            f"referencia [{a['veredicto']}; fuera de muestra: {fuera}]")
    lineas += [f"  {seguro.get('lo_que_no_dice', '')}", ""]
    return lineas


__all__ = ["APARTADOS", "CLAVE_DE_LECTURA", "ENTRE_ELLOS", "JUGADORES",
           "ULTIMOS", "a_texto", "expediente"]
