"""Capa de lectura compartida (datos_h5.py): resultados idénticos a la lectura
directa, archivos abiertos una sola vez, cálculo único concurrente y caché por
fecha de modificación."""

import os
import threading
import time
from collections import OrderedDict

import h5py
import numpy as np
import pytest

import app
import datos_h5
from test_generate_metadata import XORG, NPTS, _escribir_canal


@pytest.fixture
def medicion(tmp_path):
    t = XORG + np.arange(NPTS) * 2e-10

    def senal(i):
        return 0.5 * np.sin(2 * np.pi * 3e6 * t) + 0.1 * i + np.exp(-((t - 2e-6) / 2e-9) ** 2)

    d = tmp_path / "1v_2mm_0" / "17.5kV"
    d.mkdir(parents=True)
    for n in (1, 2):
        _escribir_canal(str(d / f"ch{n}.h5"), n, senal)
    yield str(d)
    datos_h5.limpiar_caches()   # cerrar handles antes de que pytest borre tmp_path


def _lectura_directa(carpeta, canal, seg, ventana, spec=None):
    """Referencia: lo que hacía app._cargar_segmento_leer antes de datos_h5."""
    m = datos_h5.meta_medicion(carpeta)[canal]
    with h5py.File(datos_h5.ruta_canal(carpeta, canal), "r") as f:
        dset = f[f"Waveforms/{m['chan']}/{m['chan']} Seg{seg}Data"]
        n = dset.shape[0]
        i0 = max(int(np.ceil((ventana[0] * 1e-6 - m["xorg"]) / m["xinc"])), 0)
        i1 = min(int(np.floor((ventana[1] * 1e-6 - m["xorg"]) / m["xinc"])) + 1, n)
        margen = 0 if spec is None else int(round(1.0e-6 / m["xinc"]))
        a0, a1 = max(i0 - margen, 0), min(i1 + margen, n)
        raw = dset[a0:a1]
    v = (raw.astype(np.float64) * m["yinc"] + m["yorg"]) * 1e3
    if spec is not None:
        import filtros
        v = filtros.aplicar(v, 1.0 / m["xinc"], spec)[i0 - a0:i1 - a0]
    t = (m["xorg"] + np.arange(i0, i1) * m["xinc"]) * 1e6
    return t, v


@pytest.mark.parametrize("filtrado", [False, True])
def test_cargar_igual_que_lectura_directa(medicion, filtrado):
    spec = ("highpass", 5e6) if filtrado else None
    for seg in (1, 3):
        t, v = app.cargar_segmento(medicion, "ch2", seg, filtrado=filtrado)
        tr, vr = _lectura_directa(medicion, "ch2", seg, (app.T_MIN, app.T_MAX), spec)
        assert np.array_equal(t, tr)
        assert np.allclose(v, vr, rtol=0, atol=1e-9)
    assert not v.flags.writeable and not t.flags.writeable


def test_eje_t_compartido_entre_segmentos(medicion):
    t1, _ = app.cargar_segmento(medicion, "ch2", 1)
    t2, _ = app.cargar_segmento(medicion, "ch2", 2)
    assert t1 is t2


def test_archivo_se_abre_una_sola_vez(medicion, monkeypatch):
    datos_h5.limpiar_caches()
    abiertos = []
    orig = h5py.File

    def contar(ruta, *a, **k):
        abiertos.append(ruta)
        return orig(ruta, *a, **k)

    monkeypatch.setattr(datos_h5.h5py, "File", contar)
    for seg in range(1, 6):
        app.cargar_segmento(medicion, "ch2", seg, filtrado=False)
    assert len([r for r in abiertos if r.endswith("ch2.h5")]) == 1


def test_calcular_una_vez_concurrente():
    cache, llamadas = OrderedDict(), []

    def lento():
        llamadas.append(1)
        time.sleep(0.2)
        return 42

    res = []
    hilos = [threading.Thread(target=lambda: res.append(datos_h5.calcular_una_vez(cache, "k", lento)))
             for _ in range(5)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert res == [42] * 5 and len(llamadas) == 1


def test_calcular_una_vez_lru_acotada():
    cache = OrderedDict()
    for i in range(5):
        datos_h5.calcular_una_vez(cache, i, lambda i=i: i, maxsize=3)
    assert list(cache) == [2, 3, 4]


def test_cacheado_por_archivo(tmp_path, monkeypatch):
    ruta = tmp_path / "metadata.yaml"
    ruta.write_text("a: 1", encoding="utf-8")
    llamadas = []

    def cargar():
        llamadas.append(1)
        return ruta.read_text(encoding="utf-8")

    monkeypatch.setattr(datos_h5, "INTERVALO_STAT_S", 0.0)
    assert datos_h5.cacheado_por_archivo(str(ruta), "x", cargar) == "a: 1"
    assert datos_h5.cacheado_por_archivo(str(ruta), "x", cargar) == "a: 1"
    assert len(llamadas) == 1                       # mismo mtime: no relee
    ruta.write_text("a: 2", encoding="utf-8")
    os.utime(ruta, (time.time() + 5, time.time() + 5))
    assert datos_h5.cacheado_por_archivo(str(ruta), "x", cargar) == "a: 2"
    datos_h5.invalidar_archivo(str(ruta))
    datos_h5.cacheado_por_archivo(str(ruta), "x", cargar)
    assert len(llamadas) == 3


def test_obtener_metadata_devuelve_copia(medicion):
    m1 = app.obtener_metadata(medicion)
    m1["probeta"] = "modificado"
    assert app.obtener_metadata(medicion).get("probeta") != "modificado"


def test_pasada_ch1_equivale_a_recorrer_ch1(medicion):
    t0, prom = app.promedio_impulso(medicion)
    acc = None
    for s in range(1, app.n_segmentos(medicion) + 1):
        _, v = app.cargar_segmento(medicion, "ch1", s)
        acc = v.copy() if acc is None else acc + v
    assert np.allclose(prom, acc / app.n_segmentos(medicion))
    t10 = app.t10_por_segmento(medicion)
    assert t10.size == app.n_segmentos(medicion)
