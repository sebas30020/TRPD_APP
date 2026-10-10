"""El trigger con que se calcularon los peaks (umbral, Δt, t_mín, filtro) se guarda en
metadata.yaml (canales.<ch>.trigger) y, junto con ediciones_peaks, basta para
reproducir fuera de la app el mismo conteo y la misma tabla (reproducir_trpd.py)."""

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
import generate_metadata  # noqa: E402
import reproducir_trpd  # noqa: E402

DT_US = 1e-4
T = np.arange(-1.0, 2.0 + DT_US / 2, DT_US)
PULSOS = {1: [(0.5, 100.0), (1.0, 40.0)], 2: [(0.8, 100.0), (1.2, 90.0)], 3: [(0.3, 70.0)]}
_ids = itertools.count()


def _senal(seg):
    v = np.zeros_like(T)
    for t0, a in PULSOS[seg]:
        v += a * np.exp(-0.5 * ((T - t0) / 0.001) ** 2)
    return v


class _Ctx:
    def __init__(self, prop_id):
        self.triggered = [{"prop_id": prop_id}]
        self.triggered_id = prop_id.split(".")[0]


@pytest.fixture
def medicion(tmp_path, monkeypatch):
    """Medición sintética de 3 disparos con su metadata.yaml en tmp_path."""
    (tmp_path / "metadata.yaml").write_text(
        "experimento:\n  id: prueba\nprobeta:\n  nro_vacuolas: 2\n"
        "canales:\n  ch4:\n    sensor: Antena 2\n", encoding="utf-8")
    carpeta = os.path.join(str(tmp_path), f"med_{next(_ids)}")
    monkeypatch.setattr(app, "_dir_medicion", lambda c: str(tmp_path))
    monkeypatch.setattr(app, "cargar_segmento", lambda c, ch, s, *a, **k: (T, _senal(int(s))))
    monkeypatch.setattr(app, "n_segmentos", lambda c: 3)
    monkeypatch.setattr(app, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "meta_medicion", lambda c: {ch: {"xinc": DT_US * 1e-6} for ch in app.TRIGGERS})
    monkeypatch.setattr(app, "t10_por_segmento", lambda c: np.zeros(3))
    app._CAPTURA_EDITADA_CACHE.clear()
    yield carpeta, tmp_path / "metadata.yaml"
    app._CAPTURA_EDITADA_CACHE.clear()


def _disco(ruta):
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def test_guardar_trigger_sin_tocar_el_resto(medicion):
    carpeta, ruta = medicion
    ok, msg = app.guardar_trigger_canales(
        carpeta, {"ch4": {"umbral": 50.123456, "dist": 0.05, "tmin": -1.0}}, filtrado=False)
    assert ok, msg
    d = _disco(ruta)
    assert d["experimento"] == {"id": "prueba"} and d["canales"]["ch4"]["sensor"] == "Antena 2"
    assert d["canales"]["ch4"]["trigger"] == {
        "umbral_mv": 50.123456, "distancia_us": 0.05, "tmin_us": -1.0,   # sin redondear
        "filtrado": False, "filtro": "sin filtro"}
    # Mismos valores: no se reescribe el archivo
    mtime = os.path.getmtime(ruta)
    ok, msg = app.guardar_trigger_canales(
        carpeta, {"ch4": {"umbral": 50.123456, "dist": 0.05, "tmin": -1.0}}, filtrado=False)
    assert ok and msg == "Trigger sin cambios" and os.path.getmtime(ruta) == mtime


def test_trigger_guardado_se_carga_al_abrir(medicion):
    carpeta, _ = medicion
    app.guardar_trigger_canales(carpeta, {"ch4": {"umbral": 33.0, "dist": 0.07, "tmin": 0.2}},
                                filtrado=False)
    cfg = app.config_sensores_defecto(carpeta, filtrado=False)
    assert cfg["ch4"] == {"umbral": 33.0, "dist": 0.07, "tmin": 0.2}
    # Con la otra señal (filtrada) el trigger guardado no aplica: se usa el de defecto
    assert app.config_sensores_defecto(carpeta, filtrado=True)["ch4"]["umbral"] != 33.0


