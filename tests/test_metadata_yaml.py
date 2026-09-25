"""Tests de persistencia, formato YAML y compatibilidad de referencias (V5, V6).

Verifica round-trip en metadata.yaml de la medición TRPD_CARPETA_TEST con backup/restore
garantizado, preservación de secciones originales, compatibilidad de bloques legados,
manejo de referencia O1 con y sin ancla, y equivalencia end-to-end t10 vs O1.
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
import datos
import persistencia
import arribo
import referencia

# Medición de prueba: ruta absoluta a una carpeta con ch1..ch4.h5 (no hay carpeta de datos fija).
CARPETA_TEST = os.environ.get("TRPD_CARPETA_TEST", "")


@pytest.fixture
def backup_metadata():
    """Garantiza la preservación del archivo metadata.yaml original de la medición de prueba."""
    dir_med = datos._dir_medicion(CARPETA_TEST)
    if not dir_med:
        pytest.skip(f"No se encontró directorio para {CARPETA_TEST}")

    meta_path = os.path.join(dir_med, "metadata.yaml")
    bak_path = os.path.join(dir_med, "metadata.yaml.bak_test")

    if not os.path.isfile(meta_path):
        pytest.skip(f"No existe metadata.yaml en {dir_med}")

    shutil.copy2(meta_path, bak_path)
    try:
        yield meta_path
    finally:
        if os.path.isfile(bak_path):
            shutil.copy2(bak_path, meta_path)
            os.remove(bak_path)


def test_v6_roundtrip_legado(backup_metadata):
    """Bloque legado (sin referencia_impulso, solo referencia t10): retrocompatibilidad demostrada."""
    bloque_legado = {
        "fecha": "2026-09-18",
        "fuente_calibracion": "test_legado",
        "criterio": "primer_cruce_umbral",
        "referencia": "t10_CH1_por_segmento",
        "ch2": {"sensor": "HFCT", "t_lag_ns": 15.250, "sigma_ns": 0.500, "n_valid": 50, "n_total": 50},
        "ch3": {"sensor": "Antena Vivaldi", "t_lag_ns": 9.100, "sigma_ns": 0.350, "n_valid": 48, "n_total": 50},
        "ch4": {"sensor": "Antena Bioinspirada", "t_lag_ns": 20.400, "sigma_ns": 0.800, "n_valid": 50, "n_total": 50},
    }
    ok, msg = persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_legado)
    assert ok, f"Error al guardar: {msg}"

    cal = app.calibracion_desde_metadata(CARPETA_TEST)
    assert cal["calibrado"] is True
    assert cal["referencia_impulso"] == "t10"
    assert cal["fuente"] == "test_legado"
    assert abs(cal["canales"]["ch2"]["t_lag_us"] - 0.01525) < 1e-6
    assert abs(cal["canales"]["ch3"]["t_lag_us"] - 0.0091) < 1e-6
    assert abs(cal["canales"]["ch4"]["t_lag_us"] - 0.0204) < 1e-6

    # Secciones originales preservadas
    meta = datos.obtener_metadata(CARPETA_TEST)
    assert "experimento" in meta and "circuito_impulso" in meta and "canales" in meta


def test_v6_roundtrip_o1_sin_ancla(backup_metadata):
    """Bloque O1 sin bloque 'ancla': se marca calibrado=False y t_lag_us=0.0 con aviso explicativo."""
    bloque_o1_huerfano = {
        "fecha": "2026-09-18",
        "fuente_calibracion": "test_o1_sin_ancla",
        "criterio": "primer_cruce_umbral",
        "referencia": "origen_virtual_IEC60060_por_segmento",
        "referencia_impulso": "origen_virtual_IEC60060",
        "ch4": {"sensor": "Antena Bioinspirada", "t_lag_ns": 275.500, "sigma_ns": 1.200, "n_valid": 50, "n_total": 50},
    }
    ok, msg = persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_o1_huerfano)
    assert ok, f"Error al guardar: {msg}"

    cal = app.calibracion_desde_metadata(CARPETA_TEST)
    assert cal["calibrado"] is False
    assert cal["aviso"] is not None and len(cal["aviso"]) > 0
    assert cal["canales"]["ch4"]["t_lag_us"] == 0.0
    assert cal["canales"]["ch4"]["calibrado"] is False


def test_v6_roundtrip_o1_con_ancla(backup_metadata):
    """Bloque O1 con bloque 'ancla': se resta delta_t10_menos_O1_ns normalizando a t10."""
    ancla = {
        "metodo": "IEC60060-1_AnexoB",
        "t10_menos_O1_ns": 258.40,
        "sigma_t10_menos_O1_ns": 3.10,
        "n_segmentos": 50,
        "T1_medio_us": 1.21,
        "T2_medio_us": 49.8,
        "beta_medio_pct": 0.8,
        "beta_max_pct": 2.1,
        "segmentos_fuera_tolerancia": 0,
    }
    # Supongamos que contra O1 el retardo medido es 275.40 ns (17.0 ns contra t10 + 258.40 ns)
    bloque_o1 = {
        "fecha": "2026-09-18",
        "fuente_calibracion": "test_o1_con_ancla",
        "criterio": "primer_cruce_umbral",
        "referencia_impulso": "origen_virtual_IEC60060",
        "ancla": ancla,
        "ch4": {"sensor": "Antena Bioinspirada", "t_lag_ns": 275.400, "sigma_ns": 1.100, "n_valid": 50, "n_total": 50},
    }
    bloque_full = persistencia.bloque_calibracion_retardo(
        resultados={"ch4": {"t_lag_us": 0.275400, "sigma_us": 0.0011, "n_valid": 50, "n_total": 50, "params": {}}},
        fuente="test_o1_con_ancla",
        referencia_impulso="origen_virtual_IEC60060",
        info_ancla=ancla,
    )
    ok, msg = persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_full)
    assert ok, f"Error al guardar: {msg}"

    cal = app.calibracion_desde_metadata(CARPETA_TEST)
    assert cal["calibrado"] is True
    assert cal["aviso"] is None
    # 275.40 ns - 258.40 ns = 17.0 ns = 0.017 µs
    assert abs(cal["canales"]["ch4"]["t_lag_us"] - 0.017) < 1e-6
    assert abs(cal["canales"]["ch4"]["sigma_us"] - 0.0011) < 1e-6


def test_v5_consistencia_t10_vs_o1_end_to_end(backup_metadata):
    """V5.2 y V5.3: t_lag(O1) - t_lag(t10) == delta(t10 - O1), y ambas dan el mismo retardo final."""
    delta_info = referencia.delta_t10_menos_O1(CARPETA_TEST)
    delta_us = delta_info["media_us"]
    sigma_delta_us = delta_info["sigma_us"]
    n_delta = delta_info["n"]

    # Calibrar CH4 con t10 y con O1
    u = 50.0
    res_t10 = arribo.calibrar_retardo(CARPETA_TEST, "ch4", u, 0.035, 0.15, referencia="t10")
    res_o1 = arribo.calibrar_retardo(CARPETA_TEST, "ch4", u, 0.035, 0.15, referencia="origen_virtual_IEC60060")

    assert res_t10["valido"] and res_o1["valido"]
    t_lag_t10_us = res_t10["t_lag_us"]
    t_lag_o1_us = res_o1["t_lag_us"]

    # V5.2: t_lag(O1) - t_lag(t10) ≈ delta
    diff_us = t_lag_o1_us - t_lag_t10_us
    tol_us = 3.0 * (sigma_delta_us / np.sqrt(n_delta)) + 2e-3  # 3*SE + 2 ns
    assert abs(diff_us - delta_us) < tol_us, f"Diff {diff_us*1e3:.2f} ns vs Delta {delta_us*1e3:.2f} ns (tol {tol_us*1e3:.2f} ns)"

    # V5.3: Guardar con t10 -> leer -> t_lag_A
    ancla_completa = persistencia.construir_info_ancla(CARPETA_TEST)
    bloque_a = persistencia.bloque_calibracion_retardo(
        resultados={"ch4": res_t10},
        fuente="medicion_t10",
        referencia_impulso="t10",
    )
    persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_a)
    cal_a = app.calibracion_desde_metadata(CARPETA_TEST)
    t_lag_a = cal_a["canales"]["ch4"]["t_lag_us"]

    # Guardar con O1 + ancla -> leer -> t_lag_B
    bloque_b = persistencia.bloque_calibracion_retardo(
        resultados={"ch4": res_o1},
        fuente="medicion_o1",
        referencia_impulso="origen_virtual_IEC60060",
        info_ancla=ancla_completa,
    )
    persistencia.guardar_calibracion_metadata(CARPETA_TEST, bloque_b)
    cal_b = app.calibracion_desde_metadata(CARPETA_TEST)
    t_lag_b = cal_b["canales"]["ch4"]["t_lag_us"]

    # Assert |A - B| < 3*sigma
    sigma_comb_us = np.sqrt((res_t10["sigma_us"] or 1e-3)**2 + (res_o1["sigma_us"] or 1e-3)**2)
    assert abs(t_lag_a - t_lag_b) < (3.0 * sigma_comb_us + 2e-3), (
        f"t_lag_A={t_lag_a*1e3:.2f} ns vs t_lag_B={t_lag_b*1e3:.2f} ns difieren en {abs(t_lag_a - t_lag_b)*1e3:.2f} ns"
    )
