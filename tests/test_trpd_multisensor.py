"""Tests del mapa TRPD conjunto («Calcular todos los sensores»): captura con la
configuración de cada trigger, superposición en el scatter, selección por sensor,
quitar peaks falsos en varios sensores y deshacer como una sola acción."""

from __future__ import annotations
import os
import sys
import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from app import (actualizar_badge_filtro, figura_scatter, fijar_captura, gestionar_ediciones_peaks,
                 set_seleccion, set_seleccion_otros, _idx_otros)

CFG = {"ch2": {"umbral": 5.0, "dist": 0.035, "tmin": 0.15},
       "ch3": {"umbral": 6.0, "dist": 0.035, "tmin": 0.15},
       "ch4": {"umbral": 7.0, "dist": 0.035, "tmin": 0.15}}
P = {"carpeta": "mock", "canal": "ch4", "umbral": 7.0, "dist": 0.035, "tmin": 0.15,
     "filtrado": False, "multi": CFG}


class _Ctx:
    def __init__(self, prop_id):
        self.triggered = [{"prop_id": prop_id}]
        self.triggered_id = prop_id.split(".")[0]


@pytest.fixture(autouse=True)
def _mock(monkeypatch):
    app._CAPTURA_EDITADA_CACHE.clear()
    monkeypatch.setattr(app, "canales_presentes", lambda carpeta: ["ch1", "ch2", "ch3", "ch4"])
    n_por_canal = {"ch2": 3, "ch3": 2, "ch4": 4}

    def capturar(carpeta, canal, *a, **k):
        n = n_por_canal[canal]
        return {"seg": np.ones(n, dtype=int), "t_peak": np.round(np.arange(n) * 0.1 + 0.1, 6),
                "v_peak": np.full(n, 10.0 * int(canal[-1])), "vpp": np.full(n, 20.0)}
    monkeypatch.setattr(app, "capturar", capturar)
    # «mock» no es una medición real: que fijar_captura no escriba metadata.yaml
    monkeypatch.setattr(app, "guardar_trigger_canales", lambda *a, **k: (True, "ok"))
    yield
    app._CAPTURA_EDITADA_CACHE.clear()


def _hist(store, canal):
    return ((store.get("canales") or {}).get(canal) or {}).get("historial", [])


def test_boton_calcula_todos_los_triggers(monkeypatch):
    monkeypatch.setattr(app, "_cfg_sensores", lambda *a, **k: {ch: dict(c) for ch, c in CFG.items()})
    monkeypatch.setattr(app, "ctx", _Ctx("btn_multi.n_clicks"))
    p = fijar_captura(0, "mock", "ch4", *[None] * 9, ("on",), "mock", "ch4", 1, None)
    assert p["canal"] == "ch4" and p["umbral"] == 7.0
    assert p["multi"] == CFG
    # «Calcular peaks» (un solo canal) apaga el mapa conjunto
    monkeypatch.setattr(app, "ctx", _Ctx("btn.n_clicks"))
    assert "multi" not in fijar_captura(1, "mock", "ch4", *[None] * 9, ("on",), "mock", "ch4", 1, p)


def test_cambiar_trigger_activo_conserva_el_mapa():
    app_ctx = app.ctx
    try:
        app.ctx = _Ctx("canal.value")
        p = fijar_captura(0, "mock", "ch2", *[None] * 9, ("on",), "mock", "ch2", 1, P)
        assert p["canal"] == "ch2" and p["umbral"] == 5.0 and p["multi"] == CFG
        # Sin mapa conjunto, cambiar de canal invalida la captura (como antes)
        assert fijar_captura(1, "mock", "ch2", *[None] * 9, ("on",), "mock", "ch2", 1,
                             {k: v for k, v in P.items() if k != "multi"}) is None
    finally:
        app.ctx = app_ctx


def test_scatter_superpone_sensores():
    caps = {ch: app._cap_sensor(P, ch, {}) for ch in ("ch2", "ch3", "ch4")}
    otros = [{"canal": ch, "cap": caps[ch], "t_abs": None, "sel": [1] if ch == "ch2" else []}
             for ch in ("ch2", "ch3")]
    fig = figura_scatter(caps["ch4"], None, None, "ch4", highlight=[0], otros=otros)
    assert [d.name for d in fig.data[:3]] == ["Vmax CH4", "Vmax CH2", "Vmax CH3"]
    assert fig.data[0].marker.color != fig.data[1].marker.color
    assert int(fig.data[1].customdata[0][6]) == 2 and int(fig.data[0].customdata[0][6]) == 4
    sel = [d for d in fig.data if d.name == "sel"][0]
    assert len(sel.x) == 2          # uno del activo + uno de CH2


