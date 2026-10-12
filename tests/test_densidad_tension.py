"""Pruebas unitarias para la distribución de N_PD y la gráfica de densidad vs tensión."""

from __future__ import annotations
import csv
import os
import sys
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import generar_reporte4


def test_distribucion_npd():
    assert generar_reporte4.distribucion_npd([0, 0, 1, 3, 5, 7]) == [2, 1, 0, 1, 0, 2]
    assert generar_reporte4.distribucion_npd([]) == [0, 0, 0, 0, 0, 0]
    assert generar_reporte4.distribucion_npd([1, 2, 4]) == [0, 1, 1, 0, 1, 0]


def test_grafica_densidad_tension(tmp_path):
    descs = [
        {"probeta": "p", "kv": 11.0, "kv_txt": "11", "nsegs": 3, "excluidos": [], "carpeta": "<inexistente>"},
        {"probeta": "p", "kv": 12.0, "kv_txt": "12", "nsegs": 3, "excluidos": [], "carpeta": "<inexistente>"},
    ]
    todos = [
        {
            "ch2": {"segs": [1, 2, 3], "cuentas": [0, 1, 1], "fila": {"sensor": "HFCT"}},
            "ch3": {"segs": [1, 2, 3], "cuentas": [1, 1, 2], "fila": {"sensor": "Antena 1"}},
        },
        {
            "ch2": {"segs": [1, 2, 3], "cuentas": [2, 2, 3], "fila": {"sensor": "HFCT"}},
            "ch3": {"segs": [1, 2, 3], "cuentas": [3, 3, 3], "fila": {"sensor": "Antena 1"}},
        },
    ]

    generar_reporte4.grafica_densidad_tension(str(tmp_path), descs, todos)

    png_path = tmp_path / "densidad_vs_tension.png"
    csv_path = tmp_path / "densidad_vs_tension.csv"

    assert png_path.exists()
    assert png_path.stat().st_size > 0
    assert csv_path.exists()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert len(reader) == 5  # encabezado + 4 filas (2 niveles x 2 canales)
    header = reader[0]
    assert header == [
        "Probeta", "Voltage (kV)", "Sensor", "Disparos",
        "N_PD=0", "N_PD=1", "N_PD=2", "N_PD=3", "N_PD=4", "N_PD>4",
        "f_0", "f_1", "f_2", "f_3", "f_4", "f_>4"
    ]

    for row in reader[1:]:
        assert row[0] == "p"
        disparos = int(row[3])
        assert disparos == 3
        conteos = [int(x) for x in row[4:10]]
        assert sum(conteos) == disparos
        fracs = [float(x) for x in row[10:16]]
        assert pytest.approx(sum(fracs), abs=1e-2) == 1.0


def test_grafica_densidad_tension_con_ncav(tmp_path, monkeypatch):
    monkeypatch.setattr(generar_reporte4, "n_cavidades", lambda c: 3)
    descs = [
        {"probeta": "p1", "kv": 11.0, "kv_txt": "11", "nsegs": 2, "excluidos": [], "carpeta": "dummy"},
        {"probeta": "p2", "kv": 11.0, "kv_txt": "11", "nsegs": 2, "excluidos": [], "carpeta": "dummy"},
    ]
    todos = [
        {"ch2": {"segs": [1, 2], "cuentas": [3, 3], "fila": {"sensor": "HFCT"}}},
        {"ch2": {"segs": [1, 2], "cuentas": [3, 3], "fila": {"sensor": "HFCT"}}},
    ]

    generar_reporte4.grafica_densidad_tension(str(tmp_path), descs, todos)

    assert (tmp_path / "densidad_vs_tension_p1.png").exists()
    assert (tmp_path / "densidad_vs_tension_p1.csv").exists()
    assert (tmp_path / "densidad_vs_tension_p2.png").exists()
    assert (tmp_path / "densidad_vs_tension_p2.csv").exists()


def test_grafica_npd_media(tmp_path):
    descs = [{"probeta": "p", "kv": kv, "kv_txt": f"{kv:g}", "nsegs": 3, "excluidos": [], "carpeta": "<inexistente>"}
             for kv in (11.0, 12.0)]
    todos = [{"ch3": {"segs": [1, 2, 3], "cuentas": [0, 1, 2], "fila": {"sensor": "Antena 1"}}},
             {"ch3": {"segs": [1, 2, 3], "cuentas": [3, 3, 3], "fila": {"sensor": "Antena 1"}}}]
    generar_reporte4.grafica_npd_media(str(tmp_path), descs, todos)
    assert (tmp_path / "npd_media_vs_tension.png").exists()
    with open(tmp_path / "npd_media_vs_tension.csv", encoding="utf-8") as f:
        filas = list(csv.reader(f))[1:]
    assert [(r[1], r[4]) for r in filas] == [("11", "1.000"), ("12", "3.000")]
