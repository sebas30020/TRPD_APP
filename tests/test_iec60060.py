"""Tests para iec60060.py (V1, V2, V3 del plan).

Puro numérico y sin I/O: no depende de archivos externos ni de mediciones.
"""

import sys
import os
import numpy as np
import pytest

# Agregar calibrar_app al sys.path
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import iec60060


def generar_impulso_ideal_8_1(cresta_kv=100.0, dt_us=0.002, t_min=-1.0, t_max=200.0):
    """Genera impulso ideal 1.2/50 µs según §8.1 de la metodología."""
    tau1 = 68.21697156
    tau2 = 0.40503431
    t = np.arange(t_min, t_max, dt_us)
    tp = (tau1 * tau2 / (tau1 - tau2)) * np.log(tau1 / tau2)
    v_norm = np.exp(-tp / tau1) - np.exp(-tp / tau2)

    u = np.zeros_like(t)
    pos = t >= 0
    u[pos] = cresta_kv * (np.exp(-t[pos] / tau1) - np.exp(-t[pos] / tau2)) / v_norm
    n_pre = int(round(abs(t_min) / dt_us))
    return t, u, n_pre, tau1, tau2


# ============================================================================
# V1: Vectores analíticos §8.1 y §8.2
# ============================================================================

def test_v1_impulso_ideal_8_1():
    t, u, n_pre, tau1_exp, tau2_exp = generar_impulso_ideal_8_1(cresta_kv=100.0, dt_us=0.002)
    dt_s = 2e-9

    res = iec60060.evaluar_impulso(t, u, dt_s, n_pre, pol=1, diezmado_ajuste=10)
    assert res["exito"] is True

    # Comprobaciones según tabla §8.1
    assert abs(res["Ut"] - 100.000) < 5e-3
    assert abs(res["t30"] - 0.1394) < 5e-4
    assert abs(res["t90"] - 0.8594) < 5e-4
    assert abs(res["T1"] - 1.2000) < 1e-3
    assert abs(res["O1"] - (-0.2206)) < 1e-3
    assert abs(res["t50"] - 49.7794) < 2e-3
    assert abs(res["T2"] - 50.000) < 5e-3
    assert res["beta_pct"] < 0.05
    assert abs(res["tau1"] - tau1_exp) < 0.05
    assert abs(res["tau2"] - tau2_exp) < 0.001
    assert abs(res["t10"] - 0.0413) < 5e-4
    assert res["veredicto"]["conforme"] is True


def test_v1_impulso_con_ruido_8_2():
    t, u, n_pre, _, _ = generar_impulso_ideal_8_1(cresta_kv=100.0, dt_us=0.002)
    dt_s = 2e-9
    rng = np.random.default_rng(0)
    ruido = rng.normal(0, 0.005 * 100.0, size=u.shape)  # 0.5% de ruido blanco
    u_ruido = u + ruido

    res = iec60060.evaluar_impulso(t, u_ruido, dt_s, n_pre, pol=1, diezmado_ajuste=10, suavizado_ue_ns=0.0)
    assert res["exito"] is True

    # Los tiempos son robustos (cota de 5e-3 µs = 5 ns)
    assert abs(res["T1"] - 1.2) < 5e-3
    assert abs(res["O1"] - (-0.2206)) < 5e-3
    # beta' se infla por el ruido como documenta la metodología (1.5% aprox, artefacto de ruido)
    assert 0.5 < res["beta_pct"] < 3.0


# ============================================================================
# V2: Filtro k(f)
# ============================================================================

def test_v2_coeficientes_k_tabla_verificada():
    # Ts = 10 ns
    b0_10, a1_10 = iec60060.coeficientes_k(10e-9)
    assert abs(b0_10 - 0.020744338) < 1e-7
    assert abs(a1_10 - 0.958511325) < 1e-7

    # Ts = 1 ns
    b0_1, a1_1 = iec60060.coeficientes_k(1e-9)
    assert abs(b0_1 - 0.002113588) < 1e-7
    assert abs(a1_1 - 0.995772824) < 1e-7

    # Ts = 0.2 ns (5 GS/s)
    b0_02, a1_02 = iec60060.coeficientes_k(0.2e-9)
    assert abs(b0_02 - 0.000423433) < 1e-7
    assert abs(a1_02 - 0.999153134) < 1e-7


