"""Calibración: franjas relativas al t10, validez por ruido de fondo (inicio del registro),
«Ajustar umbrales» (30 % de la mediana de la ráfaga) y arribo del HFCT en el máximo."""

from __future__ import annotations
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import arribo  # noqa: E402
import generate_metadata  # noqa: E402

DT = 1e-4
T = np.arange(-10.0, 5.0, DT)
RUIDO = 2.0                                    # mV rms
RAFAGAS = {1: 300.0, 2: 250.0, 3: 350.0, 4: 10.0}   # disparo 4: ráfaga débil (SNR 5)


def _senal(seg):
    rng = np.random.default_rng(seg)
    v = rng.normal(0.0, RUIDO, T.size)
    # Oscilación del spark gap a -0.35 µs (lóbulo de 2 ns) y un pico de "descarga" a +2 µs
    v += RAFAGAS[seg] * np.exp(-0.5 * ((T + 0.35) / 0.0005) ** 2)
    v += 500.0 * np.exp(-0.5 * ((T - 2.0) / 0.0005) ** 2)
    return v


def _parchear(monkeypatch):
    arribo._ARRIBO_CACHE.clear()
    monkeypatch.setattr(arribo, "cargar_segmento", lambda c, ch, s, ventana=None, **k: (T, _senal(int(s))))
    monkeypatch.setattr(arribo, "n_segmentos", lambda c: 4)
    monkeypatch.setattr(arribo, "_muestras", lambda c, ch, d: None)
    monkeypatch.setattr(arribo, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    monkeypatch.setattr(arribo, "ancla_por_segmento", lambda c, referencia="t10": {"ancla_us": np.full(4, -0.25)})


def test_ruido_de_fondo_al_inicio_del_registro():
    t = np.arange(-10.0, 5.0, DT)
    v = np.random.default_rng(0).normal(0.0, 3.0, t.size)
    v[t > -1.0] += 200.0 * np.sin(t[t > -1.0] * 50)     # actividad posterior: no cuenta
    assert abs(arribo.ruido_fondo(t, v) - 3.0) < 0.2


def test_ajustar_umbral_con_todos_los_disparos(monkeypatch):
    _parchear(monkeypatch)
    r = arribo.ajustar_umbral("M", "ch3", -0.15, -0.05)
    assert r["n_validos"] == 3 and r["n_total"] == 4               # el disparo 4 no supera 8× ruido
    assert abs(r["umbral_mv"] - 0.3 * 300.0) < 3.0                 # 30 % de la mediana (300 mV)
    assert r["snr"][3] < arribo.SNR_MIN < min(r["snr"][:3])
    # La descarga de +2 µs queda fuera de la franja y no infla la ráfaga
    assert max(r["rafaga_mv"]) < 400.0


def test_calibrar_descarta_disparos_bajo_el_ruido(monkeypatch):
    _parchear(monkeypatch)
    res = arribo.calibrar_retardo("M", "ch3", 90.0, 0.05, -0.15, tmax=-0.05)
    assert res["bajo_ruido"] == [False, False, False, True] and res["n_bajo_ruido"] == 1
    assert res["t_ant"][3] is None and res["n_valid"] == 3
    assert abs(res["t_lag_us"] - (-0.35 + 0.25)) < 1e-4            # arribo en el máximo del lóbulo
    assert res["params"]["snr_min"] == arribo.SNR_MIN
    # snr_min=None: sin esta condición (el disparo 4 tampoco cruza 90 mV, pero no por ruido)
    res2 = arribo.calibrar_retardo("M", "ch3", 5.0, 0.05, -0.15, tmax=-0.05, snr_min=None)
    assert res2["n_bajo_ruido"] == 0 and res2["t_ant"][3] is not None


def test_bloque_metadata_registra_snr(monkeypatch):
    _parchear(monkeypatch)
    res = arribo.calibrar_retardo("M", "ch3", 90.0, 0.05, -0.15, tmax=-0.05)
    b = generate_metadata.bloque_calibracion_retardo({"ch3": res}, "test")
    assert b["ch3"]["snr_min"] == arribo.SNR_MIN and b["ch3"]["n_bajo_ruido"] == 1
    assert b["criterio"] == "franja_t10" and b["ch3"]["franja_referencia"] == "t10"


def test_franja_relativa_al_t10_de_cada_disparo(monkeypatch):
    _parchear(monkeypatch)
    # Con el t10 corrido +0.2 µs la ráfaga (-0.35) queda fuera de t10 + [-0.15, -0.05]
    monkeypatch.setattr(arribo, "ancla_por_segmento",
                        lambda c, referencia="t10": {"ancla_us": np.full(4, -0.05)})
    res = arribo.calibrar_retardo("M", "ch3", 90.0, 0.05, -0.15, tmax=-0.05)
    assert res["n_valid"] == 0
    res = arribo.calibrar_retardo("M", "ch3", 90.0, 0.05, -0.35, tmax=-0.25)
    assert res["n_valid"] == 3 and abs(res["t_lag_us"] - (-0.30)) < 1e-4


def test_hfct_arribo_en_el_maximo_de_la_franja(monkeypatch):
    _parchear(monkeypatch)

    def hfct(seg):
        v = np.random.default_rng(seg).normal(0.0, RUIDO, T.size)
        v += 120.0 * np.exp(-0.5 * ((T + 0.37) / 0.004) ** 2)      # primera oscilación pequeña
        v -= 600.0 * np.exp(-0.5 * ((T + 0.33) / 0.006) ** 2)      # lóbulo grande
        return v
    monkeypatch.setattr(arribo, "cargar_segmento", lambda c, ch, s, ventana=None, **k: (T, hfct(int(s))))
    res = arribo.calibrar_retardo("M", "ch2", 50.0, 0.05, -0.15, tmax=-0.05)
    assert res["arribo"] == "maximo_franja" and res["params"]["umbral_mv"] is None
    assert res["n_valid"] == 4 and abs(res["t_lag_us"] - (-0.33 + 0.25)) < 2e-4
