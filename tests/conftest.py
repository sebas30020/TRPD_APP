"""Configuración global de pytest para el proyecto TRPD_APP.

No existe una carpeta de datos fija: los tests que necesitan una medición real
la leen de la variable de entorno TRPD_CARPETA_TEST (ruta absoluta a una carpeta
con ch1..ch4.h5) y se omiten si no está definida. Ejemplo (PowerShell):

    $env:TRPD_CARPETA_TEST = "G:\\...\\mediciones\\3v_2mm3mm3.5mm_0\\10kV"
    .venv\\Scripts\\python.exe -m pytest -q
"""

import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
