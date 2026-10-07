"""Tests de la exclusión de descargas en el TRPD (lazo, por disparo, deshacer y
restaurar). Las exclusiones son pasos del historial de ediciones de peaks
(metadata.yaml: ediciones_peaks), guardados como (disparo, t) y no como índices."""

from __future__ import annotations
import os
import sys
import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from app import (
    calcular_fila_densidad,
    figura_scatter,
    _idx_scatter,
    gestionar_ediciones_peaks,
    actualizar_badge_filtro,
    parsear_lista_disparos,
    contar_peaks,
    calcular_peaks,
)

# Medición de prueba: ruta absoluta a una carpeta con ch1..ch4.h5 (no hay carpeta de datos fija).
CARPETA_TEST = os.environ.get("TRPD_CARPETA_TEST", "")


@pytest.fixture(autouse=True)
def _sin_cache_editada():
    """Los tests sustituyen capturar() con capturas distintas bajo la misma carpeta 'mock'."""
    app._CAPTURA_EDITADA_CACHE.clear()
    yield
    app._CAPTURA_EDITADA_CACHE.clear()


def _cap_mock(segs):
    segs = np.asarray(segs, dtype=int)
    n = segs.size
    return {"seg": segs, "t_peak": np.round(np.arange(n) * 0.1 + 0.1, 6), "v_peak": np.full(n, 100.0),
            "vpp": np.full(n, 150.0)}


def _hist(store, carpeta, canal):
    if (store or {}).get("carpeta") != carpeta:
        return []
    return ((store.get("canales") or {}).get(canal) or {}).get("historial", [])


def test_layout_elementos_filtro_presentes():
    """Componentes de exclusión (TRPD) y de edición manual de peaks en app.layout."""
    ids_encontrados = set()

    def _buscar_ids(componente):
        if hasattr(componente, "id") and componente.id:
            ids_encontrados.add(componente.id)
        if hasattr(componente, "children"):
            hijos = componente.children
            if isinstance(hijos, list):
                for h in hijos:
                    _buscar_ids(h)
            elif hijos is not None:
                _buscar_ids(hijos)

    _buscar_ids(app.app.layout)
    for i in ("ediciones_peaks", "marca_peak", "btn_excluir_seleccion", "btn_deshacer_exclusion",
              "btn_restaurar_descargas", "input_excluir_disparo", "btn_excluir_disparo",
              "badge_filtro_descargas", "input_marca_t", "btn_anadir_peak", "btn_quitar_peak",
              "btn_deshacer_edicion", "btn_restaurar_ediciones", "badge_ediciones", "aviso_ediciones"):
        assert i in ids_encontrados, i
    assert "descargas_excluidas" not in ids_encontrados   # ya no se guarda por índice


def test_parsear_lista_disparos():
    """Verifica el parser robusto de disparos e impulsos manuales."""
    assert parsear_lista_disparos(None) == []
    assert parsear_lista_disparos("") == []
    assert parsear_lista_disparos(5) == [5]
    assert parsear_lista_disparos("5") == [5]
    assert parsear_lista_disparos("1, 3, 5") == [1, 3, 5]
    assert parsear_lista_disparos("2-5") == [2, 3, 4, 5]
    assert parsear_lista_disparos("1, 3-5, 8") == [1, 3, 4, 5, 8]
    assert parsear_lista_disparos("1; 4; 7") == [1, 4, 7]
    assert parsear_lista_disparos("1-10", n_max_segs=5) == [1, 2, 3, 4, 5]


