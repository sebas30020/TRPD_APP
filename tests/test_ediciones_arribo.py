"""Edición manual de arribos en calibrar_app: fijar t_ant a mano o quitar un disparo
del promedio, con historial (deshacer) persistido en metadata.yaml."""

from __future__ import annotations
import os
import sys
import numpy as np
import yaml
import plotly.graph_objects as go
from dash import no_update

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import datos
import ediciones
import main
from figuras import figura_dispersion_lag


def _res(t_ant, ancla=None):
    """Resultado mínimo de calibrar_retardo con anclas en 0."""
    n = len(t_ant)
    ancla = ancla if ancla is not None else [0.0] * n
    t_lag = np.array([np.nan if t is None else t - a for t, a in zip(t_ant, ancla)])
    valido, atipico, media, sigma = ediciones.filtrar_mad(t_lag)
    return {"canal": "ch2", "segs": list(range(1, n + 1)), "t_ant": list(t_ant),
            "t_lag": [None if np.isnan(x) else float(x) for x in t_lag],
            "valido": valido.tolist(), "atipico": atipico.tolist(), "t_lag_us": media,
            "sigma_us": sigma, "n_valid": int(valido.sum()), "n_total": n, "ancla_us": list(ancla),
            "params": {"umbral_mv": 10.0, "distancia_us": 0.05, "tmin_us": -1.0}}


def test_estado_replay_fijar_y_quitar():
    ed = {"historial": [
        {"accion": "fijar", "seg": 2, "t_us": 0.1},
        {"accion": "quitar", "seg": 3},
        {"accion": "quitar", "seg": 2},     # quitar descarta el manual
        {"accion": "fijar", "seg": 3, "t_us": 0.2},   # fijar saca de quitados
    ]}
    est = ediciones.estado_ediciones(ed)
    assert est["manuales"] == {3: 0.2}
    assert est["quitados"] == {2}


def test_sin_ediciones_no_cambia_el_resultado():
    r = _res([0.10, 0.11, None, 0.12])
    out = ediciones.aplicar_ediciones(r, None)
    assert out["t_lag_us"] == r["t_lag_us"] and out["n_valid"] == r["n_valid"]
    assert out["origen"] == ["auto"] * 4 and out["n_manual"] == 0 and out["n_quitados"] == 0


def test_fijar_rellena_sin_cruce_y_quitar_saca_del_promedio():
    r = _res([0.10, 0.11, None, 0.50], ancla=[0.0, 0.0, 0.0, 0.0])
    n_valid_orig = r["n_valid"]
    ed ={"historial": [{"accion": "fijar", "seg": 3, "t_us": 0.12},
                        {"accion": "quitar", "seg": 4}]}
    out = ediciones.aplicar_ediciones(r, ed)
    assert out["origen"] == ["auto", "auto", "manual", "quitado"]
    assert out["t_ant"][2] == 0.12
    assert out["t_lag"][3] is None and out["valido"][3] is False
    assert out["n_valid"] == 3
    assert abs(out["t_lag_us"] - np.mean([0.10, 0.11, 0.12])) < 1e-12
    # el resultado original no se modifica
    assert r["t_ant"][2] is None and r["n_valid"] == n_valid_orig and r["t_lag"][3] == 0.5


def test_resultados_editados_solo_de_la_misma_medicion():
    store = {"_carpeta": "A", "ch2": _res([0.1, None])}
    ed = {"carpeta": "A", "canales": {"ch2": {"historial": [{"accion": "fijar", "seg": 2, "t_us": 0.3}]}}}
    assert main.resultados_editados(store, ed)["ch2"]["n_valid"] == 2
    ed_otra = dict(ed, carpeta="B")
    assert main.resultados_editados(store, ed_otra)["ch2"]["n_valid"] == 1


