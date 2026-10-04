"""transformada_s (plegado espectral) frente a la implementación directa anterior."""

import numpy as np
import pytest
import scipy.fft as sfft

import app


def _referencia(x, t_us, dt_us, fmax_mhz, nfreq, paso, bloque=16):
    """Implementación directa previa: IFFT de longitud N por fila y decimado [::paso]."""
    N = x.size
    X = sfft.fft(x)
    m = sfft.fftfreq(N) * N
    jmax = max(1, min(N // 2, int(round(fmax_mhz * 1e6 * N * dt_us * 1e-6))))
    js = np.unique(np.linspace(1, jmax, min(nfreq, jmax)).round().astype(int))
    t_dec = t_us[::paso]
    A = np.empty((js.size + 1, t_dec.size))
    A[0, :] = abs(float(x.mean()))
    for a in range(0, js.size, bloque):
        jb = js[a:a + bloque]
        idx = (np.arange(N)[None, :] + jb[:, None]) % N
        G = np.exp(-2 * np.pi ** 2 * m[None, :] ** 2 / jb[:, None] ** 2)
        A[a + 1:a + 1 + jb.size] = np.abs(sfft.ifft(X[idx] * G, axis=1))[:, ::paso]
    return t_dec, np.concatenate(([0.0], js / (N * dt_us))), A


def _senales(N, dt_us):
    t = np.arange(N) * dt_us
    rng = np.random.default_rng(1)
    return {
        "tono": 3.0 * np.sin(2 * np.pi * 400.0 * t),               # 400 MHz
        "pulso": np.exp(-((t - t[N // 3]) / (20 * dt_us)) ** 2) + 0.2,
        "ruido": rng.normal(size=N),
    }, t


def _comparar(x, t, dt_us, n_t):
    td, f, A = app.transformada_s(x, t, dt_us, 3000, 120, n_t)
    paso = int(round((td[1] - td[0]) / dt_us)) if td.size > 1 else 1
    n_usadas = td.size * paso                     # muestras que entraron en la ST
    tr, fr, Ar = _referencia(x[:n_usadas], t[:n_usadas], dt_us, 3000, 120, paso)
    assert np.allclose(td, tr)
    assert np.allclose(f, fr)
    assert np.max(np.abs(A - Ar)) <= 1e-5 * np.max(Ar)
    return paso, n_usadas


@pytest.mark.parametrize("N,n_t", [(701, 700), (20000, 400), (350000 // 10, 2000)])
def test_igual_que_referencia_exacto(N, n_t):
    """Paso que divide a N (o divisor cercano): mismas muestras que la referencia."""
    dt_us = 1e-4                                   # 10 GSa/s
    senales, t = _senales(N, dt_us)
    for x in senales.values():
        paso, n_usadas = _comparar(x, t, dt_us, n_t)
        assert n_usadas == N                       # sin recorte
        assert N // n_t // 2 <= paso <= max(1, N // n_t)


def test_n_primo_recorta_pocas_muestras():
    """Si ningún divisor sirve, se recortan < paso muestras finales y el resto es exacto."""
    dt_us, N = 1e-4, 20011                         # 20011 es primo
    senales, t = _senales(N, dt_us)
    paso, n_usadas = _comparar(senales["pulso"], t, dt_us, 400)
    assert N - n_usadas < paso


def test_tono_da_media_amplitud():
    dt_us, N = 1e-4, 20000
    t = np.arange(N) * dt_us
    x = 2.0 * np.sin(2 * np.pi * 500.0 * t)
    _, f, A = app.transformada_s(x, t, dt_us, 3000, 600, 500)
    fila = int(np.argmin(np.abs(f - 500.0)))
    assert np.median(A[fila, 50:-50]) == pytest.approx(1.0, rel=0.05)


def test_salida_float32_y_tope_3ghz():
    dt_us, N = 1e-4, 5000
    t = np.arange(N) * dt_us
    _, f, A = app.transformada_s(np.sin(t), t, dt_us, 4500, 100, 500)
    assert A.dtype == np.float32
    assert f.max() <= 3000.0 + 1e-6
