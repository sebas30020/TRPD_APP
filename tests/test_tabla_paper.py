"""Tabla de estadística con el formato de la Tabla 1 del paper."""

import numpy as np
from dash import html

import app

CARPETA = "M/3v_2mm3mm4mm_1/11kV"


def _cap_sintetica():
    # 4 segmentos con cuentas [3, 3, 2, 0]: descargas 0-2 en seg 1, 3-5 en seg 2, 6-7 en seg 3
    seg = np.array([1, 1, 1, 2, 2, 2, 3, 3])
    vpp = np.array([100, 200, 300, 400, 500, 600, 9000, 9000], dtype=float)  # mV
    t_peak = np.array([1, 2, 3, 4, 5, 6, 90, 90], dtype=float)                # µs
    return {"t_peak": t_peak, "v_peak": vpp / 2, "vpp": vpp, "seg": seg,
            "t10_seg": np.zeros(8)}


def _parchear(monkeypatch, cap, meta):
    monkeypatch.setattr(app, "capturar", lambda *a, **k: cap)
    monkeypatch.setattr(app, "n_segmentos", lambda carpeta: 4)
    monkeypatch.setattr(app, "obtener_metadata", lambda carpeta: meta)


META_VIEJA = {"probeta": {"codigo": "3v_2mm3mm4mm_1", "nro_vacuolas": 3},
              "canales": {"ch3": {"sensor": "Antena Vivaldi"}}}


def test_fila_promedios_condicionados(monkeypatch):
    _parchear(monkeypatch, _cap_sintetica(), META_VIEJA)
    f = app.calcular_fila_densidad(CARPETA, "ch3", 1.0, 1.0, 0.0)
    assert f["specimen"] == "3v"
    assert f["diametro"] == "2, 3, 4"
    assert f["voltage"] == "11"
    assert f["sensor"] == "Antena 1"
    assert f["distribucion"] == "[1, 0, 1, 2, 0, 0]"
    assert f["n_coinc"] == "2"
    # Solo los segmentos 1 y 2 (3 peaks): media vpp = 350 mV, t_abs = 3.5 µs
    assert f["vpp_media"] == "0.350"
    assert f["tabs_media"] == "3.500"


def test_fila_sin_coincidencias(monkeypatch):
    cap = _cap_sintetica()
    meta = {"probeta": {"nro_vacuolas": 4}, "canales": {}}
    _parchear(monkeypatch, cap, meta)
    f = app.calcular_fila_densidad(CARPETA, "ch2", 1.0, 1.0, 0.0)
    assert f["n_coinc"] == "0"
    assert f["vpp_media"] == "-" and f["tabs_media"] == "-"
    assert f["sensor"] == "HFCT"


def test_fila_respeta_excluidos(monkeypatch):
    _parchear(monkeypatch, _cap_sintetica(), META_VIEJA)
    app._CAPTURA_EDITADA_CACHE.clear()
    # Quitar la descarga de t = 4 µs del seg 2 -> ese disparo pasa a 2 peaks
    ed = {"historial": [{"accion": "quitar", "puntos": [{"seg": 2, "t_us": 4.0}]}]}
    f = app.calcular_fila_densidad(CARPETA, "ch3", 1.0, 1.0, 0.0, ediciones=ed)
    assert f["n_coinc"] == "1"
    assert f["vpp_media"] == "0.200"


def _contar(comp, tipo):
    n = 1 if isinstance(comp, tipo) else 0
    hijos = getattr(comp, "children", None)
    if isinstance(hijos, list):
        n += sum(_contar(h, tipo) for h in hijos)
    elif hijos is not None and not isinstance(hijos, str):
        n += _contar(hijos, tipo)
    return n


def _buscar(comp, pred, out):
    if pred(comp):
        out.append(comp)
    hijos = getattr(comp, "children", None)
    for h in (hijos if isinstance(hijos, list) else [hijos]):
        if h is not None and not isinstance(h, str):
            _buscar(h, pred, out)
    return out


def test_construir_tabla_paper_agrupa_por_medicion():
    filas = []
    for carpeta, n, v in [("b/11kV", 3, 11.0), ("a/17.5kV", 1, 17.5)]:
        for ch in ["ch4", "ch2", "ch3"]:
            filas.append({"specimen": f"{n}v", "diametro": "2", "voltage": f"{v:g}",
                          "sensor": ch, "distribucion": "[0, 0, 0, 0, 0, 0]", "n_coinc": "0",
                          "vpp_media": "-", "tabs_media": "-",
                          "_carpeta": carpeta, "_canal": ch, "_n_cav": n, "_voltage_kv": v})
    cont = app.construir_tabla_paper(filas)
    tabla = _buscar(cont, lambda c: isinstance(c, html.Table), [])[0]
    assert _contar(tabla, html.Th) == 8
    con_span = _buscar(tabla, lambda c: isinstance(c, html.Td) and getattr(c, "rowSpan", None) == 3, [])
    assert len(con_span) == 6                       # specimen, d, voltage × 2 grupos
    specimens = [c.children for c in _buscar(tabla, lambda c: getattr(c, "className", None) == "tp-specimen", [])]
    assert specimens == ["1v", "3v"]                # ordenado por nº de cavidades
    assert _contar(tabla, html.Tr) == 1 + 6


def test_tabla_vacia_y_csv():
    assert not _buscar(app.construir_tabla_paper([]), lambda c: isinstance(c, html.Table), [])
    csv = app.csv_tabla_densidad([{"specimen": "1v", "_carpeta": "x"}])
    cab = csv.splitlines()[0]
    assert cab.startswith("Specimen,d (mm),Voltage (kV),Sensor")
    assert "_carpeta" not in csv


def test_nota_filtros():
    filas = [{"sensor": "HFCT", "_canal": "ch2", "_filtrado": True, "_filtro": "HP 5 MHz"},
             {"sensor": "Antena 2", "_canal": "ch4", "_filtrado": True, "_filtro": "HP 200 MHz"}]
    nota = app.nota_filtros_tabla(filas)
    assert "HFCT: HP 5 MHz" in nota and "Antena 2: HP 200 MHz" in nota
    assert app.nota_filtros_tabla([dict(f, _filtrado=False) for f in filas]) == "Señal sin filtrar."
    assert "mezcla" in app.nota_filtros_tabla([filas[0], dict(filas[1], _filtrado=False)])
