"""Configuración global de pytest para el proyecto TRPD_APP."""

import os
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
MEDICIONES = os.path.abspath(os.path.join(RAIZ, os.pardir, "mediciones", "Mediciones"))


@pytest.fixture(scope="session")
def check_mediciones_disponible():
    if not os.path.isdir(MEDICIONES):
        pytest.skip(f"Directorio de mediciones {MEDICIONES} no disponible")
