"""Migración y formalización de scripts_tmp/verificar_trpd_cal.py (V7).

Verifica regresión:
- Tests 1, 3 y 5 reapuntados a calibrar_app (arribo y persistencia).
- Tests 2 y 4 conservados sobre app.py (t10_por_segmento, capturar, t_abs_captura).
"""

from __future__ import annotations
import os
import shutil
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
import persistencia

# Medición de prueba: ruta absoluta a una carpeta con ch1..ch4.h5 (no hay carpeta de datos fija).
CARPETA_TEST = os.environ.get("TRPD_CARPETA_TEST", "")


def test_1_sintetico_t_arribo():
    """Test 1: arribo = máximo de |v| de la primera oscilación que cruza el umbral."""
    dt = 2e-4
    t = np.arange(0, 1.0, dt)

    # 1.1 Pulso gaussiano: el arribo es su máximo (refinado sub-muestra), no el cruce
    t_pico = 0.30013
    v = 3.0 * np.exp(-0.5 * ((t - t_pico) / 0.005) ** 2)
    ta = arribo.t_arribo(t, v, umbral=1.0, distancia=10, tmin=0.0)
    assert ta is not None and abs(ta - t_pico) < 2e-6, ta

    # 1.2 Sin cruce -> None
    assert arribo.t_arribo(t, np.full_like(t, 0.5), umbral=1.0, distancia=10, tmin=0.0) is None

    # 1.3 Señal negativa (-v) -> usa |v|
    ta_neg = arribo.t_arribo(t, -v, umbral=1.0, distancia=10, tmin=0.0)
    assert ta_neg is not None and abs(ta_neg - ta) < 1e-9

    # 1.4 Lóbulo positivo pequeño que cruza primero, seguido de un lóbulo negativo
    #     mayor: el arribo es el máximo del lóbulo positivo (t = 0.31), no el del negativo.
    v_osc = np.zeros_like(t)
    lob_pos = (t > 0.30) & (t < 0.32)
    v_osc[lob_pos] = 2.0 * np.sin(np.pi * (t[lob_pos] - 0.30) / 0.02)
    lob_neg = (t > 0.32) & (t < 0.36)
    v_osc[lob_neg] = -6.0 * np.sin(np.pi * (t[lob_neg] - 0.32) / 0.04)
    ta_osc = arribo.t_arribo(t, v_osc, umbral=1.0, distancia=int(0.05 / dt), tmin=0.0)
    assert ta_osc is not None and abs(ta_osc - 0.31) < 2e-5, ta_osc

    # 1.5 t_máx acota dónde puede empezar el cruce; el lóbulo puede terminar después
    assert arribo.t_arribo(t, v_osc, umbral=1.0, distancia=None, tmin=0.0, tmax=0.29) is None
    ta_tmax = arribo.t_arribo(t, v_osc, umbral=1.0, distancia=None, tmin=0.0, tmax=0.305)
    assert ta_tmax is not None and abs(ta_tmax - 0.31) < 2e-5, ta_tmax

    # 1.6 t_mín: el lóbulo que cruza antes de t_mín no cuenta
    ta_tmin = arribo.t_arribo(t, v_osc, umbral=1.0, distancia=None, tmin=0.32)
    assert ta_tmin is not None and abs(ta_tmin - 0.34) < 2e-5, ta_tmin


def test_2_t10_por_segmento_app():
    """Test 2: t10 por segmento en app.py."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    t10_arr = app.t10_por_segmento(CARPETA_TEST)
    n_fb = app.n_fallback_t10(CARPETA_TEST)
    assert len(t10_arr) == app.n_segmentos(CARPETA_TEST)   # uno por segmento, sea cual sea N
    assert np.all(np.isfinite(t10_arr))

    mean_ns = np.mean(t10_arr) * 1e3
    std_ns = np.std(t10_arr, ddof=1) * 1e3
    T_prom = app.tiempos_impulso(CARPETA_TEST)
    t10_prom_ns = (T_prom["t10"] or 0.0) * 1e3
    diff_ns = abs(mean_ns - t10_prom_ns)
    assert diff_ns < (3 * std_ns + 1e-1)


def test_3_humo_calibracion_calibrar_app():
    """Test 3: Humo de calibrar_retardo en CH4 vía calibrar_app."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    t, v = datos.cargar_segmento(CARPETA_TEST, "ch4", 1)
    u = float(np.max(np.abs(v)) * 0.60)
    res = arribo.calibrar_retardo(CARPETA_TEST, "ch4", u, 0.5, 0.0)
    assert len(res["t_lag"]) == res["n_total"] == datos.n_segmentos(CARPETA_TEST)
    assert res["n_valid"] > 0
    assert res["t_lag_us"] is not None

    res_absurdo = arribo.calibrar_retardo(CARPETA_TEST, "ch4", 1e9, 0.5, 0.0)
    assert res_absurdo["n_valid"] == 0
    assert res_absurdo["t_lag_us"] is None


