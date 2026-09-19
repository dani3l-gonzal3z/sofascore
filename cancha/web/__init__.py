"""La interfaz: un servidor local y una página que se instala como app.

    cancha web            # en este ordenador
    cancha web --lan      # y desde el móvil, en la misma wifi

No hay framework web ni dependencias: es ``http.server`` de la biblioteca
estándar sirviendo una página y una API JSON encima de las mismas
herramientas que ve la IA. Lo que la IA puede preguntar, la página lo puede
enseñar; y al revés.

En Windows se abre en el navegador y Edge o Chrome la instalan como
aplicación. En iOS, Safari → Compartir → «Añadir a pantalla de inicio»: es
una PWA, con su manifiesto y su icono, y se abre a pantalla completa.
"""

from .servidor import Servidor, arrancar

__all__ = ["Servidor", "arrancar"]
