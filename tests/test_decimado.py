"""Diezmado min-max del gráfico de señales y re-diezmado por zoom (Patch)."""

import numpy as np
from dash import no_update

import app


def _senal(n=350_000, dt=1e-4):
    t = -5.0 + np.arange(n) * dt
    rng = np.random.default_rng(3)
    v = rng.normal(0, 1, n)
    if n > 349_000:
        v[[1000, 123_456, 349_000]] = [80.0, -95.0, 60.0]   # picos aislados
    return t, v


def test_decimar_conserva_picos_y_orden():
    t, v = _senal()
    td, vd = app.decimar_minmax(t, v, 2000)
    assert td.size <= 4000
    assert np.all(np.diff(td) > 0)
    for i in (1000, 123_456, 349_000):
        assert t[i] in td and v[i] in vd
    assert vd.max() == v.max() and vd.min() == v.min()
    # cada tramo conserva su mínimo y su máximo
    largo = int(np.ceil(v.size / 2000))
    for b in (0, 777, 1999):
        tramo = v[b * largo:(b + 1) * largo]
        assert tramo.max() in vd and tramo.min() in vd


def test_decimar_no_toca_senales_cortas():
    t, v = _senal(3000)
    td, vd = app.decimar_minmax(t, v, 2000)
    assert td is t and vd is v


def test_tramo_visible_crudo_hasta_1us():
    t, v = _senal()
    td, vd = app.tramo_visible(t, v, 2.0, 2.0 + app.SIN_DIEZMADO_US)
    dentro = (t >= 2.0) & (t <= 2.0 + app.SIN_DIEZMADO_US)
    assert np.all(np.isin(t[dentro], td))                 # todas las muestras
    assert np.all(np.diff(td) > 0)
    td2, _ = app.tramo_visible(t, v, 2.0, 4.0)            # 2 µs: diezmado
    assert td2.size <= 2 * app.DEC_BUCKETS + 4


def test_rango_desde_relayout():
    assert app._rango_desde_relayout({"xaxis3.range[0]": 1.0, "xaxis3.range[1]": 1.5}) == (1.0, 1.5)
    assert app._rango_desde_relayout({"xaxis.range": [0, 2]}) == (0.0, 2.0)
    assert app._rango_desde_relayout({"xaxis.autorange": True}) == "completo"
    assert app._rango_desde_relayout({"shapes[2].y0": 4.0, "shapes[2].y1": 4.0}) is None
    assert app._rango_desde_relayout({"autosize": True}) is None
    assert app._rango_desde_relayout({"yaxis2.range[0]": 0, "yaxis2.range[1]": 1}) is None


def test_redecimar_zoom_patch_crudo(monkeypatch):
    t, v = _senal()
    monkeypatch.setattr(app, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "cargar_segmento", lambda c, ch, s, **k: (t, v))
    pat, rango = app.redecimar_zoom({"xaxis2.range[0]": 1.0, "xaxis2.range[1]": 1.5},
                                    "m", 1, "ch4", ["on"])
    ops = pat.to_plotly_json()["operations"]
    assert len(ops) == 6                                   # x e y de ch2, ch3, ch4
    val = ops[0]["params"]["value"]
    assert val["dtype"] == "f4"
    x = np.frombuffer(__import__("base64").b64decode(val["bdata"]), dtype=np.float32)
    assert x.size >= int(0.5 / 1e-4)                       # 0.5 µs a 10 GSa/s: crudo
    assert rango == {"carpeta": "m", "canal": "ch4", "x0": 1.0, "x1": 1.5}


def test_redecimar_ignora_arrastre_de_umbral():
    assert app.redecimar_zoom({"shapes[0].y0": 3.0}, "m", 1, "ch4") == (no_update, no_update)


def test_rango_vigente_por_medicion_y_canal():
    r = {"carpeta": "m", "canal": "ch4", "x0": 1.0, "x1": 2.0}
    assert app._rango_vigente(r, "m", "ch4") == (1.0, 2.0)
    assert app._rango_vigente(r, "m", "ch3") is None
    assert app._rango_vigente(None, "m", "ch4") is None