def test_seleccion_por_sensor(monkeypatch):
    caja = {"points": [
        {"curveNumber": 0, "customdata": [0, 0, 0, 1, 0, 2, 4]},
        {"curveNumber": 1, "customdata": [0, 0, 0, 1, 0, 0, 2]},
        {"curveNumber": 1, "customdata": [0, 0, 0, 1, 0, 2, 2]},
        {"curveNumber": 2, "customdata": [0, 0, 0, 1, 0, 1, 3]},
    ]}
    assert _idx_otros(caja, ["ch2", "ch3"]) == {"ch2": [0, 2], "ch3": [1]}
    monkeypatch.setattr(app, "ctx", _Ctx("grafico_scatter.selectedData"))
    sel_o, _ = set_seleccion_otros(P, caja, None, None, None, P, seg_actual=1)
    assert sel_o == {"ch2": [0, 2], "ch3": [1]}
    sel, _ = set_seleccion(P, caja, None, None, None, P, seg_actual=1)
    assert sel == [2]
    # Caja solo sobre otros sensores: la selección del activo se vacía
    solo_otros = {"points": caja["points"][1:]}
    assert set_seleccion(P, solo_otros, None, None, None, P, seg_actual=1)[0] == []


def test_quitar_en_varios_sensores_y_deshacer(monkeypatch):
    guardados = []
    monkeypatch.setattr(app, "guardar_ediciones_canal",
                        lambda c, ch, ed: (guardados.append(ch), (True, "ok"))[1])
    monkeypatch.setattr(app, "ctx", _Ctx("btn_excluir_seleccion.n_clicks"))
    store = {"carpeta": "mock", "canales": {}}
    st, _, aviso = gestionar_ediciones_peaks(*[1] * 9, sel=[0], val_disparo="", store=store, p=P,
                                             marca=None, sel_otros={"ch2": [1, 2], "ch3": [0]})
    assert aviso.startswith("✓ 4 peaks quitados") and "CH2: 2" in aviso
    h2, h3, h4 = _hist(st, "ch2"), _hist(st, "ch3"), _hist(st, "ch4")
    assert [p["t_us"] for p in h2[0]["puntos"]] == [0.2, 0.3] and len(h3) == len(h4) == 1
    assert h2[0]["grupo"] == h3[0]["grupo"] == h4[0]["grupo"]
    assert sorted(guardados) == ["ch2", "ch3", "ch4"]
    assert app._cap_sensor(P, "ch2", st)["t_peak"].size == 1

    # Badge: cuenta la selección de todos los sensores y muestra activas por sensor
    r = actualizar_badge_filtro(sel=[0], store=st, p=P, sel_otros={"ch2": [0]})
    assert r[1] == "Quitar 2 seleccionadas" and "CH2: 1 (2 quit.)" in r[4]

    # Deshacer revierte la acción en los tres sensores
    monkeypatch.setattr(app, "ctx", _Ctx("btn_deshacer_exclusion.n_clicks"))
    st2, _, aviso = gestionar_ediciones_peaks(*[1] * 9, sel=[], val_disparo="", store=st, p=P, marca=None)
    assert aviso.startswith("✓ Deshecho")
    assert _hist(st2, "ch2") == _hist(st2, "ch3") == _hist(st2, "ch4") == []


def test_quitar_solo_en_otro_sensor(monkeypatch):
    monkeypatch.setattr(app, "guardar_ediciones_canal", lambda c, ch, ed: (True, "ok"))
    monkeypatch.setattr(app, "ctx", _Ctx("btn_excluir_seleccion.n_clicks"))
    st, _, aviso = gestionar_ediciones_peaks(*[1] * 9, sel=[], val_disparo="",
                                             store={"carpeta": "mock", "canales": {}}, p=P,
                                             marca=None, sel_otros={"ch3": [1]})
    assert aviso.startswith("✓ 1 peak quitado (CH3: 1)")
    assert len(_hist(st, "ch3")) == 1 and _hist(st, "ch4") == []