def test_contar_peaks_unitario(monkeypatch):
    """contar_peaks aplica las ediciones (quitar por tiempo y por disparo)."""
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: _cap_mock([1, 1, 2, 2, 3, 3]))
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 3)

    segs, cuentas = contar_peaks("mock", "ch3", 10.0, 1.0, 0.0, ediciones=None)
    assert segs == [1, 2, 3]
    assert cuentas == [2, 2, 2]

    # Quitar los dos peaks del disparo 1 (t = 0.1 y 0.2 µs)
    ed = {"historial": [{"accion": "quitar", "puntos": [{"seg": 1, "t_us": 0.1}, {"seg": 1, "t_us": 0.2}]}]}
    assert contar_peaks("mock", "ch3", 10.0, 1.0, 0.0, ediciones=ed)[1] == [0, 2, 2]
    ed = {"historial": [{"accion": "quitar_disparo", "segs": [2]}]}
    assert contar_peaks("mock", "ch3", 10.0, 1.0, 0.0, ediciones=ed)[1] == [2, 0, 2]


def test_figura_scatter_captura_editada():
    """La curva 0 son todos los peaks de la captura editada, con el índice en customdata[5]
    y rombos para los manuales (origen 1)."""
    cap = {
        "t_peak": np.array([1.0, 2.0, 3.0]),
        "v_peak": np.array([100.0, 200.0, 300.0]),
        "vpp": np.array([120.0, 220.0, 320.0]),
        "seg": np.array([1, 1, 2]),
        "origen": np.array([0, 1, 0]),
    }
    t_abs = np.array([0.5, 1.5, 2.5])
    fig = figura_scatter(cap, None, None, "ch3", t_abs=t_abs)
    np.testing.assert_array_almost_equal(fig.data[0].x, [0.5, 1.5, 2.5])
    np.testing.assert_array_equal(fig.data[0].customdata[:, 5].astype(int), [0, 1, 2])
    assert list(fig.data[0].marker.symbol) == ["circle", "diamond", "circle"]

    sin_manual = figura_scatter({k: v for k, v in cap.items() if k != "origen"}, None, None, "ch3")
    assert sin_manual.data[0].marker.symbol == "circle"


def test_figura_scatter_highlight():
    cap = {
        "t_peak": np.array([1.0, 2.0, 3.0]),
        "v_peak": np.array([100.0, 200.0, 300.0]),
        "vpp": np.array([120.0, 220.0, 320.0]),
        "seg": np.array([1, 1, 2]),
    }
    fig = figura_scatter(cap, None, None, "ch4", highlight=[0, 7])
    trazas_sel = [t for t in fig.data if t.name == "sel"]
    assert len(trazas_sel) == 1
    assert list(trazas_sel[0].y) == [100.0]


def test_idx_scatter_mapeo_activos_y_customdata():
    """Verifica que _idx_scatter mapee adecuadamente a los índices globales originales."""
    datos_cd = {
        "points": [
            {"curveNumber": 0, "pointNumber": 0, "customdata": [100, 120, 1.0, 1, 500.0, 3]}
        ]
    }
    assert _idx_scatter(datos_cd, 10, activos=[3, 7]) == [3]

    datos_pt = {
        "points": [
            {"curveNumber": 0, "pointNumber": 1, "customdata": [100, 120]}
        ]
    }
    assert _idx_scatter(datos_pt, 10, activos=[2, 5, 8]) == [5]


class _Ctx:
    def __init__(self, trig_id):
        self.triggered_id = trig_id
        self.triggered = [{"prop_id": f"{trig_id}.n_clicks"}]


