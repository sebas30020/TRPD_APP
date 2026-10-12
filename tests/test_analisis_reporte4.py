"""Tests unitarios para analisis_reporte4.py con datos sintéticos (sin .h5).

Verifica:
1. Interpolación de u_inst y pico_impulso sobre una doble exponencial conocida (IEC 60060-1).
2. Tiempo de cruce en el frente de onda.
3. Emparejamiento húngaro con desfases, huecos y tolerancias temporales.
4. Agrupamiento de eventos por disparo (CH2, CH3, CH4 con desfase de HFCT).
5. Ajuste binomial (logística y Weibull) recuperando parámetros simulados y bootstrap.
6. Spearman y corrección FDR de Benjamini-Hochberg sobre series con y sin tendencia.
7. Intervalos entre descargas.
8. Mezcla gaussiana (GMM) sintética con selección BIC.
"""

import numpy as np
import pytest

import analisis_reporte4 as ar


def doble_exponencial(t, v0=3.0, tau1=68.22, tau2=0.4046):
    """Impulso estándar analítico 1.2/50 µs."""
    t = np.asarray(t, dtype=float)
    u = np.where(t > 0, np.exp(-t / tau1) - np.exp(-t / tau2), 0.0)
    # Factor analítico de pico
    tp = (tau1 * tau2 / (tau1 - tau2)) * np.log(tau1 / tau2)
    norm = np.exp(-tp / tau1) - np.exp(-tp / tau2)
    return v0 * (u / norm)


def test_suavizar_y_pico_impulso():
    t = np.linspace(-1.0, 10.0, 110001)  # dt = 0.0001 us = 0.1 ns (10 GS/s)
    v_ideal = doble_exponencial(t, v0=3.2)
    # Añadir ruido Gaussiano de alta frecuencia
    rng = np.random.default_rng(42)
    ruido = rng.normal(0, 0.05, size=t.shape)
    v_ruidoso = v_ideal + ruido

    dt_ns = (t[1] - t[0]) * 1e3
    n_muestras = int(round(50.0 / dt_ns))  # 50 ns
    v_suav = ar.suavizar(v_ruidoso, n_muestras)

    u_pico, t_pico = ar.pico_impulso(t, v_suav)
    # Pico real ~ 3.2 V
    assert abs(u_pico - 3.2) < 0.05
    # t_pico esperado para 1.2/50 µs es ~ 1.2 - 1.8 µs
    assert 0.8 < t_pico < 2.5


def test_tension_instantanea_y_cruce():
    t = np.linspace(0.0, 10.0, 10001)
    v = doble_exponencial(t, v0=3.0)

    # Evaluar en puntos conocidos
    t_eval = np.array([0.5, 1.2, 5.0])
    u_inst = ar.tension_instantanea(t, v, t_eval)
    assert u_inst.shape == (3,)
    for ti, ui in zip(t_eval, u_inst):
        assert abs(ui - doble_exponencial(ti, v0=3.0)) < 1e-4

    # Tiempo de cruce en el frente
    u_target = 1.5  # Cruce al 50%
    tc = ar.tiempo_cruce(t, v, u_target)
    assert not np.isnan(tc)
    assert abs(doble_exponencial(tc, v0=3.0) - u_target) < 0.01

    # Cruce imposible por encima del pico
    tc_nan = ar.tiempo_cruce(t, v, 5.0)
    assert np.isnan(tc_nan)


def test_emparejar_hungaro():
    # ta y tb con desfases pequeños y algunos eventos sin par
    # Tol: 0.005 us = 5 ns
    tol = 0.005
    ta = np.array([1.000, 2.000, 3.000, 4.000])
    tb = np.array([0.998, 2.003, 3.010, 5.000])  # 3.010 se aleja 10 ns (fuera de tol 5 ns)

    pares = ar.emparejar(ta, tb, tol)
    # Esperado: (0, 0) dif 2 ns; (1, 1) dif 3 ns
    assert pares == [(0, 0), (1, 1)]

    # Caso vacío
    assert ar.emparejar(np.array([]), tb, tol) == []
    assert ar.emparejar(ta, np.array([]), tol) == []


