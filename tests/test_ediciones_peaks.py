"""Edición manual de peaks: las ediciones se guardan como (disparo, t) y se reaplican
igual al cambiar el trigger (umbral, Δt, t_mín)."""

from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pytest
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, "..")))

import app  # noqa: E402

DT_US = 1e-4                       # 10 GSa/s
T = np.arange(-1.0, 2.0 + DT_US / 2, DT_US)
PULSOS = {                          # seg -> [(t_us, amplitud mV)]
    1: [(0.5, 100.0), (1.0, 40.0), (1.9995, 80.0)],
    2: [(0.8, 100.0)],
    3: [],
}
_ids = itertools.count()


def _senal(seg):
    v = np.zeros_like(T)
    for t0, a in PULSOS[seg]:
        v += a * np.exp(-0.5 * ((T - t0) / 0.001) ** 2)   # sigma = 1 ns
    return v


@pytest.fixture
def sintetico(monkeypatch):
    """Medición sintética de 3 disparos; devuelve un nombre de carpeta único (las
    cachés de captura van por carpeta)."""
    monkeypatch.setattr(app, "cargar_segmento", lambda c, ch, s, *a, **k: (T, _senal(int(s))))
    monkeypatch.setattr(app, "n_segmentos", lambda c: 3)
    monkeypatch.setattr(app, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "meta_medicion", lambda c: {ch: {"xinc": DT_US * 1e-6} for ch in app.TRIGGERS})
    monkeypatch.setattr(app, "t10_por_segmento", lambda c: np.zeros(3))
    return f"sintetico_{next(_ids)}"


def _cuentas(carpeta, umbral, ed=None):
    return app.contar_peaks(carpeta, "ch4", umbral, 0.05, -1.0, ediciones=ed, filtrado=False)[1]


def _hist(*pasos):
    return {"historial": list(pasos)}


def quitar(seg, t):
    return {"accion": "quitar", "puntos": [{"seg": seg, "t_us": t}]}


def anadir(seg, t):
    return {"accion": "anadir", "puntos": [{"seg": seg, "t_us": t}]}


def test_estado_ediciones_replay_y_cancelacion():
    est = app.estado_ediciones(_hist(anadir(1, 1.0), quitar(1, 1.0), quitar(2, 0.8),
                                     anadir(2, 0.8002), {"accion": "quitar_disparo", "segs": [3]}))
    assert est["anadidos"] == [(2, 0.8002)]          # añadir sobre un quitado lo recupera
    assert est["quitados"] == [(1, 1.0)]             # quitar un añadido lo deja quitado
    assert est["disparos"] == {3}
    assert app.estado_ediciones(None) == {"anadidos": [], "quitados": [], "disparos": set()}


def test_sin_ediciones_igual_que_la_deteccion(sintetico):
    # El pulso en 1.9995 µs no cabe en la ventana de 70 ns: nunca se cuenta.
    assert _cuentas(sintetico, 30) == [2, 1, 0]
    assert _cuentas(sintetico, 50) == [1, 1, 0]
    assert _cuentas(sintetico, 30, _hist()) == [2, 1, 0]


def test_quitado_sobrevive_a_otro_umbral(sintetico):
    ed = _hist(quitar(1, 0.5))
    assert _cuentas(sintetico, 30, ed) == [1, 1, 0]
    # Con umbral 50 el índice del peak de 0.5 µs cambia, pero sigue quitado.
    assert _cuentas(sintetico, 50, ed) == [0, 1, 0]
    cap = app.captura_editada(sintetico, "ch4", 50, 0.05, -1.0, filtrado=False, ediciones=ed)
    assert [(s, round(t, 4)) for s, t, _ in cap["quitados_vis"]] == [(1, 0.5)]


def test_anadido_bajo_umbral_cuenta_y_tiene_vpp_de_su_ventana(sintetico):
    ed = _hist(anadir(1, 1.0003))          # fuera del máximo: se reajusta en ±1 ns
    assert _cuentas(sintetico, 50, ed) == [2, 1, 0]
    cap = app.captura_editada(sintetico, "ch4", 50, 0.05, -1.0, filtrado=False, ediciones=ed)
    i = int(np.nonzero(cap["origen"] == 1)[0][0])
    assert cap["seg"][i] == 1 and abs(cap["t_peak"][i] - 1.0) < 1e-9
    assert cap["v_peak"][i] == pytest.approx(40.0, rel=1e-6)
    assert cap["vpp"][i] == pytest.approx(np.ptp(cap["W"][i]))
    assert cap["W"].shape[0] == cap["t_peak"].size
    assert list(cap["seg"]) == sorted(cap["seg"])   # ordenada por (seg, t)


def test_anadido_sobre_detectado_no_duplica_y_queda_forzado(sintetico):
    ed = _hist(anadir(1, 1.0))
    assert _cuentas(sintetico, 30, ed) == [2, 1, 0]
    cap = app.captura_editada(sintetico, "ch4", 30, 0.05, -1.0, filtrado=False, ediciones=ed)
    assert int(np.sum(cap["origen"] == 1)) == 1
    assert _cuentas(sintetico, 50, ed) == [2, 1, 0]   # el trigger ya no lo detecta, sigue


def test_anadido_sin_ventana_completa_se_omite(sintetico):
    ed = _hist(anadir(1, 1.9995))
    cap = app.captura_editada(sintetico, "ch4", 50, 0.05, -1.0, filtrado=False, ediciones=ed)
    assert cap["omitidos"] == 1
    assert _cuentas(sintetico, 50, ed) == [1, 1, 0]


def test_quitar_disparo_con_cualquier_trigger(sintetico):
    ed = _hist({"accion": "quitar_disparo", "segs": [1]}, anadir(1, 1.0))
    assert _cuentas(sintetico, 30, ed) == [0, 1, 0]
    assert _cuentas(sintetico, 50, ed) == [0, 1, 0]


def test_ajustar_a_peak(sintetico):
    t, v = app.ajustar_a_peak(sintetico, "ch4", 2, 0.795, filtrado=False)   # ±10 ns
    assert abs(t - 0.8) < 1e-9 and v == pytest.approx(100.0)
    assert app.ajustar_a_peak(sintetico, "ch4", 2, 5.0, filtrado=False) is None


def test_persistencia_en_metadata(tmp_path, monkeypatch):
    (tmp_path / "metadata.yaml").write_text(
        "experimento:\n  id: prueba\nprobeta:\n  nro_vacuolas: 3\n", encoding="utf-8")
    carpeta = str(tmp_path)
    monkeypatch.setattr(app, "_dir_medicion", lambda c: carpeta)
    assert app.ediciones_canal(carpeta, "ch4") == {"historial": []}

    ed = _hist(quitar(1, 0.5), anadir(2, 1.25))
    ok, msg = app.guardar_ediciones_canal(carpeta, "ch4", ed)
    assert ok, msg
    disco = yaml.safe_load((tmp_path / "metadata.yaml").read_text(encoding="utf-8"))
    assert disco["experimento"] == {"id": "prueba"} and disco["probeta"] == {"nro_vacuolas": 3}
    assert disco["ediciones_peaks"]["ch4"]["historial"] == ed["historial"]
    assert app.ediciones_canal(carpeta, "ch4") == ed
    assert app.ediciones_medicion(carpeta)["ch2"] == {"historial": []}

    ok, _ = app.guardar_ediciones_canal(carpeta, "ch4", {"historial": []})
    assert ok
    disco = yaml.safe_load((tmp_path / "metadata.yaml").read_text(encoding="utf-8"))
    assert "ediciones_peaks" not in disco