def test_4_trpd_antes_despues_app():
    """Test 4: TRPD antes vs después de calibración en app.py (t_abs_captura)."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    cfg_sensores = app.config_sensores_defecto(CARPETA_TEST)
    t_lag_test = 0.0124  # 12.4 ns

    for ch in ["ch2", "ch3", "ch4"]:
        if ch not in app.canales_presentes(CARPETA_TEST):
            continue
        cfg = cfg_sensores[ch]
        u = cfg["umbral"] or app.umbral_defecto(CARPETA_TEST, ch)
        cap = app.capturar(CARPETA_TEST, ch, u, cfg["dist"], cfg["tmin"])

        tpk = cap["t_peak"]
        if tpk.size == 0:
            continue

        tabs_0 = app.t_abs_captura(cap, 0.0)
        tabs_lag = app.t_abs_captura(cap, t_lag_test)

        assert tabs_0.size == tpk.size
        assert np.allclose(tabs_0, tpk - cap["t10_seg"])
        assert np.allclose(tabs_0 - tabs_lag, t_lag_test)


def test_5_persistencia_calibrar_app():
    """Test 5: Persistencia en metadata.yaml vía persistencia y lectura en app."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    dir_med = datos._dir_medicion(CARPETA_TEST)
    meta_path = os.path.join(dir_med, "metadata.yaml")
    bak_path = os.path.join(dir_med, "metadata.yaml.bak_regresion")

    shutil.copy2(meta_path, bak_path)
    try:
        bloque_prueba = {
            "fecha": "2026-09-16",
            "fuente_calibracion": "test_script_esferas",
            "criterio": "primer_cruce_umbral",
            "referencia": "t10_CH1_por_segmento",
            "referencia_impulso": "t10",
            "ch2": {"sensor": "HFCT", "t_lag_ns": 12.400, "sigma_ns": 0.850, "n_valid": 50, "n_total": 50},
            "ch3": {"sensor": "Antena 1", "t_lag_ns": 8.120, "sigma_ns": 0.420, "n_valid": 49, "n_total": 50},
            "ch4": {"sensor": "Antena 2", "t_lag_ns": 15.650, "sigma_ns": 1.100, "n_valid": 50, "n_total": 50},
        }
        ok, msg = persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_prueba)
        assert ok, f"Error al guardar: {msg}"

        cal = app.calibracion_desde_metadata(CARPETA_TEST)
        assert cal["calibrado"] is True
        assert cal["fuente"] == "test_script_esferas"
        assert abs(cal["canales"]["ch2"]["t_lag_us"] - 0.0124) < 1e-6
        assert abs(cal["canales"]["ch3"]["t_lag_us"] - 0.00812) < 1e-6
        assert abs(cal["canales"]["ch4"]["t_lag_us"] - 0.01565) < 1e-6

        assert abs(app.lag_canal(cal, CARPETA_TEST, "ch2") - 0.0124) < 1e-6
        assert app.lag_canal(cal, "otra_carpeta", "ch2") == 0.0

        meds_cal = persistencia.mediciones_con_calibracion([CARPETA_TEST])
        assert CARPETA_TEST in meds_cal

        meta_nueva = datos.obtener_metadata(CARPETA_TEST)
        assert "osciloscopio" in meta_nueva and "canales" in meta_nueva and "probeta" in meta_nueva
    finally:
        if os.path.exists(bak_path):
            shutil.copy2(bak_path, meta_path)
            os.remove(bak_path)