def _senal_con_peaks(monkeypatch, t_peaks):
    t = np.linspace(-5, 30, 3501)
    v = np.zeros_like(t)
    for tp in t_peaks:
        v[int(np.argmin(np.abs(t - tp)))] = 50.0
    monkeypatch.setattr(app, "canales_presentes", lambda carpeta: ["ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "cargar_segmento", lambda carpeta, canal, seg, **k: (t, v))
    monkeypatch.setattr(app, "meta_medicion",
                        lambda carpeta: {ch: {"xinc": 1e-8} for ch in ("ch2", "ch3", "ch4")})
    return [float(t[int(np.argmin(np.abs(t - tp)))]) for tp in t_peaks]


def test_senales_muestran_cruces_de_todos_los_triggers(monkeypatch):
    """Sin mapa conjunto: los demás triggers marcan sus peaks en vivo, sin los quitados."""
    t1, t2 = _senal_con_peaks(monkeypatch, [2.0, 5.0])
    cfg = {ch: {"umbral": 10.0, "dist": 0.035, "tmin": 0.15} for ch in ("ch2", "ch3", "ch4")}
    ed = {"ch3": {"historial": [{"accion": "quitar", "puntos": [{"seg": 1, "t_us": t2}]}]}}
    fig = app.figura("mock", 1, "ch4", cfg_sensores=cfg, ediciones_otros=ed)
    cruces = {d.name: [float(x) for x in d.x] for d in fig.data if d.name and d.name.startswith("peaks ")}
    assert cruces == {"peaks CH2": [t1, t2], "peaks CH3": [t1], "peaks CH4": [t1, t2]}


def test_senales_mapa_conjunto_y_clic_en_cruz_de_otro_sensor(monkeypatch):
    _senal_con_peaks(monkeypatch, [2.0, 5.0])
    cap2 = {"seg": np.array([1, 1]), "t_peak": np.array([2.0, 5.0]), "v_peak": np.array([50.0, 50.0]),
            "origen": np.array([0, 0]), "quitados_vis": [(1, 7.0, 40.0)]}
    cfg = {ch: {"umbral": 10.0, "dist": 0.035, "tmin": 0.15} for ch in ("ch2", "ch3", "ch4")}
    fig = app.figura("mock", 1, "ch4", cfg_sensores=cfg, caps_otros={"ch2": cap2},
                     seleccion_otros={"ch2": [1]})
    c2 = [d for d in fig.data if d.name == "peaks CH2"][0]
    assert [list(c) for c in c2.customdata] == [[0, 2], [1, 2]]
    assert [d for d in fig.data if d.name == "quitados CH2"]
    assert [d for d in fig.data if d.name == "seleccionado CH2"]
    assert any(a.name == "badge_ediciones" and "CH2" in a.text for a in fig.layout.annotations)
    # Clic en esa cruz: selección del otro sensor, no del activo
    clic = {"points": [{"curveNumber": 5, "x": 5.0, "customdata": [1, 2]}]}
    assert app._idx_cruces(clic, 10) is None
    monkeypatch.setattr(app, "ctx", _Ctx("grafico.clickData"))
    assert set_seleccion_otros(None, None, None, clic, None, P)[0] == {"ch2": [1]}
    assert set_seleccion(None, None, None, clic, None, P)[0] == []


def test_clic_webgl_sin_customdata_lleva_al_segmento(monkeypatch):
    """El clic sobre Scattergl no trae customdata: curva k -> otros[k-1], índice = pointNumber,
    y el gráfico de señales salta al segmento de esa descarga."""
    def capturar(carpeta, canal, *a, **k):
        return {"seg": np.array([1, 4, 7]), "t_peak": np.array([0.1, 0.2, 0.3]),
                "v_peak": np.full(3, 10.0), "vpp": np.full(3, 20.0)}
    monkeypatch.setattr(app, "capturar", capturar)
    clic = {"points": [{"curveNumber": 2, "pointNumber": 2, "pointIndex": 2, "x": 0.3, "y": 10.0}]}
    assert _idx_otros(clic, ["ch2", "ch3"]) == {"ch3": [2]}
    assert _idx_otros({"points": [{"curveNumber": 3, "pointNumber": 0}]}, ["ch2", "ch3"]) == {}  # CH1
    monkeypatch.setattr(app, "ctx", _Ctx("grafico_scatter.clickData"))
    assert set_seleccion_otros(P, None, clic, None, {}, P, seg_actual=1) == ({"ch3": [2]}, 7)
    assert set_seleccion_otros(P, None, clic, None, {}, P, seg_actual=7) == ({"ch3": [2]}, app.no_update)
    assert set_seleccion(P, None, clic, None, {}, P, seg_actual=1)[0] == []


def test_impulso_ch1_escalado_al_maximo_de_todos_los_sensores():
    """La cresta de la curva CH1 coincide con el mayor Vmax (o Vpp) entre todos los sensores."""
    caps = {ch: app._cap_sensor(P, ch, {}) for ch in ("ch2", "ch3", "ch4")}   # Vmax 20, 30, 40
    t_ref = np.linspace(-1, 5, 200)
    v_ref = np.exp(-((t_ref - 1.0) ** 2)) * 1800.0
    otros = [{"canal": ch, "cap": caps[ch], "t_abs": None, "sel": []} for ch in ("ch3", "ch4")]

    def cresta(fig):
        return max(float(y) for y in [d for d in fig.data if d.name.startswith("CH1 promedio")][0].y)

    assert cresta(figura_scatter(caps["ch2"], t_ref, v_ref, "ch2", otros=otros)) == pytest.approx(40.0)
    assert cresta(figura_scatter(caps["ch2"], t_ref, v_ref, "ch2")) == pytest.approx(20.0)
    assert cresta(figura_scatter(caps["ch2"], t_ref, v_ref, "ch2", modo="vpp", otros=otros)) == pytest.approx(20.0)
