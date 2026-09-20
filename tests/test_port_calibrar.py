"""Tests de equivalencia del port de calibrar_app contra app.py y contra el oráculo (V4, V5)."""

import json
import os
import sys
import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import app
import arribo
import datos
import impulso
import referencia

CARPETA_TEST = "mediciones_filtros/cada_30s/7"
ORACULO_PATH = r"C:\Users\runi2\.gemini\antigravity-cli\brain\a701fd7d-a7fd-49cb-907e-43afbdf2bc24\scratch\oraculo_calibracion.json"


@pytest.fixture
def oraculo_data():
    if not os.path.isfile(ORACULO_PATH):
        pytest.skip(f"Oráculo no encontrado en {ORACULO_PATH}")
    with open(ORACULO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_v4_t_arribo_vs_app():
    # Señal sintética con rampa y cruce
    t = np.linspace(0, 10, 1000)
    v = np.sin(t) * 100.0
    ta_port = arribo.t_arribo(t, v, 50.0, 10, 0.0)
    assert ta_port is not None
    if hasattr(app, "_t_arribo"):
        ta_app = app._t_arribo(t, v, 50.0, 10, 0.0)
        assert abs(ta_app - ta_port) == 0.0


def test_v4_t10_por_segmento_vs_app():
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")
    t10_app = app.t10_por_segmento(CARPETA_TEST)
    t10_port = impulso.t10_por_segmento(CARPETA_TEST)
    assert np.allclose(t10_app, t10_port, rtol=0, atol=1e-12)


def test_v4_calibrar_retardo_vs_app_y_oraculo(oraculo_data):
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

    for ch in ["ch2", "ch3", "ch4"]:
        ref_oraculo = oraculo_data["canales"][ch]
        u = ref_oraculo["umbral_mv"]
        d = ref_oraculo["distancia_us"]
        tm = ref_oraculo["tmin_us"]

        res_port = arribo.calibrar_retardo(CARPETA_TEST, ch, u, d, tm, referencia="t10")

        # Comparación contra app (si estuviera presente)
        if hasattr(app, "calibrar_retardo"):
            res_app = app.calibrar_retardo(CARPETA_TEST, ch, u, d, tm)
            assert res_app["n_valid"] == res_port["n_valid"]
            assert res_app["n_total"] == res_port["n_total"]
            assert res_app["valido"] == res_port["valido"]
            assert res_app["atipico"] == res_port["atipico"]
            if res_app["t_lag_us"] is not None:
                assert abs(res_app["t_lag_us"] - res_port["t_lag_us"]) < 1e-12
                assert abs(res_app["sigma_us"] - res_port["sigma_us"]) < 1e-12

        # Comparación contra oráculo guardado previamente (oráculo definitivo P0)
        assert res_port["n_valid"] == ref_oraculo["n_valid"]
        assert res_port["n_total"] == ref_oraculo["n_total"]
        if ref_oraculo["t_lag_us"] is not None:
            delta_ns = abs(ref_oraculo["t_lag_us"] - res_port["t_lag_us"]) * 1e3
            assert delta_ns == 0.0, f"Discrepancia en {ch}: delta = {delta_ns} ns"


def test_v4_umbral_absurdo():
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")
    res = arribo.calibrar_retardo(CARPETA_TEST, "ch4", 1e9, 0.035, 0.15)
    assert res["n_valid"] == 0
    assert res["t_lag_us"] is None
    assert res["sigma_us"] is None


def test_v5_consistencia_anclas_delta_t10_O1():
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")
    delta_info = referencia.delta_t10_menos_O1(CARPETA_TEST)
    media_us = delta_info["media_us"]
    # Cota física de la norma IEC 60060-1 para T1 ∈ [0.84, 1.56] µs: delta ∈ [0.18, 0.34] µs
    assert 0.18 <= media_us <= 0.34
    assert delta_info["n"] > 0