def test_plantilla_de_metadata_conserva_el_trigger():
    previo = {"canales": {"ch4": {"sensor": "Antena 2",
                                  "trigger": {"umbral_mv": 33.0, "filtrado": True}}}}
    nuevo = {"canales": {"ch4": {"sensor": "Antena 2", "presente": True}}}
    d = generate_metadata.completar_metadata(previo, nuevo)
    assert d["canales"]["ch4"]["trigger"] == {"umbral_mv": 33.0, "filtrado": True}


def test_calcular_guarda_el_trigger(monkeypatch):
    llamadas = []
    monkeypatch.setattr(app, "guardar_trigger_canales",
                        lambda c, cfgs, filtrado=True: llamadas.append((c, cfgs, filtrado)) or (True, "ok"))
    monkeypatch.setattr(app, "canales_presentes", lambda c: ["ch1", "ch2", "ch3", "ch4"])
    cfg = {"ch2": {"umbral": 5.0, "dist": 0.035, "tmin": 0.15},
           "ch3": {"umbral": 6.0, "dist": 0.035, "tmin": 0.15},
           "ch4": {"umbral": 7.0, "dist": 0.035, "tmin": 0.15}}
    monkeypatch.setattr(app, "_cfg_sensores", lambda *a, **k: {ch: dict(c) for ch, c in cfg.items()})
    monkeypatch.setattr(app, "ctx", _Ctx("btn.n_clicks"))
    app.fijar_captura(1, "m", "ch3", *[None] * 9, ("on",), "m", "ch3", None, None)
    assert llamadas[-1] == ("m", {"ch3": cfg["ch3"]}, True)      # solo el canal calculado
    monkeypatch.setattr(app, "ctx", _Ctx("btn_multi.n_clicks"))
    app.fijar_captura(1, "m", "ch3", *[None] * 9, (), "m", "ch3", 1, None)
    assert llamadas[-1] == ("m", cfg, False)                      # todos los sensores


def test_reproducir_desde_metadata_da_lo_mismo(medicion):
    carpeta, ruta = medicion
    u, d, tm = 60.0, 0.05, -1.0
    # Lo que haría la app: calcular (guarda el trigger) y editar (guarda el historial)
    app.guardar_trigger_canales(carpeta, {"ch4": {"umbral": u, "dist": d, "tmin": tm}}, filtrado=False)
    ed = {"historial": [
        {"accion": "quitar", "puntos": [{"seg": 2, "t_us": 1.2}]},     # falso positivo
        {"accion": "anadir", "puntos": [{"seg": 1, "t_us": 1.0}]},     # bajo el umbral
        {"accion": "quitar_disparo", "segs": [3]},                     # disparo inválido
    ]}
    app.guardar_ediciones_canal(carpeta, "ch4", ed)
    app._CAPTURA_EDITADA_CACHE.clear()

    esperado = app.contar_peaks(carpeta, "ch4", u, d, tm, ediciones=ed, filtrado=False)
    assert esperado == ([1, 2, 3], [2, 1, 0])

    app._CAPTURA_EDITADA_CACHE.clear()
    r = reproducir_trpd.resultado_canal(carpeta, "ch4")   # solo lee metadata.yaml
    assert r["cfg"] == {"umbral": u, "dist": d, "tmin": tm, "filtrado": False}
    assert (r["segs"], r["cuentas"]) == esperado
    assert not any(int(s) == 2 and abs(t - 1.2) < 1e-3 for s, t in zip(r["cap"]["seg"], r["cap"]["t_peak"]))
    assert r["fila"]["distribucion"] == "[1, 1, 1, 0, 0, 0]" and r["fila"]["n_coinc"] == "1"
    # Canal sin trigger guardado: no se inventa un resultado
    assert reproducir_trpd.resultado_canal(carpeta, "ch2") is None
