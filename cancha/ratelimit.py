"""Limitador de peticiones: separa las llamadas para no martillear la API."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Espaciador simple: garantiza como mucho ``rate`` peticiones por segundo."""

    def __init__(self, rate: float = 3.0, sleep=time.sleep, clock=time.monotonic) -> None:
        self.min_intervalo = 0.0 if rate <= 0 else 1.0 / rate
        self._sleep = sleep
        self._clock = clock
        self._ultima = 0.0
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Bloquea lo necesario. Devuelve los segundos que ha esperado."""
        if self.min_intervalo <= 0:
            return 0.0
        with self._lock:
            ahora = self._clock()
            transcurrido = ahora - self._ultima
            espera = self.min_intervalo - transcurrido
            if espera > 0:
                self._sleep(espera)
                self._ultima = self._clock()
                return espera
            self._ultima = ahora
            return 0.0
