"""Fuentes de datos, más allá de Sofascore.

    from cancha.sources import ClubElo, Understat, FutbolData, ESPN, contexto_partido

Cada fuente es independiente y comparte con las demás el transporte, la caché,
el limitador de peticiones y los errores tipados (:mod:`cancha.sources.base`).
:func:`contexto_partido` es la que las junta: coge un partido de Sofascore y le
añade lo que dicen las otras, emparejándolo por su cuenta.

Y cuando hay algo que no merece la pena scrapear dos veces —FBref,
Transfermarkt, Capology— se usan las librerías que ya lo hacen, a través de
:mod:`.externas`, si están instaladas.
"""

from .base import FUENTES, Fuente, FuenteError, construir, registrar
from .clubelo import ClubElo
from .cruce import UNDERSTAT_POR_TORNEO, contexto_partido, temporada_de
from .espn import ESPN
from .externas import AdaptadorNoDisponible, adaptador, disponibles
from .futboldata import FutbolData, rellenar_cuotas
from .understat import Understat

__all__ = [
    "Fuente",
    "FuenteError",
    "FUENTES",
    "registrar",
    "construir",
    "ClubElo",
    "Understat",
    "FutbolData",
    "ESPN",
    "rellenar_cuotas",
    "disponibles",
    "adaptador",
    "AdaptadorNoDisponible",
    "contexto_partido",
    "temporada_de",
    "UNDERSTAT_POR_TORNEO",
]
