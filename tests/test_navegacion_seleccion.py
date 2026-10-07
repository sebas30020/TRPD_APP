"""Tests de la barra de segmentos junto al gráfico, del clic en el TRPD (lleva al segmento
de la descarga y la resalta en las señales) y de la visibilidad de los peaks manuales."""

from __future__ import annotations
import os
import sys
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from app import figura, set_seleccion

P = {"carpeta": "mock", "canal": "ch4", "umbral": 10.0, "dist": 1.0, "tmin": 0.0, "filtrado": True}


class _Ctx:
    def __init__(self, prop_id):
        self.triggered = [{"prop_id": prop_id}]
        self.triggered_id = prop_id.split(".")[0]


def _cap():
    return {"seg": np.array([1, 2, 2, 3]), "t_peak": np.array([1.0, 2.0, 3.0, 4.0]),
            "v_peak": np.array([20.0, 21.0, 22.0, 23.0]), "vpp": np.array([30.0, 31.0, 32.0, 33.0]),
            "origen": np.array([0, 0, 1, 0])}


def _hijos(c):
    h = getattr(c, "children", None)
    return h if isinstance(h, list) else ([h] if h is not None and not isinstance(h, str) else [])


def _buscar(c, pred):
    if pred(c):
        return c
    for h in _hijos(c):
        r = _buscar(h, pred)
        if r is not None:
            return r
    return None


def _ids(c):
    out = {getattr(c, "id", None)}
    for h in _hijos(c):
        out |= _ids(h)
    return out


def test_barra_segmentos_junto_al_grafico():
    """La navegación de segmentos sale de la barra superior y va debajo de la barra de
    edición de peaks y antes del gráfico."""
    controles = _buscar(app.app.layout, lambda c: getattr(c, "className", None) == "controls")
    assert "segmento_prev" not in _ids(controles) and "carpeta" in _ids(controles)
    # Contenedor común: barra de edición (solo Señales), barra de segmentos (Señales y
    # Transformada S) y luego el gráfico de señales.
    cont = _buscar(app.app.layout, lambda c: any(getattr(h, "id", None) == "panel_senales" for h in _hijos(c)))
    hijos = _hijos(cont)
    pos = {(getattr(h, "id", None) or getattr(h, "className", None)): k for k, h in enumerate(hijos)}
    assert pos["panel_senales_ediciones"] + 1 == pos["barra-segmentos"] == pos["panel_senales"] - 1
    assert "btn_anadir_peak" in _ids(hijos[pos["panel_senales_ediciones"]])
    assert {"segmento_prev", "segmento", "segmento_total", "segmento_next"} <= _ids(hijos[pos["barra-segmentos"]])
    assert "grafico" in _ids(hijos[pos["panel_senales"]])


def test_clic_trpd_lleva_al_segmento(monkeypatch):
    monkeypatch.setattr(app, "_cap_p", lambda p, ed=None: _cap())
    monkeypatch.setattr(app, "_ed", lambda store, carpeta, canal: {"historial": []})
    clic = {"points": [{"curveNumber": 0, "pointNumber": 2, "customdata": [0, 0, 0, 0, 0, 2]}]}
    monkeypatch.setattr(app, "ctx", _Ctx("grafico_scatter.clickData"))
    assert set_seleccion(P, None, clic, None, None, P, seg_actual=1) == ([2], 2)
    # Ya en ese segmento: solo cambia la selección
    sel, seg = set_seleccion(P, None, clic, None, None, P, seg_actual=2)
    assert sel == [2] and seg is app.no_update


def test_caja_en_trpd_no_cambia_de_segmento(monkeypatch):
    monkeypatch.setattr(app, "_cap_p", lambda p, ed=None: _cap())
    monkeypatch.setattr(app, "_ed", lambda store, carpeta, canal: {"historial": []})
    caja = {"points": [{"curveNumber": 0, "customdata": [0, 0, 0, 0, 0, k]} for k in (0, 3)]}
    monkeypatch.setattr(app, "ctx", _Ctx("grafico_scatter.selectedData"))
    sel, seg = set_seleccion(P, caja, None, None, None, P, seg_actual=1)
    assert sel == [0, 3] and seg is app.no_update


def _sinteticos(monkeypatch):
    t = np.linspace(-5, 30, 3501)
    v = np.zeros_like(t)
    monkeypatch.setattr(app, "canales_presentes", lambda carpeta: ["ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "cargar_segmento", lambda carpeta, canal, seg, **k: (t, v))
    monkeypatch.setattr(app, "meta_medicion",
                        lambda carpeta: {ch: {"xinc": 1e-8} for ch in ("ch2", "ch3", "ch4")})


CFG = {ch: {"umbral": 10.0, "dist": 0.035, "tmin": 0.15} for ch in ("ch2", "ch3", "ch4")}


def test_figura_resalta_peak_seleccionado(monkeypatch):
    _sinteticos(monkeypatch)
    fig = figura("mock", 2, "ch4", cfg_sensores=CFG, cap=_cap(), seleccion=[1])
    assert [d.name for d in fig.data[:3]] == ["ch2", "ch3", "ch4"]     # índices de señal intactos
    sel = [d for d in fig.data if d.name == "seleccionado"]
    assert len(sel) == 1 and list(sel[0].x) == [2.0]
    assert any("peak 1 de 2" in (a.text or "") for a in fig.layout.annotations)
    # Seleccionado en otro segmento: nada que resaltar aquí
    assert not [d for d in figura("mock", 3, "ch4", cfg_sensores=CFG, cap=_cap(), seleccion=[1]).data
                if d.name == "seleccionado"]


def test_manuales_visibles_en_vista_previa(monkeypatch):
    """Con parámetros cambiados sin recalcular, el peak manual sigue dibujado."""
    _sinteticos(monkeypatch)
    fig = figura("mock", 2, "ch4", cfg_sensores=CFG, cap=_cap(), vista_previa=True)
    man = [d for d in fig.data if d.name == "peaks manuales"]
    assert len(man) == 1 and list(man[0].x) == [3.0]
