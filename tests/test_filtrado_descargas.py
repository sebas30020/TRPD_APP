"""Tests unitarios para la herramienta de filtrado y exclusión de descargas en TRPD."""

from __future__ import annotations
import os
import sys
import numpy as np
import pytest
from dash import no_update
import plotly.graph_objects as go

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from app import (
    calcular_fila_densidad,
    figura_scatter,
    _idx_scatter,
    gestionar_exclusiones_descargas,
    actualizar_badge_filtro,
    parsear_lista_disparos,
    contar_peaks,
    calcular_peaks,
    _obtener_excluidos,
    _obtener_historial,
)

CARPETA_TEST = "mediciones_filtros/cada_30s/7"


def test_layout_elementos_filtro_presentes():
    """Verifica que los componentes de filtrado, deshacer y exclusión manual existan en app.layout."""
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
    assert "descargas_excluidas" in ids_encontrados
    assert "btn_excluir_seleccion" in ids_encontrados
    assert "btn_deshacer_exclusion" in ids_encontrados
    assert "btn_restaurar_descargas" in ids_encontrados
    assert "input_excluir_disparo" in ids_encontrados
    assert "btn_excluir_disparo" in ids_encontrados
    assert "badge_filtro_descargas" in ids_encontrados


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
    """Verifica que contar_peaks excluya adecuadamente los índices señalados."""
    cap_mock = {
        "seg": np.array([1, 1, 2, 2, 3, 3]),
    }
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: cap_mock)
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 3)

    # Sin exclusiones: segmento 1 tiene 2, seg 2 tiene 2, seg 3 tiene 2
    segs, cuentas = contar_peaks("mock", "ch3", 10.0, 1.0, 0.0, excluidos=None)
    assert segs == [1, 2, 3]
    assert cuentas == [2, 2, 2]

    # Excluyendo índices 0 y 1 (ambos del segmento 1): seg 1 queda en 0
    segs, cuentas_exc = contar_peaks("mock", "ch3", 10.0, 1.0, 0.0, excluidos=[0, 1])
    assert cuentas_exc == [0, 2, 2]


def test_figura_scatter_exclusion_puntos():
    """Verifica que figura_scatter omita los puntos excluidos de la curva 0 y guarde el índice global."""
    cap = {
        "t_peak": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        "v_peak": np.array([100.0, 200.0, 300.0, 400.0, 500.0]),
        "vpp": np.array([120.0, 220.0, 320.0, 420.0, 520.0]),
        "seg": np.array([1, 1, 2, 2, 3]),
    }
    t_abs = np.array([0.5, 1.5, 2.5, 3.5, 4.5])

    # Sin exclusiones
    fig_todas = figura_scatter(cap, None, None, "ch3", t_abs=t_abs, excluidos=None)
    assert len(fig_todas.data[0].x) == 5

    # Con exclusión de los índices 1 y 3 (segundo y cuarto punto)
    fig_filtrada = figura_scatter(cap, None, None, "ch3", t_abs=t_abs, excluidos=[1, 3])
    assert len(fig_filtrada.data[0].x) == 3

    # Los puntos restantes deben ser los índices globales 0, 2 y 4
    np.testing.assert_array_almost_equal(fig_filtrada.data[0].x, [0.5, 2.5, 4.5])
    np.testing.assert_array_almost_equal(fig_filtrada.data[0].y, [100.0, 300.0, 500.0])

    # Columna 5 de customdata debe preservar los índices globales originales [0, 2, 4]
    cd = fig_filtrada.data[0].customdata
    assert cd is not None
    indices_globales = cd[:, 5].astype(int)
    np.testing.assert_array_equal(indices_globales, [0, 2, 4])


def test_figura_scatter_highlight_omite_excluidos():
    """Verifica que los puntos resaltados en amarillo solo incluyan descargas activas."""
    cap = {
        "t_peak": np.array([1.0, 2.0, 3.0]),
        "v_peak": np.array([100.0, 200.0, 300.0]),
        "vpp": np.array([120.0, 220.0, 320.0]),
        "seg": np.array([1, 1, 2]),
    }
    fig = figura_scatter(cap, None, None, "ch4", highlight=[0, 1], excluidos=[1])
    trazas_sel = [t for t in fig.data if t.name == "sel"]
    assert len(trazas_sel) == 1
    assert len(trazas_sel[0].x) == 1
    assert trazas_sel[0].y[0] == 100.0


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


