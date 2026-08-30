"""Fuentes de datos, más allá de Sofascore.

    from cancha.sources import ClubElo, Understat, contexto_partido

Cada fuente es independiente y comparte con las demás el transporte, la caché,
el limitador de peticiones y los errores tipados (:mod:`cancha.sources.base`).
:func:`contexto_partido` es la que las junta: coge un partido de Sofascore y le
añade lo que dicen las otras, emparejándolo por su cuenta.
"""

from .base import FUENTES, Fuente, FuenteError, construir, registrar
from .clubelo import ClubElo
from .cruce import UNDERSTAT_POR_TORNEO, contexto_partido, temporada_de
from .understat import Understat

__all__ = [
    "Fuente",
    "FuenteError",
    "FUENTES",
    "registrar",
    "construir",
    "ClubElo",
    "Understat",
    "contexto_partido",
    "temporada_de",
    "UNDERSTAT_POR_TORNEO",
]
