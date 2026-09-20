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

CARPETA_TEST = "mediciones_filtros/cada_30s/7"


def test_1_sintetico_t_arribo():
    """Test 1: Verificación sintética de interpolación sub-muestra en arribo.t_arribo."""
    dt = 2e-4
    t = np.arange(0, 1.0, dt)

    # 1.1 Rampa lineal que cruza umbral=1 en t*=0.30013, seguida de pulso
    t_star = 0.30013
    umbral = 1.0
    v = np.zeros_like(t)
    idx_rampa = (t >= 0.2) & (t <= 0.4)
    m = 2.0 / 0.2
    v[idx_rampa] = 1.0 + m * (t[idx_rampa] - t_star)
    v[t > 0.4] = 2.0
    v[(t >= 0.48) & (t <= 0.52)] = 5.0

    ta = arribo.t_arribo(t, v, umbral=umbral, distancia=10, tmin=0.0)
    assert ta is not None, "ta no debería ser None"
    assert abs(ta - t_star) < 1e-7, f"Error en interpolación: {abs(ta - t_star)}"

    # 1.2 Sin cruce -> None
    v_bajo = np.ones_like(t) * 0.5
    ta_bajo = arribo.t_arribo(t, v_bajo, umbral=1.0, distancia=10, tmin=0.0)
    assert ta_bajo is None, f"Esperado None sin cruce, obtenido {ta_bajo}"

    # 1.3 Precursor EMI absorbido por pico mayor
    v_prec = np.zeros_like(t)
    v_prec[int(0.298 / dt)] = 1.05
    i_pico_mayor = int(0.302 / dt)
    v_prec[i_pico_mayor - 5:i_pico_mayor + 5] = np.linspace(0.5, 5.0, 10)
    v_prec[i_pico_mayor:i_pico_mayor + 10] = np.linspace(5.0, 0.2, 10)
    distancia_muestras = int(0.02 / dt)
    ta_prec = arribo.t_arribo(t, v_prec, umbral=1.0, distancia=distancia_muestras, tmin=0.0)
    assert ta_prec is not None

    # 1.4 Señal negativa (-v) -> usa |v|
    ta_neg = arribo.t_arribo(t, -v, umbral=umbral, distancia=10, tmin=0.0)
    assert ta_neg is not None and abs(ta_neg - ta) < 1e-7


def test_2_t10_por_segmento_app():
    """Test 2: t10 por segmento en app.py."""
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

    t10_arr = app.t10_por_segmento(CARPETA_TEST)
    n_fb = app.n_fallback_t10(CARPETA_TEST)
    assert len(t10_arr) == 50
    assert np.all(np.isfinite(t10_arr))

    mean_ns = np.mean(t10_arr) * 1e3
    std_ns = np.std(t10_arr, ddof=1) * 1e3
    T_prom = app.tiempos_impulso(CARPETA_TEST)
    t10_prom_ns = (T_prom["t10"] or 0.0) * 1e3
    diff_ns = abs(mean_ns - t10_prom_ns)
    assert diff_ns < (3 * std_ns + 1e-1)


def test_3_humo_calibracion_calibrar_app():
    """Test 3: Humo de calibrar_retardo en CH4 vía calibrar_app."""
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

    t, v = datos.cargar_segmento(CARPETA_TEST, "ch4", 1)
    u = float(np.max(np.abs(v)) * 0.60)
    res = arribo.calibrar_retardo(CARPETA_TEST, "ch4", u, 0.5, 0.0)
    assert len(res["t_lag"]) == res["n_total"] == 50
    assert res["n_valid"] > 0
    assert res["t_lag_us"] is not None

    res_absurdo = arribo.calibrar_retardo(CARPETA_TEST, "ch4", 1e9, 0.5, 0.0)
    assert res_absurdo["n_valid"] == 0
    assert res_absurdo["t_lag_us"] is None


def test_4_trpd_antes_despues_app():
    """Test 4: TRPD antes vs después de calibración en app.py (t_abs_captura)."""
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

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
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

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
            "ch3": {"sensor": "Antena Vivaldi", "t_lag_ns": 8.120, "sigma_ns": 0.420, "n_valid": 49, "n_total": 50},
            "ch4": {"sensor": "Antena Bioinspirada", "t_lag_ns": 15.650, "sigma_ns": 1.100, "n_valid": 50, "n_total": 50},
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

        meds_cal = persistencia.mediciones_con_calibracion()
        assert CARPETA_TEST in meds_cal

        meta_nueva = datos.obtener_metadata(CARPETA_TEST)
        assert "osciloscopio" in meta_nueva and "canales" in meta_nueva and "probeta" in meta_nueva
    finally:
        if os.path.exists(bak_path):
            shutil.copy2(bak_path, meta_path)
            os.remove(bak_path)