def test_dispersion_rombos_para_manuales():
    out = ediciones.aplicar_ediciones(_res([0.1, None, 0.11]),
                                      {"historial": [{"accion": "fijar", "seg": 2, "t_us": 0.105}]})
    fig = figura_dispersion_lag(out, canal="ch2")
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].marker.symbol) == ["circle", "diamond", "circle"]
    assert "1 manual" in fig.data[0].name


def test_bloque_metadata_registra_tmax():
    import generate_metadata
    r = _res([0.1, 0.11, 0.12])
    r["params"]["tmax_us"] = 0.5
    b = generate_metadata.bloque_calibracion_retardo({"ch2": r}, "test")
    assert b["ch2"]["tmax_us"] == 0.5
    r["params"]["tmax_us"] = None
    assert "tmax_us" not in generate_metadata.bloque_calibracion_retardo({"ch2": r}, "test")["ch2"]


def test_persistencia_y_callback(tmp_path, monkeypatch):
    (tmp_path / "metadata.yaml").write_text(yaml.safe_dump({"probeta": {"codigo": "X"}}), encoding="utf-8")
    carpeta = str(tmp_path)
    monkeypatch.setattr(datos, "_dir_medicion", lambda c: carpeta)
    monkeypatch.setattr(main, "ctx", type("C", (), {"triggered": [1], "triggered_id": "btn_fijar_arribo"})())

    marca = {"carpeta": carpeta, "canal": "ch3", "seg": 4, "t_us": -0.31234}
    store, msg = main.gestionar_ediciones_arribo(1, 0, 0, 0, carpeta, 4, "ch2", marca, None)
    assert msg.startswith("✓") and "CH3" in msg
    assert store["canales"]["ch3"]["historial"][-1] == {
        "accion": "fijar", "seg": 4, "t_us": -0.31234, "desc": "Arribo manual CH3 disparo 4"}
    disco = yaml.safe_load((tmp_path / "metadata.yaml").read_text(encoding="utf-8"))
    assert disco["probeta"] == {"codigo": "X"}
    assert disco["ediciones_arribo"]["ch3"]["historial"][0]["t_us"] == -0.31234
    assert ediciones.ediciones_canal(carpeta, "ch3")["historial"][0]["seg"] == 4

    # Deshacer deja el canal sin historial y borra la sección
    monkeypatch.setattr(main, "ctx", type("C", (), {"triggered": [1], "triggered_id": "btn_deshacer_arribo"})())
    store, msg = main.gestionar_ediciones_arribo(1, 0, 1, 0, carpeta, 4, "ch3", None, store)
    assert msg.startswith("✓ Deshecho") and store["canales"]["ch3"]["historial"] == []
    disco = yaml.safe_load((tmp_path / "metadata.yaml").read_text(encoding="utf-8"))
    assert "ediciones_arribo" not in disco


def test_marca_por_clic_en_senal_y_en_arribo(monkeypatch):
    monkeypatch.setattr(main, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    monkeypatch.setattr(main, "ctx", type("C", (), {"triggered": [1], "triggered_id": "grafico_canal"})())
    # curveNumber 2 → ch3 (trazas de señal en orden ch1..ch4)
    click = {"points": [{"curveNumber": 2, "x": -0.4123456789}]}
    marca, t, canal, aviso = main.fijar_marca_arribo(click, None, "ch2", "M", 5)
    assert marca == {"carpeta": "M", "canal": "ch3", "seg": 5, "t_us": -0.412346} and canal == "ch3"
    # Clic en CH1 → aviso, sin marca
    marca, *_, aviso = main.fijar_marca_arribo({"points": [{"curveNumber": 0, "x": 0.1}]}, None, "ch2", "M", 5)
    assert marca is no_update and "CH2–CH4" in aviso
    # Clic en el marcador de arribo: el canal viene en customdata
    marca, _, canal, _ = main.fijar_marca_arribo(
        {"points": [{"curveNumber": 7, "x": 0.2, "customdata": "ch4"}]}, None, "ch2", "M", 5)
    assert marca["canal"] == "ch4" and canal == "ch4"
