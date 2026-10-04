"""Filtros digitales por canal (filtros.py) y su aplicación al cargar segmentos."""

import os
import sys

import numpy as np
import pytest

import app
import filtros
from test_generate_metadata import XINC, XORG, NPTS, _escribir_canal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibrar_app"))
import datos  # noqa: E402  (calibrar_app/datos.py, como en test_regresion_calibracion)


def test_parsear_filtro():
    assert filtros.parsear_filtro("HP_5MHz") == ("highpass", 5e6)
    assert filtros.parsear_filtro("hp_200mhz") == ("highpass", 200e6)
    assert filtros.parsear_filtro("LP_10MHz") == ("lowpass", 10e6)
    assert filtros.parsear_filtro("HP 1.5 GHz") == ("highpass", 1.5e9)
    for nada in (None, "", "ninguno", "None", "sin filtro"):
        assert filtros.parsear_filtro(nada) is None
    assert filtros.parsear_filtro("pasa-algo") is None


def test_texto_y_etiqueta():
    for t in ("HP_5MHz", "HP_200MHz", "LP_10MHz"):
        assert filtros.texto(filtros.parsear_filtro(t)) == t
    assert filtros.etiqueta(("highpass", 5e6)) == "HP 5 MHz"
    assert filtros.etiqueta(None) == "sin filtro"
    assert filtros.texto(None) == "ninguno"


def test_filtro_canal():
    assert filtros.filtro_canal({}, "ch2") == ("highpass", 5e6)
    assert filtros.filtro_canal(None, "ch3") == ("highpass", 200e6)
    assert filtros.filtro_canal({}, "ch4") == ("highpass", 200e6)
    assert filtros.filtro_canal({}, "ch1") is None
    meta = {"canales": {"ch3": {"filtro": "ninguno"}, "ch4": {"sensor": "Antena 2"}}}
    assert filtros.filtro_canal(meta, "ch3") is None            # 'ninguno' explícito
    assert filtros.filtro_canal(meta, "ch4") == ("highpass", 200e6)   # sin clave -> defecto


def _amplitud(fs, f, spec):
    t = np.arange(20000) / fs
    y = filtros.aplicar(np.sin(2 * np.pi * f * t), fs, spec)
    return np.max(np.abs(y[5000:15000]))     # lejos de los bordes


def test_aplicar_respuesta_en_frecuencia():
    fs = 1e9
    assert _amplitud(fs, 1e6, ("highpass", 5e6)) < 0.1
    assert _amplitud(fs, 50e6, ("highpass", 5e6)) > 0.95
    assert _amplitud(fs, 20e6, ("highpass", 200e6)) < 0.1
    assert _amplitud(fs, 400e6, ("highpass", 200e6)) > 0.95


def test_aplicar_corte_sobre_nyquist_no_filtra():
    v = np.random.default_rng(0).normal(size=1000)
    assert np.array_equal(filtros.aplicar(v, 300e6, ("highpass", 200e6)), v)
    assert filtros.aplicar(v, 1e9, None) is v


@pytest.fixture
def medicion_ch2(tmp_path):
    """ch2 con rampa lenta (componente del impulso) + pulso rápido de 1 V en t = 2 µs."""
    t = XORG + np.arange(NPTS) * XINC

    def senal(_):
        rampa = 2.0 * np.clip((t + 1e-6) / 20e-6, 0, 1)
        pulso = np.exp(-((t - 2e-6) / 2e-9) ** 2)
        return rampa + pulso

    d = tmp_path / "1v_2mm_0" / "17.5kV"
    d.mkdir(parents=True)
    _escribir_canal(str(d / "ch1.h5"), 1, lambda _: np.zeros(NPTS))
    _escribir_canal(str(d / "ch2.h5"), 2, senal)
    return str(d)


def test_cargar_segmento_filtrado(medicion_ch2):
    t, crudo = app.cargar_segmento(medicion_ch2, "ch2", 1, filtrado=False)
    _, filt = app.cargar_segmento(medicion_ch2, "ch2", 1, filtrado=True)
    assert t.size == crudo.size == filt.size
    lejos = np.abs(t - 2.0) > 0.5                       # fuera del pulso
    assert np.max(crudo[lejos]) > 1000                  # rampa de hasta 2 V (mV)
    assert np.max(np.abs(filt[lejos][t[lejos] > 0])) < 50   # la componente lenta desaparece
    assert np.max(filt) > 800                           # el pulso se conserva
    # CH1 nunca se filtra
    _, c1a = app.cargar_segmento(medicion_ch2, "ch1", 1, filtrado=True)
    _, c1b = app.cargar_segmento(medicion_ch2, "ch1", 1, filtrado=False)
    assert np.array_equal(c1a, c1b)


def test_cargar_segmento_no_depende_de_la_ventana(medicion_ch2):
    t, v = app.cargar_segmento(medicion_ch2, "ch2", 1, ventana=(-5.0, 30.0))
    t2, v2 = app.cargar_segmento(medicion_ch2, "ch2", 1, ventana=(1.0, 3.0))
    i0 = int(np.searchsorted(t, t2[0]))
    assert np.allclose(v[i0:i0 + t2.size], v2, atol=1e-6 * np.max(np.abs(v)) + 1e-9, rtol=1e-3)


def test_capturar_cache_separa_filtrado(medicion_ch2):
    a = app.capturar(medicion_ch2, "ch2", 500.0, 0.035, 0.0, filtrado=True)
    b = app.capturar(medicion_ch2, "ch2", 500.0, 0.035, 0.0, filtrado=False)
    assert a is not b
    assert a["t_peak"].size == 5 and np.allclose(a["t_peak"], 2.0, atol=0.01)   # el pulso de cada disparo
    assert b["t_peak"].size >= 1


def test_calibrar_app_filtra_igual(medicion_ch2):
    _, va = app.cargar_segmento(medicion_ch2, "ch2", 1, ventana=datos.VENTANA_T10)
    _, vb = datos.cargar_segmento(medicion_ch2, "ch2", 1, ventana=datos.VENTANA_T10)
    assert np.allclose(va, vb)


def test_fila_densidad_marca_filtro(medicion_ch2):
    f = app.calcular_fila_densidad(medicion_ch2, "ch2", 500.0, 0.035, 0.0)
    assert f["_filtrado"] is True and f["_filtro"] == "HP 5 MHz"
    assert f["n_coinc"] == "5"            # 1 pulso por disparo en los 5 segmentos, probeta 1v
