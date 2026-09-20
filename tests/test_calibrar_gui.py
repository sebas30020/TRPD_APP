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
)
import datos

CARPETA_TEST = "mediciones_filtros/cada_30s/7"


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
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

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
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

    fig = actualizar_grafico_impulso(carpeta=CARPETA_TEST, seg=1)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1  # Al menos u0 y trazas de ajuste


def test_callback_evaluar_iec():
    if not os.path.isdir(datos.MEDICIONES):
        pytest.skip("MEDICIONES no montado")

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
