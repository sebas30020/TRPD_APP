"""Verificación, al cargar una medición en calibrar_app, de la calibración guardada en
metadata.yaml: completa, incompleta, a revisar o sin calibrar."""

from __future__ import annotations
import os
import sys

import numpy as np
import pytest
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import datos_h5
import filtros
import main as cal_main
import persistencia
from datos import spec_filtro
from test_generate_metadata import NPTS, XINC, XORG, _escribir_canal


@pytest.fixture
def med3(tmp_path):
    """Medición sintética con CH1 y los tres sensores."""
    t = XORG + np.arange(NPTS) * XINC
    rng = np.random.default_rng(1)
    d = tmp_path / "3v_4mm_1" / "11kV"
    d.mkdir(parents=True)
    _escribir_canal(str(d / "ch1.h5"), 1, lambda _: np.where(t < 0, 0.0, 2.0) + rng.normal(0, 0.005, NPTS))
    for n in (2, 3, 4):
        _escribir_canal(str(d / f"ch{n}.h5"), n, lambda _: rng.normal(0, 0.002, NPTS))
    return str(d)


def _bloque(med, canales, **extra_canal):
    b = {"fecha": "2026-10-09", "fuente_calibracion": "calibrar_app", "referencia_impulso": "t10"}
    for ch in canales:
        b[ch] = {"sensor": ch, "t_lag_ns": -110.0, "sigma_ns": 17.0, "n_valid": 11, "n_total": 15,
                 "umbral_mv": 40.0, "tmin_us": -0.4, "tmax_us": -0.3,
                 "filtro": filtros.texto(spec_filtro(med, ch)), **extra_canal}
    return b


def _escribir(med, datos):
    ruta = os.path.join(med, "metadata.yaml")
    with open(ruta, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, sort_keys=False)
    datos_h5.invalidar_archivo(ruta)  # como al guardar desde las apps


def test_sin_calibrar(med3):
    est = persistencia.estado_calibracion(med3)
    assert est["estado"] == "sin_calibrar" and est["n_canales"] == 3
    assert est["faltan"] == ["ch2", "ch3", "ch4"]


def test_incompleta(med3):
    _escribir(med3, {"calibracion_retardo": _bloque(med3, ["ch2", "ch4"])})
    est = persistencia.estado_calibracion(med3)
    assert est["estado"] == "incompleta" and est["faltan"] == ["ch3"]
    assert est["canales"]["ch2"]["estado"] == "calibrado"


def test_completa(med3):
    _escribir(med3, {"calibracion_retardo": _bloque(med3, ["ch2", "ch3", "ch4"])})
    est = persistencia.estado_calibracion(med3)
    assert est["estado"] == "completa" and est["n_calibrados"] == 3
    assert est["fecha"] == "2026-10-09" and est["referencia"] == "t10"


def test_revisar_por_filtro(med3):
    b = _bloque(med3, ["ch2", "ch3", "ch4"])
    b["ch3"]["filtro"] = "HP_1MHz"
    del b["ch4"]["filtro"]
    _escribir(med3, {"calibracion_retardo": b})
    est = persistencia.estado_calibracion(med3)
    assert est["estado"] == "revisar"
    assert "filtro HP_1MHz" in est["canales"]["ch3"]["motivos"][0]
    assert est["canales"]["ch4"]["motivos"] == ["calibrado sobre señal cruda"]


def test_revisar_por_ediciones_posteriores(med3):
    # Guardado con 1 arribo manual; después se quitó otro disparo sin volver a guardar
    b = _bloque(med3, ["ch2", "ch3", "ch4"])
    b["ch2"].update(n_arribos_manuales=1, n_disparos_quitados=0)
    ed = {"ch2": {"historial": [{"accion": "fijar", "seg": 3, "t_us": -0.36}]}}
    _escribir(med3, {"calibracion_retardo": b, "ediciones_arribo": ed})
    assert persistencia.estado_calibracion(med3)["estado"] == "completa"
    ed["ch2"]["historial"].append({"accion": "quitar", "seg": 5})
    est = persistencia.estado_calibracion(med3, ed)
    assert est["canales"]["ch2"]["motivos"] == ["arribos editados después de guardar"]


def test_panel_muestra_lo_guardado_sin_calcular(med3):
    # El caso reportado: medición ya calibrada, sesión sin cálculos
    _escribir(med3, {"calibracion_retardo": _bloque(med3, ["ch2", "ch3", "ch4"])})
    txt = str(cal_main.actualizar_tabla_resumen({}, med3, None))
    assert "Calibración completa en metadata.yaml: 3/3 canales" in txt
    assert "-110.00" in txt and "Sin cálculos en esta sesión" in txt


def test_panel_sesion_pendiente_de_guardar(med3):
    _escribir(med3, {"calibracion_retardo": _bloque(med3, ["ch2"])})
    r = {"t_lag_us": -0.120, "sigma_us": 0.01, "n_valid": 10, "n_total": 15, "segs": [],
         "params": {"umbral_mv": 40.0, "distancia_us": 0.05, "tmin_us": -0.4}}
    store = {"_carpeta": med3, "ch2": dict(r, t_lag_us=-0.110), "ch3": r}
    txt = str(cal_main.actualizar_tabla_resumen(store, med3, None))
    assert "Calibración incompleta: 1/3 canales · falta CH3, CH4" in txt
    assert "✓ guardado" in txt and "pendiente de guardar" in txt