def test_v2_filtro_k_frecuencia():
    # Impulso unitario centrado en N=65536
    N = 65536
    dt_s = 10e-9
    x = np.zeros(N, dtype=np.float64)
    x[N // 2] = 1.0

    y = iec60060.filtro_k(x, dt_s)
    H = np.abs(np.fft.rfft(y))
    f = np.fft.rfftfreq(N, d=dt_s) / 1e6  # en MHz

    mask = (f >= 0) & (f <= 5.0)
    k_teorico = iec60060.respuesta_k(f[mask])
    err_max = np.max(np.abs(H[mask] - k_teorico))
    # La metodología reporta 2.9e-4 a 10 ns; verificar < 1e-3
    assert err_max < 1e-3


def test_v2_fidelidad_vectorizada():
    # Compara contra el bucle explícito de referencia de §7
    dt_s = 2e-9
    b0, a1 = iec60060.coeficientes_k(dt_s)
    rng = np.random.default_rng(42)
    x = rng.standard_normal(5000)

    # Implementación recursiva escalar
    def fwd(v):
        y = np.empty_like(v)
        yp = 0.0
        xp = 0.0
        for i, xi in enumerate(v):
            yp = b0 * (xi + xp) + a1 * yp
            xp = xi
            y[i] = yp
        return y

    y_loop = fwd(fwd(x[::-1])[::-1])
    y_vect = iec60060.filtro_k(x, dt_s)

    assert np.max(np.abs(y_loop - y_vect)) < 1e-12


def test_v2_guarda_dtype():
    # Entrada entera convertida a float64
    x_int = np.arange(100, dtype=np.int16)
    y = iec60060.filtro_k(x_int, 1e-9)
    assert y.dtype == np.float64
    y_flt = iec60060.filtro_k(x_int.astype(np.float64), 1e-9)
    assert np.allclose(y, y_flt)


# ============================================================================
# V3: Regla de cruce (corrección del bug de §7)
# ============================================================================

def test_v3_cruce_frente_ultimo_vs_primero():
    t, u, _, _, _ = generar_impulso_ideal_8_1(cresta_kv=100.0, dt_us=0.002)
    i_pk = int(np.argmax(u))
    Ut = 100.0
    nivel30 = 0.30 * Ut

    # Añadir una espiga previa al frente en t = -0.5 µs
    u_mod = u.copy()
    idx_espiga = np.nonzero((t >= -0.51) & (t <= -0.49))[0]
    u_mod[idx_espiga] = 0.35 * Ut

    primero = iec60060.cruce_frente_primero(t, u_mod, nivel30, i_pk)
    ultimo = iec60060.cruce_frente_ultimo(t, u_mod, nivel30, i_pk)

    assert primero is not None and ultimo is not None
    # 'primero' se engancha erróneamente en la espiga (~ -0.5)
    assert abs(primero - (-0.5)) < 0.05
    # 'ultimo' toma el verdadero cruce del frente en 0.1394
    assert abs(ultimo - 0.1394) < 5e-4
    assert abs(primero - ultimo) > 0.5


def test_v3_evaluar_impulso_robusto_ante_prepulso():
    t, u, n_pre, _, _ = generar_impulso_ideal_8_1(cresta_kv=100.0, dt_us=0.002)
    dt_s = 2e-9
    # Añadir ruido o prepulso antes del pie en t = -0.2 µs que supere el 30%
    u_mod = u.copy()
    idx_espiga = np.nonzero((t >= -0.25) & (t <= -0.23))[0]
    u_mod[idx_espiga] = 0.35 * 100.0

    res = iec60060.evaluar_impulso(t, u_mod, dt_s, n_pre, pol=1, diezmado_ajuste=10)
    assert res["exito"] is True
    # O1 debe seguir siendo -0.2206 ± 0.002 µs
    assert abs(res["O1"] - (-0.2206)) < 2e-3
