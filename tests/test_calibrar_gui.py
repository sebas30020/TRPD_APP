"""Tests unitarios y de integración para la interfaz y callbacks de calibrar_app."""

from __future__ import annotations
import os
import sys
import pytest
from dash import no_update
import plotly.graph_objects as go

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

from interfaz import layout
from main import (
    actualizar_label_segmento,
    actualizar_grafico_canal,
    actualizar_grafico_impulso,
    evaluar_conformidad_iec,
    actualizar_tabla_resumen,
    actualizar_panel_iec,
    guardar_en_metadata,
    sincronizar_umbral,
    sincronizar_triggers,
    calcular_retardo_canal,
    actualizar_grafico_dispersion,
)
import datos

# Medición de prueba: ruta absoluta a una carpeta con ch1..ch4.h5 (no hay carpeta de datos fija).
CARPETA_TEST = os.environ.get("TRPD_CARPETA_TEST", "")


def test_layout_componentes_requeridos():
    """Verifica que el árbol del layout contenga todos los IDs de control y gráficos obligatorios."""
    meds = [CARPETA_TEST]
    lay = layout(meds, CARPETA_TEST)
    assert lay is not None

    ids_esperados = {
        "resultado_store", "iec_store", "carpeta", "canal", "referencia",
        "fuente_calibracion", "label_segmento", "segmento", "ucal", "dtcal",
        "tmincal", "btn_calcular", "btn_evaluar_iec", "btn_guardar",
        "msg_feedback", "grafico_canal", "grafico_impulso", "grafico_dispersion",
        "grafico_ancla", "tabla_resumen", "panel_iec_resumen",
    }

    # Búsqueda recursiva de ids
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

    _buscar_ids(lay)
    faltantes = ids_esperados - ids_encontrados
    assert not faltantes, f"Faltan IDs en el layout: {faltantes}"


def test_callback_label_segmento():
    assert actualizar_label_segmento(1) == "Disparo 1"
    assert actualizar_label_segmento(50) == "Disparo 50"


def test_callback_grafico_canal():
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    fig = actualizar_grafico_canal(
        carpeta=CARPETA_TEST,
        canal="ch4",
        seg=1,
        ucal=50.0,
        dtcal=0.035,
        tmincal=0.15,
        ref="t10",
    )
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1  # Traza de la señal + marca arribo si cruza


def test_callback_grafico_impulso():
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    fig = actualizar_grafico_impulso(carpeta=CARPETA_TEST, seg=1)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1  # Al menos u0 y trazas de ajuste


def test_callback_evaluar_iec():
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    res = evaluar_conformidad_iec(1, CARPETA_TEST)
    assert "resumen_iec" in res and "delta" in res
    assert res["resumen_iec"]["n_total"] == 50
    assert 0.18 <= res["delta"]["media_us"] <= 0.34


def test_callback_tabla_resumen():
    store_ejemplo = {
        "ch4": {
            "t_lag_us": 0.0152,
            "sigma_us": 0.0008,
            "n_valid": 50,
            "n_total": 50,
            "params": {"umbral_mv": 50.0, "distancia_us": 0.035, "tmin_us": 0.15},
        }
    }
    tabla = actualizar_tabla_resumen(store_ejemplo, CARPETA_TEST)
    assert tabla is not None


def test_callback_panel_iec():
    store_iec = {
        "resumen_iec": {"T1_medio_us": 1.21, "T2_medio_us": 49.8, "beta_medio_pct": 0.8, "conforme": True, "fuera_tolerancia": 0},
        "delta": {"media_us": 0.258, "sigma_us": 0.003},
    }
    panel = actualizar_panel_iec(store_iec)
    assert panel is not None


def test_sincronizar_umbral_zoom_no_resetea():
    """Al recibir relayoutData de zoom (sin shapes), debe retornar no_update para no reiniciar la vista."""
    relayout_zoom = {"xaxis.range[0]": 2.5, "xaxis.range[1]": 8.0}
    res = sincronizar_umbral(relayout_zoom, CARPETA_TEST, "ch4", 25.0)
    assert res == no_update


def test_sincronizar_umbral_arrastre_shape():
    """Al arrastrar una forma (shape.y0/y1), debe actualizar el valor de ucal."""
    relayout_drag = {"shapes[0].y0": 42.8, "shapes[0].y1": 42.8}
    res = sincronizar_umbral(relayout_drag, CARPETA_TEST, "ch4", 25.0)
    assert res == 42.8


def test_calcular_retardo_todos_canales():
    """Al seleccionar canal='todos', calcula el retardo de CH2, CH3 y CH4 simultáneamente."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    res = calcular_retardo_canal(1, CARPETA_TEST, "todos", None, 0.035, 0.15, "t10", {})
    assert "ch2" in res
    assert "ch3" in res
    assert "ch4" in res
    assert res["_referencia"] == "t10"


def test_multicanal_figura_canal_layout():
    """Verifica que figura_canal configure uirevision y trazas para todos los canales presentes."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    fig = actualizar_grafico_canal(CARPETA_TEST, "ch4", 1, 30.0, 0.035, 0.15, "t10")
    assert isinstance(fig, go.Figure)
    assert fig.layout.uirevision == CARPETA_TEST
    # Debe contener subplots con trazas de CH1 y sensores
    assert len(fig.data) >= 4


