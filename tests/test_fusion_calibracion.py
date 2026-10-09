"""Guardar la calibración de solo algunos canales no debe borrar la de los demás:
calibrar_app conserva los canales no recalculados si usan la misma referencia."""

from __future__ import annotations
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import main
import persistencia
from persistencia import fusionar_con_bloque_previo


def _previo(ref="t10"):
    return {
        "fecha": "2026-09-01", "fuente_calibracion": "antes", "criterio": "primer_cruce_umbral",
        "referencia_impulso": ref,
        "ch2": {"sensor": "HFCT", "t_lag_ns": 12.4, "sigma_ns": 0.8, "n_valid": 40, "n_total": 50},
        "ch3": {"sensor": "Antena 1", "t_lag_ns": 8.1, "sigma_ns": 0.4, "n_valid": 49, "n_total": 50},
        "ch4": {"sensor": "Antena 2", "t_lag_ns": 15.6, "sigma_ns": 1.1, "n_valid": 50, "n_total": 50},
    }


def _nuevo(ref="t10"):
    return {"fecha": "2026-10-09", "fuente_calibracion": "ahora", "referencia_impulso": ref,
            "ch4": {"sensor": "Antena 2", "t_lag_ns": 20.0, "sigma_ns": 0.5, "n_valid": 50, "n_total": 50}}


def test_conserva_canales_no_recalculados():
    bloque, cons, desc = fusionar_con_bloque_previo(_nuevo(), _previo())
    assert cons == ["ch2", "ch3"] and desc == []
    assert bloque["ch4"]["t_lag_ns"] == 20.0                     # el recalculado manda
    assert bloque["ch2"]["t_lag_ns"] == 12.4 and bloque["ch3"]["t_lag_ns"] == 8.1
    assert bloque["ch2"]["fecha"] == "2026-09-01"                # fecha de su calibración
    assert bloque["fecha"] == "2026-10-09"


def test_descarta_si_cambia_la_referencia():
    bloque, cons, desc = fusionar_con_bloque_previo(_nuevo("origen_virtual_IEC60060"), _previo("t10"))
    assert cons == [] and desc == ["ch2", "ch3"]
    assert "ch2" not in bloque and "ch3" not in bloque


def test_referencia_legada_y_sin_previo():
    previo = _previo()
    del previo["referencia_impulso"]
    previo["referencia"] = "t10_CH1_por_segmento"
    _, cons, _ = fusionar_con_bloque_previo(_nuevo(), previo)
    assert cons == ["ch2", "ch3"]
    bloque, cons, desc = fusionar_con_bloque_previo(_nuevo(), None)
    assert cons == desc == [] and set(bloque) == set(_nuevo())


def test_canal_previo_sin_t_lag_no_se_conserva():
    previo = _previo()
    previo["ch3"]["t_lag_ns"] = None
    _, cons, _ = fusionar_con_bloque_previo(_nuevo(), previo)
    assert cons == ["ch2"]


def test_guardar_en_metadata_conserva_canales(monkeypatch):
    """Callback completo: recalcular solo CH4 y guardar mantiene CH2 y CH3."""
    escrito = {}
    monkeypatch.setattr(main, "obtener_metadata", lambda c: {"calibracion_retardo": _previo()})
    monkeypatch.setattr(main, "spec_filtro", lambda c, ch: None)
    monkeypatch.setattr(main, "guardar_calibracion_metadata",
                        lambda c, b: (escrito.update(b), (True, "ok"))[1])
    store = {"_carpeta": "X", "ch4": {"t_lag_us": 0.020, "sigma_us": 0.0005, "n_valid": 50, "n_total": 50,
                                      "params": {"umbral_mv": 5.0, "distancia_us": 0.05, "tmin_us": 0.15}}}
    out = main.guardar_en_metadata(1, "X", store, "calibrar_app", "t10", None)
    assert escrito["ch4"]["t_lag_ns"] == 20.0
    assert escrito["ch2"]["t_lag_ns"] == 12.4 and escrito["ch3"]["t_lag_ns"] == 8.1
    assert "CH2, CH3" in str(out)
    assert persistencia.CANALES_SENSOR == ("ch2", "ch3", "ch4")