def test_gestionar_exclusiones_descargas_flujo_completo(monkeypatch):
    """Verifica el flujo completo: lazo, exclusión manual de disparo, deshacer y restaurar todo."""
    p = {"carpeta": "mock", "canal": "ch4", "umbral": 10.0, "dist": 1.0, "tmin": 0.0}
    key = "mock|ch4"

    cap_mock = {
        "seg": np.array([1, 1, 2, 2, 3, 3]),
        "t_peak": np.zeros(6),
    }
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: cap_mock)
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 3)

    class MockCtx:
        def __init__(self, trig_id):
            self.triggered_id = trig_id

    # 1. Exclusión por lazo (índices 0 y 1)
    monkeypatch.setattr(app, "ctx", MockCtx("btn_excluir_seleccion"))
    dict1, inp1 = gestionar_exclusiones_descargas(1, 0, 0, 0, 0, sel=[0, 1], val_disparo="", excl_dict={}, p=p)
    assert _obtener_excluidos(dict1, key) == [0, 1]
    assert len(_obtener_historial(dict1, key)) == 1
    assert _obtener_historial(dict1, key)[0]["tipo"] == "lazo"

    # 2. Exclusión manual del disparo 3 (índices 4 y 5)
    monkeypatch.setattr(app, "ctx", MockCtx("btn_excluir_disparo"))
    dict2, inp2 = gestionar_exclusiones_descargas(1, 0, 0, 1, 0, sel=[], val_disparo="3", excl_dict=dict1, p=p)
    assert inp2 == ""  # se limpia el input
    assert _obtener_excluidos(dict2, key) == [0, 1, 4, 5]
    assert len(_obtener_historial(dict2, key)) == 2
    assert _obtener_historial(dict2, key)[1]["tipo"] == "disparo"

    # 3. Retroceder última filtración (Deshacer disparo 3)
    monkeypatch.setattr(app, "ctx", MockCtx("btn_deshacer_exclusion"))
    dict3, _ = gestionar_exclusiones_descargas(1, 1, 0, 1, 0, sel=[], val_disparo="", excl_dict=dict2, p=p)
    assert _obtener_excluidos(dict3, key) == [0, 1]
    assert len(_obtener_historial(dict3, key)) == 1

    # 4. Retroceder otra vez (Deshacer lazo)
    dict4, _ = gestionar_exclusiones_descargas(1, 2, 0, 1, 0, sel=[], val_disparo="", excl_dict=dict3, p=p)
    assert _obtener_excluidos(dict4, key) == []
    assert len(_obtener_historial(dict4, key)) == 0

    # 5. Probar restaurar todo cuando hay exclusiones acumuladas
    dict_con_ambos = dict2
    monkeypatch.setattr(app, "ctx", MockCtx("btn_restaurar_descargas"))
    dict_reset, _ = gestionar_exclusiones_descargas(1, 2, 1, 1, 0, sel=[], val_disparo="", excl_dict=dict_con_ambos, p=p)
    assert _obtener_excluidos(dict_reset, key) == []
    assert len(_obtener_historial(dict_reset, key)) == 0


def test_actualizar_badge_filtro_callback(monkeypatch):
    """Verifica que el badge y los botones respondan adecuadamente al estado."""
    p = {"carpeta": "mock", "canal": "ch3", "umbral": 15.0, "dist": 1.0, "tmin": 0.0}
    cap_mock = {"t_peak": np.zeros(10)}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: cap_mock)
    key = "mock|ch3"

    # Sin selección ni exclusiones
    dis_excl, txt_excl, dis_undo, dis_res, badge = actualizar_badge_filtro(sel=[], excl_dict={}, p=p)
    assert dis_excl is True
    assert dis_undo is True
    assert dis_res is True
    assert "10 descargas activas" in badge

    # Con 2 seleccionadas
    dis_excl, txt_excl, dis_undo, dis_res, badge = actualizar_badge_filtro(sel=[2, 4], excl_dict={}, p=p)
    assert dis_excl is False
    assert txt_excl == "🚫 Quitar 2 seleccionadas"

    # Con 3 exclusiones en 2 pasos
    excl_data = {
        key: {
            "excluidos": [0, 1, 2],
            "historial": [
                {"tipo": "lazo", "indices": [0, 1]},
                {"tipo": "disparo", "indices": [2]},
            ],
        }
    }
    dis_excl, txt_excl, dis_undo, dis_res, badge = actualizar_badge_filtro(sel=[], excl_dict=excl_data, p=p)
    assert dis_undo is False
    assert dis_res is False
    assert "7/10 activas (3 excluidas en 2 pasos)" in badge


def test_calcular_peaks_callback(monkeypatch):
    """Verifica que calcular_peaks responda al input de descargas_excluidas."""
    p = {"carpeta": "mock", "canal": "ch3", "umbral": 10.0, "dist": 1.0, "tmin": 0.0}
    cap_mock = {"seg": np.array([1, 1, 2, 2])}
    monkeypatch.setattr(app, "capturar", lambda *args, **kwargs: cap_mock)
    monkeypatch.setattr(app, "n_segmentos", lambda *args: 2)

    # Sin exclusiones
    fig1 = calcular_peaks(p, excl_dict={})
    bar1 = fig1.data[0]
    np.testing.assert_array_equal(bar1.y, [2, 2])

    # Excluyendo índices 0 y 1
    key = "mock|ch3"
    excl_dict = {key: {"excluidos": [0, 1], "historial": []}}
    fig2 = calcular_peaks(p, excl_dict=excl_dict)
    bar2 = fig2.data[0]
    np.testing.assert_array_equal(bar2.y, [0, 2])


def test_calcular_fila_densidad_con_y_sin_exclusiones():
    """Verifica que calcular_fila_densidad refleje numéricamente las descargas excluidas."""
    carpeta = CARPETA_TEST
    canal = "ch3"
    umbral = 15.0
    dist = 1.0
    tmin = 0.0

    fila_base = calcular_fila_densidad(carpeta, canal, umbral, dist, tmin, t_lag_us=0.0, excluidos=None)
    assert fila_base["specimen"] != ""
    assert fila_base["vmax_media"] != "-"

    # Excluir el índice 0
    fila_exc = calcular_fila_densidad(carpeta, canal, umbral, dist, tmin, t_lag_us=0.0, excluidos=[0])
    assert fila_exc["id"] == fila_base["id"]
    assert fila_exc["vmax_media"] != "-"