def test_eventos_disparo():
    # Simular un disparo con 3 descargas físicas:
    # Evento 1: detectado por CH2, CH3, CH4
    # Evento 2: detectado solo por CH3, CH4
    # Evento 3: detectado solo por CH2
    desfase_hfct = 0.015  # 15 ns = 0.015 us
    tol34 = 0.005         # 5 ns
    tol2 = 0.015          # 15 ns tras corregir desfase

    t_real_1 = 1.000
    t_real_2 = 2.500
    t_real_3 = 4.000

    t_dict = {
        "ch3": np.array([t_real_1, t_real_2]),
        "ch4": np.array([t_real_1 + 0.001, t_real_2 - 0.001]),
        "ch2": np.array([t_real_1 + desfase_hfct + 0.002, t_real_3 + desfase_hfct]),
    }

    eventos = ar.eventos_disparo(t_dict, desfase_hfct, tol34, tol2)
    assert len(eventos) == 3

    # Evento 1: tiene los 3 canales
    e1 = eventos[0]
    assert e1["ch3"] == 0
    assert e1["ch4"] == 0
    assert e1["ch2"] == 0
    assert abs(e1["t_ref"] - t_real_1) < 0.002

    # Evento 2: ch3 y ch4, no ch2
    e2 = eventos[1]
    assert e2["ch3"] == 1
    assert e2["ch4"] == 1
    assert e2["ch2"] is None
    assert abs(e2["t_ref"] - t_real_2) < 0.002

    # Evento 3: solo ch2
    e3 = eventos[2]
    assert e3["ch3"] is None
    assert e3["ch4"] is None
    assert e3["ch2"] == 1
    assert abs(e3["t_ref"] - t_real_3) < 0.002


def test_ajuste_binomial_logistica():
    # Simular una curva S logística perfecta
    u50_real = 2.5
    s_real = 0.20
    x = np.array([1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2])
    n = np.full_like(x, 100)
    # Probabilidad teórica
    p = 1.0 / (1.0 + np.exp(-(x - u50_real) / s_real))
    k = np.round(n * p)

    res = ar.ajuste_binomial(x, k, n, modelo="logistica")
    assert abs(res["u50"] - u50_real) < 0.05
    assert abs(res["b"] - s_real) < 0.05
    assert res["u10"] < res["u50"]

    # Bootstrap binomial
    u10_boot, u50_boot = ar.bootstrap_binomial(x, k, n, "logistica", res["theta"], n_boot=50, semilla=123)
    assert len(u50_boot) >= 40
    ic = ar.ic95(u50_boot)
    assert ic[0] <= u50_real <= ic[1]


def test_ajuste_binomial_weibull():
    a_real = 2.8
    b_real = 8.0
    x = np.array([1.5, 2.0, 2.3, 2.5, 2.7, 2.9, 3.2])
    n = np.full_like(x, 100)
    p = 1.0 - np.exp(-((x / a_real) ** b_real))
    k = np.round(n * p)

    res = ar.ajuste_binomial(x, k, n, modelo="weibull")
    u50_teorico = a_real * (np.log(2.0) ** (1.0 / b_real))
    assert abs(res["u50"] - u50_teorico) < 0.1
    assert res["u10"] < res["u50"]


def test_spearman_y_fdr_bh():
    # Serie monótona creciente
    x = np.arange(10, dtype=float)
    y = 2.0 * x + 5.0
    rho, p, n = ar.spearman(x, y)
    assert abs(rho - 1.0) < 1e-6
    assert p < 1e-4
    assert n == 10

    # Serie con NaN
    x[2] = np.nan
    rho_nan, p_nan, n_nan = ar.spearman(x, y)
    assert abs(rho_nan - 1.0) < 1e-6
    assert n_nan == 9

    # Corrección FDR Benjamini-Hochberg
    p_vals = np.array([0.001, 0.01, 0.04, 0.20, 0.80])
    q_vals = ar.fdr_bh(p_vals)
    assert np.all(q_vals >= p_vals)
    assert np.all(np.diff(q_vals) >= -1e-12)  # Monótona respecto al ranking


def test_intervalos():
    t = np.array([3.5, 1.2, 2.0])  # Desordenados
    dt = ar.intervalos(t)
    # Ordenados: 1.2, 2.0, 3.5 -> diffs: 0.8, 1.5
    np.testing.assert_allclose(dt, [0.8, 1.5])


def test_gmm_y_seleccion_bic():
    # Generar 2 clusters sintéticos bien separados en 2D
    rng = np.random.default_rng(99)
    c1 = rng.normal(loc=[-2.0, -2.0], scale=0.3, size=(50, 2))
    c2 = rng.normal(loc=[2.0, 2.0], scale=0.3, size=(50, 2))
    X = np.vstack([c1, c2])

    mejor, ajustes = ar.seleccionar_gmm(X, k_max=3, semilla=99)
    # Debe preferir k = 2
    assert mejor["k"] == 2
    assert len(ajustes) == 3