def test_gestionar_ediciones_flujo_completo(monkeypatch):
    """Lazo, exclusión de disparo, deshacer paso a paso y restaurar: cada acción es un
    paso del historial en tiempo, y se guarda en metadata.yaml."""
    p = {"carpeta": "mock", "canal": "ch4", "umbral": 10.0, "dist": 1.0, "tmin": 0.0, "filtrado": False}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: _cap_mock([1, 1, 2, 2, 3, 3]))
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 3)
    guardados = []

    def guardar(c, ch, ed):
        guardados.append((c, ch, ed))
        return True, "ok"
    monkeypatch.setattr(app, "guardar_ediciones_canal", guardar)

    def accion(trig, store, sel=(), disparo=""):
        monkeypatch.setattr(app, "ctx", _Ctx(trig))
        return gestionar_ediciones_peaks(1, 1, 1, 1, 1, 1, 1, 1, 1, sel=list(sel), val_disparo=disparo,
                                         store=store, p=p, marca=None)

    # 1. Lazo sobre los índices 0 y 1 -> (seg 1, 0.1 µs) y (seg 1, 0.2 µs)
    st1, _, aviso = accion("btn_excluir_seleccion", {"carpeta": "mock", "canales": {}}, sel=[0, 1])
    h = _hist(st1, "mock", "ch4")
    assert aviso.startswith("✓") and len(h) == 1 and h[0]["accion"] == "quitar"
    assert h[0]["puntos"] == [{"seg": 1, "t_us": 0.1}, {"seg": 1, "t_us": 0.2}]
    assert contar_peaks("mock", "ch4", 10.0, 1.0, 0.0, ediciones={"historial": h})[1] == [0, 2, 2]
    assert guardados[-1][:2] == ("mock", "ch4")

    # 2. Excluir el disparo 3 (el input se limpia)
    st2, inp, _ = accion("btn_excluir_disparo", st1, disparo="3")
    h2 = _hist(st2, "mock", "ch4")
    assert inp == "" and len(h2) == 2
    assert h2[1] == {"accion": "quitar_disparo", "segs": [3], "desc": "Disparo(s) [3]"}
    assert contar_peaks("mock", "ch4", 10.0, 1.0, 0.0, ediciones={"historial": h2})[1] == [0, 2, 0]

    # 3-4. Deshacer dos veces (botón del TRPD y de la barra de señales: son equivalentes)
    st3, _, _ = accion("btn_deshacer_exclusion", st2)
    assert len(_hist(st3, "mock", "ch4")) == 1
    st4, _, _ = accion("btn_deshacer_edicion", st3)
    assert _hist(st4, "mock", "ch4") == []

    # 5. Restaurar todo
    st5, _, _ = accion("btn_restaurar_descargas", st2)
    assert _hist(st5, "mock", "ch4") == []

    # Sin selección ni marca, "Quitar peak" avisa y no cambia nada
    st6, _, aviso = accion("btn_quitar_peak", st1)
    assert st6 is app.no_update and aviso


def test_gestionar_ediciones_anadir_y_quitar_con_marca(monkeypatch):
    p = {"carpeta": "mock", "canal": "ch4", "umbral": 10.0, "dist": 1.0, "tmin": 0.0, "filtrado": False}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: _cap_mock([1, 2]))
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 2)
    monkeypatch.setattr(app, "guardar_ediciones_canal", lambda c, ch, ed: (True, "ok"))
    store = {"carpeta": "mock", "canales": {}}

    # Quitar con la marca cerca del peak de seg 2 (t = 0.2 µs)
    monkeypatch.setattr(app, "ctx", _Ctx("btn_quitar_peak"))
    marca = {"carpeta": "mock", "canal": "ch4", "seg": 2, "t_us": 0.2004}
    st, _, _ = gestionar_ediciones_peaks(*[1] * 9, sel=[], val_disparo="", store=store, p=p, marca=marca)
    assert _hist(st, "mock", "ch4")[0]["puntos"] == [{"seg": 2, "t_us": 0.2}]

    # Añadir sin marca: aviso
    monkeypatch.setattr(app, "ctx", _Ctx("btn_anadir_peak"))
    st2, _, aviso = gestionar_ediciones_peaks(*[1] * 9, sel=[], val_disparo="", store=store, p=p, marca=None)
    assert st2 is app.no_update and "marca" in aviso


