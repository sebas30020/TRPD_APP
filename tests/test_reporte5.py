"""Pruebas unitarias para generar_reporte5.py (lectura de Libro1.xlsx, estadística V_pp y gráficas vs tensión)."""

from __future__ import annotations

import csv
import os
import sys
import zipfile

import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import generar_reporte5 as g5  # noqa: E402


def _crear_xlsx_sintetico(ruta_xlsx):
    shared_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">
  <si><t>ch2</t></si>
  <si><t>ch3</t></si>
  <si><t>ch4</t></si>
  <si><t>mv</t></si>
  <si><t>deltat</t></si>
  <si><t>tmin</t></si>
</sst>"""
    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="7">
      <c r="D7" t="s"><v>0</v></c>
      <c r="G7" t="s"><v>1</v></c>
      <c r="J7" t="s"><v>2</v></c>
    </row>
    <row r="9">
      <c r="C9"><v>16</v></c>
      <c r="D9"><v>200</v></c><c r="E9"><v>0.03</v></c><c r="F9"><v>0.65</v></c>
      <c r="G9"><v>600</v></c><c r="H9"><v>0.03</v></c><c r="I9"><v>0.3</v></c>
      <c r="J9"><v>600</v></c><c r="K9"><v>0.03</v></c><c r="L9"><v>0.3</v></c>
    </row>
    <row r="10">
      <c r="C10"><v>17</v></c>
      <c r="D10"><v>160</v></c><c r="E10"><v>0.03</v></c><c r="F10"><v>0.6</v></c>
      <c r="G10"><v>650</v></c><c r="H10"><v>0.03</v></c><c r="I10"><v>0.3</v></c>
      <c r="J10"><v>650</v></c><c r="K10"><v>0.03</v></c><c r="L10"><v>0.3</v></c>
    </row>
  </sheetData>
</worksheet>"""
    with zipfile.ZipFile(ruta_xlsx, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def test_leer_triggers_xlsx_sintetico(tmp_path):
    ruta = tmp_path / "Libro1.xlsx"
    _crear_xlsx_sintetico(str(ruta))
    tr = g5.leer_triggers_xlsx(str(ruta))
    assert sorted(tr.keys()) == [16, 17]
    assert tr[16]["ch2"] == {"umbral": 200.0, "dist": 0.03, "tmin": 0.65}
    assert tr[16]["ch3"] == {"umbral": 600.0, "dist": 0.03, "tmin": 0.3}
    assert tr[17]["ch2"] == {"umbral": 160.0, "dist": 0.03, "tmin": 0.6}
    assert tr[17]["ch4"] == {"umbral": 650.0, "dist": 0.03, "tmin": 0.3}


@pytest.mark.skipif(not os.path.isfile(g5.RUTA_XLSX_DEFECTO), reason="Libro1.xlsx real no disponible")
def test_leer_triggers_xlsx_real():
    tr = g5.leer_triggers_xlsx(g5.RUTA_XLSX_DEFECTO)
    assert sorted(tr.keys()) == [16, 17, 18, 19, 20]
    assert tr[16]["ch2"] == {"umbral": 200.0, "dist": 0.03, "tmin": 0.65}
    assert tr[17]["ch2"] == {"umbral": 160.0, "dist": 0.03, "tmin": 0.6}
    assert tr[18]["ch2"] == {"umbral": 185.0, "dist": 0.03, "tmin": 0.7}
    assert tr[19]["ch2"] == {"umbral": 185.0, "dist": 0.03, "tmin": 0.65}
    assert tr[20]["ch2"] == {"umbral": 185.0, "dist": 0.03, "tmin": 0.7}


def test_medias_vpp_y_graficas(tmp_path, monkeypatch):
    monkeypatch.setattr(g5.g4, "n_cavidades", lambda c: 1)
    res_16 = {
        "ch2": {
            "segs": [1, 2, 3],
            "cuentas": [0, 1, 1],
            "cap": {"vpp": np.array([400.0, 600.0]), "seg": np.array([2, 3])},
            "t_abs": np.array([4.0, 4.4]),
            "fila": {"sensor": "HFCT", "voltage": "16"},
            "cfg": {"umbral": 200.0, "dist": 0.03, "tmin": 0.65},
        },
        "ch3": {
            "segs": [1, 2, 3],
            "cuentas": [0, 1, 1],
            "cap": {"vpp": np.array([2000.0, 2400.0]), "seg": np.array([2, 3])},
            "t_abs": np.array([4.0, 4.4]),
            "fila": {"sensor": "Antena 1", "voltage": "16"},
            "cfg": {"umbral": 600.0, "dist": 0.03, "tmin": 0.3},
        },
    }
    res_17 = {
        "ch2": {
            "segs": [1, 2, 3],
            "cuentas": [1, 1, 2],
            "cap": {"vpp": np.array([500.0, 700.0, 800.0, 800.0]), "seg": np.array([1, 2, 3, 3])},
            "t_abs": np.array([3.5, 3.7, 3.9, 4.1]),
            "fila": {"sensor": "HFCT", "voltage": "17"},
            "cfg": {"umbral": 160.0, "dist": 0.03, "tmin": 0.6},
        },
        "ch3": {
            "segs": [1, 2, 3],
            "cuentas": [1, 1, 1],
            "cap": {"vpp": np.array([2100.0, 2300.0, 2500.0]), "seg": np.array([1, 2, 3])},
            "t_abs": np.array([3.5, 3.7, 3.9]),
            "fila": {"sensor": "Antena 1", "voltage": "17"},
            "cfg": {"umbral": 650.0, "dist": 0.03, "tmin": 0.3},
        },
    }

    g5.medias_vpp("1v_4mm_1/16kV", res_16)
    g5.medias_vpp("1v_4mm_1/17kV", res_17)

    assert res_16["ch2"]["fila"]["vpp_media"] == "0.500"
    assert res_16["ch2"]["fila"]["vpp_media_cav"] == "0.500"
    assert res_16["ch2"]["fila"]["tabs_media_cav"] == "4.200"
    assert res_17["ch2"]["fila"]["vpp_media"] == "0.700"
    assert res_17["ch2"]["fila"]["vpp_media_cav"] == "0.600"

    descs = [
        {"probeta": "1v_4mm_1", "kv": 16.0, "kv_txt": "16", "nsegs": 3, "excluidos": [], "carpeta": "1v_4mm_1/16kV"},
        {"probeta": "1v_4mm_1", "kv": 17.0, "kv_txt": "17", "nsegs": 3, "excluidos": [], "carpeta": "1v_4mm_1/17kV"},
    ]
    todos = [res_16, res_17]

    g5.graficas_tension(str(tmp_path), descs, todos)
    g5.grafica_cociente_vpp(str(tmp_path), descs, todos)

    assert (tmp_path / "vpp_vs_tension.png").exists()
    assert (tmp_path / "vpp_vs_tension.csv").exists()
    assert (tmp_path / "tabs_vs_tension.png").exists()
    assert (tmp_path / "tabs_vs_tension.csv").exists()
    assert (tmp_path / "vpp_cociente_tension.png").exists()
    assert (tmp_path / "vpp_cociente_tension.csv").exists()

    with open(tmp_path / "vpp_vs_tension.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Probeta", "Conjunto", "Voltage (kV)", "Sensor", "Descargas", "V̄_pp (V)", "σ V_pp (V)"]