def test_multicanal_figura_canal_lineas_umbral_editables():
    """Verifica que figura_canal dibuje las líneas horizontales de umbral como shapes editables."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    fig = actualizar_grafico_canal(
        CARPETA_TEST, "todos", 1, None, 0.035, 0.15, "t10",
        u2=150.0, tmin2=0.15, u3=120.0, tmin3=0.15, u4=90.0, tmin4=0.15
    )
    # Debe haber al menos 3 shapes de umbral (CH2, CH3, CH4)
    assert len(fig.layout.shapes) >= 3
    # Los primeros 3 shapes deben ser las líneas horizontales de trigger de CH2, CH3, CH4
    s0, s1, s2 = fig.layout.shapes[0], fig.layout.shapes[1], fig.layout.shapes[2]
    assert s0.y0 == 150.0 and s0.y1 == 150.0 and getattr(s0, "editable", False) is True
    assert s1.y0 == 120.0 and s1.y1 == 120.0 and getattr(s1, "editable", False) is True
    assert s2.y0 == 90.0 and s2.y1 == 90.0 and getattr(s2, "editable", False) is True


def test_sincronizar_triggers_cambio_canal_no_resetea():
    """Al alternar entre canales, ningún trigger establecido debe ser sobrescrito."""
    # Simular que el usuario ya tenía configurado CH2 a 120 mV y CH3 a 85 mV
    # y ahora cambia el selector de canal a 'ch3'
    # No hay relayoutData de gráfico
    res = sincronizar_triggers(
        relayout=None,
        carpeta=CARPETA_TEST,
        canal="ch3",
        u2=120.0,
        tmin2=0.18,
        u3=85.0,
        tmin3=0.15,
        u4=45.0,
        tmin4=0.12,
        ucal_act=120.0,
    )
    # Debe retornar no_update para los valores de u2, tmin2, u3, tmin3, u4, tmin4
    # garantizando que ninguno se pierda al seleccionar otro canal
    u2_out, t2_out, u3_out, t3_out, u4_out, t4_out, ucal_out = res
    assert u2_out == no_update
    assert t2_out == no_update
    assert u3_out == no_update
    assert t3_out == no_update
    assert u4_out == no_update
    assert t4_out == no_update


def test_sincronizar_triggers_arrastre_shape_especifico():
    """Al mover la línea de umbral de un canal específico (ej. CH3), solo ese canal se actualiza."""
    # shapes[0] = ch2, shapes[1] = ch3, shapes[2] = ch4
    relayout_ch3 = {"shapes[1].y0": 92.5, "shapes[1].y1": 92.5}
    res = sincronizar_triggers(
        relayout=relayout_ch3,
        carpeta=CARPETA_TEST,
        canal="ch3",
        u2=120.0,
        tmin2=0.18,
        u3=85.0,
        tmin3=0.15,
        u4=45.0,
        tmin4=0.12,
        ucal_act=85.0,
    )
    u2_out, t2_out, u3_out, t3_out, u4_out, t4_out, ucal_out = res
    assert u2_out == no_update  # CH2 intacto
    assert u3_out == 92.5       # CH3 actualizado al nuevo valor arrastrado
    assert u4_out == no_update  # CH4 intacto


def test_calcular_retardo_multi_trigger_independiente():
    """Al calcular retardo en modo 'todos', cada canal procesa su propio umbral y t_min."""
    if not datos.canales_presentes(CARPETA_TEST):
        pytest.skip("TRPD_CARPETA_TEST no definida o sin datos")

    res = calcular_retardo_canal(
        n_clicks=1,
        carpeta=CARPETA_TEST,
        canal="todos",
        ucal=None,
        dtcal=0.035,
        tmincal=0.15,
        ref="t10",
        store_actual={},
        u2=500.0,
        tmin2=0.14,
        u3=400.0,
        tmin3=0.15,
        u4=300.0,
        tmin4=0.16,
    )
    assert res["ch2"]["params"]["umbral_mv"] == 500.0
    assert res["ch2"]["params"]["tmin_us"] == 0.14
    assert res["ch3"]["params"]["umbral_mv"] == 400.0
    assert res["ch3"]["params"]["tmin_us"] == 0.15
    assert res["ch4"]["params"]["umbral_mv"] == 300.0
    assert res["ch4"]["params"]["tmin_us"] == 0.16


def test_callback_grafico_dispersion_selector_canal():
    """Verifica que el gráfico de dispersión responda al selector de canal mostrando su sensor correspondiente."""
    store_ejemplo = {
        "ch2": {
            "canal": "ch2",
            "segs": [1, 2],
            "t_lag": [0.010, 0.011],
            "valido": [True, True],
            "atipico": [False, False],
            "t_lag_us": 0.0105,
            "sigma_us": 0.0005,
            "n_valid": 2,
            "n_total": 2,
        },
        "ch3": {
            "canal": "ch3",
            "segs": [1, 2],
            "t_lag": [0.020, 0.021],
            "valido": [True, True],
            "atipico": [False, False],
            "t_lag_us": 0.0205,
            "sigma_us": 0.0005,
            "n_valid": 2,
            "n_total": 2,
        },
    }
    fig2 = actualizar_grafico_dispersion(store_ejemplo, canal="ch2")
    assert isinstance(fig2, go.Figure)
    assert "CH2" in fig2.layout.annotations[0].text or "HFCT" in fig2.layout.annotations[0].text

    fig3 = actualizar_grafico_dispersion(store_ejemplo, canal="ch3")
    assert isinstance(fig3, go.Figure)
    assert "CH3" in fig3.layout.annotations[0].text or "Vivaldi" in fig3.layout.annotations[0].text



