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


def test_valores_por_defecto_sin_trigger_guardado(medicion):
    carpeta, _ = medicion
    cfg = app.config_sensores_defecto(carpeta, filtrado=True)
    assert cfg == {"ch2": {"umbral": 130.0, "dist": 0.03, "tmin": 0.3},
                   "ch3": {"umbral": 50.0, "dist": 0.03, "tmin": 0.3},
                   "ch4": {"umbral": 40.0, "dist": 0.03, "tmin": 0.3}}


class _CtxCarga(_Ctx):
    def __init__(self, *prop_ids):
        super().__init__(prop_ids[0])
        self.triggered_prop_ids = {p: p.split(".")[0] for p in prop_ids}


def test_cargar_analisis_guardado(medicion):
    """«Cargar análisis guardado» rehace la captura (mapa conjunto) con los triggers de
    metadata.yaml de la señal vigente, sin tocar el archivo."""
    carpeta, ruta = medicion
    app.guardar_trigger_canales(carpeta, {"ch3": {"umbral": 20.0, "dist": 0.05, "tmin": -1.0},
                                          "ch4": {"umbral": 60.0, "dist": 0.05, "tmin": -1.0}},
                                filtrado=False)
    app.guardar_trigger_canales(carpeta, {"ch2": {"umbral": 9.0, "dist": 0.05, "tmin": -1.0}},
                                filtrado=True)
    assert set(app.triggers_guardados(carpeta, filtrado=False)) == {"ch3", "ch4"}
    assert set(app.triggers_guardados(carpeta, filtrado=True)) == {"ch2"}

    mtime = os.path.getmtime(ruta)
    import dash
    app.ctx = _CtxCarga("btn_cargar_guardado.n_clicks")
    try:
        # Trigger activo sin trigger guardado (ch2 con señal sin filtro): toma el primero
        p = app.fijar_captura(0, carpeta, "ch2", *[None] * 9, (), carpeta, "ch2", 0, None, 1)
        assert p["canal"] == "ch3" and p["umbral"] == 20.0 and p["cargado"]
        assert p["multi"] == {"ch3": {"umbral": 20.0, "dist": 0.05, "tmin": -1.0},
                              "ch4": {"umbral": 60.0, "dist": 0.05, "tmin": -1.0}}
        # El mismo clic cambia el selector a ch3: manda la carga, no se pierde la captura
        app.ctx = _CtxCarga("canal.value", "btn_cargar_guardado.n_clicks")
        assert app.fijar_captura(0, carpeta, "ch3", *[None] * 9, (), carpeta, "ch3", 0, None, 1) == p
        # La vuelta del selector (canal ya fijado) no rehace nada
        app.ctx = _CtxCarga("canal.value")
        assert app.fijar_captura(0, carpeta, "ch3", *[None] * 9, (), carpeta, "ch3", 0, p, 1) is dash.no_update
        # Cambiar a ch4 del mapa conjunto: ya no es una carga (la tabla no se rehace entera)
        p4 = app.fijar_captura(0, carpeta, "ch4", *[None] * 9, (), carpeta, "ch4", 0, p, 1)
        assert p4["canal"] == "ch4" and p4["umbral"] == 60.0 and "cargado" not in p4
        # Sin triggers guardados para la señal: no cambia nada
        app.ctx = _CtxCarga("btn_cargar_guardado.n_clicks")
        assert app.captura_guardada(carpeta, "ch4", filtrado=True)["multi"].keys() == {"ch2"}
    finally:
        app.ctx = dash.ctx
    assert os.path.getmtime(ruta) == mtime


def test_cargar_rehace_filas_de_densidad(medicion, monkeypatch):
    carpeta, _ = medicion
    monkeypatch.setattr(app, "calcular_fila_densidad",
                        lambda c, ch, u, d, t, **k: {"id": f"{c}_{ch}", "umbral": u})
    monkeypatch.setattr(app, "lag_canal", lambda *a: 0.0)
    monkeypatch.setattr(app, "ctx", _Ctx("captura_params.data"))
    p = {"carpeta": carpeta, "canal": "ch4", "umbral": 60.0, "dist": 0.05, "tmin": -1.0,
         "filtrado": False, "cargado": True,
         "multi": {"ch3": {"umbral": 20.0, "dist": 0.05, "tmin": -1.0},
                   "ch4": {"umbral": 60.0, "dist": 0.05, "tmin": -1.0}}}
    previas = [{"id": "otra_ch4", "umbral": 1.0}, {"id": f"{carpeta}_ch4", "umbral": 99.0}]
    # Aunque la pestaña Estadística no esté visible
    filas = app.actualizar_densidad_store(p, 0, 0, None, previas, *[None] * 9, None, "senales")
    assert filas == [{"id": "otra_ch4", "umbral": 1.0}, {"id": f"{carpeta}_ch3", "umbral": 20.0},
                     {"id": f"{carpeta}_ch4", "umbral": 60.0}]