def test_actualizar_badge_filtro_callback(monkeypatch):
    """Badge y botones según selección, marca y ediciones."""
    p = {"carpeta": "mock", "canal": "ch3", "umbral": 15.0, "dist": 1.0, "tmin": 0.0}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: _cap_mock([1] * 5 + [2] * 5))

    r = actualizar_badge_filtro(sel=[], store={}, p=p)
    dis_excl, txt_excl, dis_undo, dis_res, badge, dis_add, dis_quit, dis_undo2, dis_res2, badge_ed = r
    assert dis_excl and dis_undo and dis_res and dis_add and dis_quit and dis_undo2 and dis_res2
    assert badge == "10 descargas activas"
    assert badge_ed == "Sin ediciones manuales"

    r = actualizar_badge_filtro(sel=[2, 4], store={}, p=p,
                                marca={"carpeta": "mock", "canal": "ch3", "seg": 1, "t_us": 0.5})
    assert r[0] is False and r[1] == "Quitar 2 seleccionadas"
    assert r[5] is False and r[6] is False          # añadir (hay marca) y quitar (hay selección)

    store = {"carpeta": "mock", "canales": {"ch3": {"historial": [
        {"accion": "quitar", "puntos": [{"seg": 1, "t_us": 0.1}, {"seg": 1, "t_us": 0.2}]},
        {"accion": "quitar_disparo", "segs": [2]},
    ]}}}
    r = actualizar_badge_filtro(sel=[], store=store, p=p)
    assert r[2] is False and r[3] is False
    assert r[4] == "3 descargas activas (7 quitadas)"
    assert r[9] == "0 añadidos · 7 quitados · 1 disparo excluido"


def test_calcular_peaks_callback(monkeypatch):
    """calcular_peaks responde a las ediciones del canal."""
    p = {"carpeta": "mock", "canal": "ch3", "umbral": 10.0, "dist": 1.0, "tmin": 0.0}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: _cap_mock([1, 1, 2, 2]))
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 2)

    np.testing.assert_array_equal(calcular_peaks(p, store={}).data[0].y, [2, 2])
    store = {"carpeta": "mock", "canales": {"ch3": {"historial": [{"accion": "quitar_disparo", "segs": [1]}]}}}
    np.testing.assert_array_equal(calcular_peaks(p, store=store).data[0].y, [0, 2])


def test_calcular_fila_densidad_con_y_sin_exclusiones():
    """calcular_fila_densidad refleja numéricamente un peak quitado."""
    if not app.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")
    carpeta = CARPETA_TEST
    canal = "ch3"
    umbral = 15.0
    dist = 1.0
    tmin = 0.0

    fila_base = calcular_fila_densidad(carpeta, canal, umbral, dist, tmin, t_lag_us=0.0, ediciones=None)
    assert fila_base["specimen"] != ""
    # La tabla (formato Tabla 1) usa V̄_pp y promedios condicionados a N_PD = N_cav
    assert "vpp_media" in fila_base and "n_coinc" in fila_base

    # Quitar el primer peak (por tiempo): un peak menos en la distribución
    cap = app.capturar(carpeta, canal, umbral, dist, tmin)
    ed = None
    if cap["t_peak"].size:
        ed = {"historial": [{"accion": "quitar", "puntos": [
            {"seg": int(cap["seg"][0]), "t_us": float(cap["t_peak"][0])}]}]}
    fila_exc = calcular_fila_densidad(carpeta, canal, umbral, dist, tmin, t_lag_us=0.0, ediciones=ed)
    assert fila_exc["id"] == fila_base["id"]
    n_segs = app.n_segmentos(carpeta)
    for fila in (fila_base, fila_exc):
        assert sum(int(x) for x in fila["distribucion"].strip("[]").split(",")) == n_segs
    tot_base = sum(app.contar_peaks(carpeta, canal, umbral, dist, tmin)[1])
    tot_exc = sum(app.contar_peaks(carpeta, canal, umbral, dist, tmin, ediciones=ed)[1])
    if tot_base:
        assert tot_exc == tot_base - 1
