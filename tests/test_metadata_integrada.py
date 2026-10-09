"""generate_metadata integrado en app.py y calibrar_app: al abrir una medición las dos
apps crean o completan el mismo metadata.yaml, y solo calibrar_app escribe los t_lag."""

from __future__ import annotations
import os
import sys

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "calibrar_app"))

import app
import generate_metadata as gm
import main as cal_main
import persistencia
from test_generate_metadata import medicion  # noqa: F401  (fixture: medición .h5 sintética)

CAL = {"fecha": "2026-10-09", "fuente_calibracion": "calibrar_app", "referencia_impulso": "t10",
       "ch3": {"sensor": "Antena 1", "t_lag_ns": -116.559, "sigma_ns": 17.3, "n_valid": 11, "n_total": 5}}
ED = {"ch3": {"historial": [{"accion": "quitar", "seg": 2}]}}


def _yaml(medicion):
    with open(os.path.join(medicion, "metadata.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _escribir(medicion, datos):
    with open(os.path.join(medicion, "metadata.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, sort_keys=False, allow_unicode=True)


def test_asegurar_crea_y_no_reescribe(medicion):
    ruta, accion = gm.asegurar_metadata(medicion)
    assert accion == "creado"
    assert _yaml(medicion)["probeta"]["codigo"] == "3v_2mm2mm4mm_0"
    mtime = os.path.getmtime(ruta)
    assert gm.asegurar_metadata(medicion)[1] == "sin_cambios"
    assert os.path.getmtime(ruta) == mtime


def test_asegurar_completa_sin_tocar_calibracion(medicion):
    # Caso real: calibrar_app guardó antes de que existiera el YAML completo
    _escribir(medicion, {"ediciones_arribo": ED, "calibracion_retardo": CAL,
                         "experimento": {"temperatura_c": 21.5}})
    assert gm.asegurar_metadata(medicion)[1] == "completado"
    d = _yaml(medicion)
    assert d["calibracion_retardo"] == CAL and d["ediciones_arribo"] == ED
    assert d["experimento"]["temperatura_c"] == 21.5          # lo escrito se conserva
    assert d["probeta"]["codigo"] == "3v_2mm2mm4mm_0"         # lo faltante se rellena
    assert d["circuito_impulso"]["tension_kv_ac_sec"] == 10.0


def test_plantilla_nunca_trae_secciones_de_apps(medicion):
    d = gm.plantilla_metadata(medicion, medicion)
    assert not set(gm.SECCIONES_DE_APPS) & set(d)


def test_forzar_conserva_calibracion(medicion):
    _escribir(medicion, {"calibracion_retardo": CAL, "ediciones_arribo": ED,
                         "ediciones_peaks": {"ch3": {"historial": []}}, "probeta": {"codigo": "x"}})
    gm.generar(medicion, forzar=True)
    d = _yaml(medicion)
    assert d["calibracion_retardo"] == CAL and d["ediciones_arribo"] == ED
    assert "ediciones_peaks" in d
    assert d["probeta"]["codigo"] == "3v_2mm2mm4mm_0"         # lo automático se rehace


def test_app_abre_medicion_y_genera_yaml(medicion):
    assert app.asegurar_metadata_al_abrir(medicion)["accion"] == "creado"
    assert app.obtener_metadata(medicion)["_existe_en_disco"] is True


def test_calibrar_abre_medicion_y_genera_yaml(medicion):
    assert cal_main.asegurar_metadata_al_abrir(medicion)["accion"] == "creado"
    assert _yaml(medicion)["probeta"]["codigo"] == "3v_2mm2mm4mm_0"


def test_calibrar_guarda_sobre_yaml_completo(medicion):
    # Sin metadata.yaml previo, guardar la calibración deja también todo lo de generate_metadata
    ok, _ = persistencia.guardar_calibracion_metadata(medicion, CAL)
    assert ok
    d = _yaml(medicion)
    assert d["calibracion_retardo"] == CAL
    assert d["probeta"]["codigo"] == "3v_2mm2mm4mm_0" and "canales" in d


def test_app_no_puede_escribir_t_lag(medicion):
    gm.asegurar_metadata(medicion)
    d = _yaml(medicion)
    d["calibracion_retardo"] = CAL
    d["ediciones_arribo"] = ED
    _escribir(medicion, d)

    # Editor YAML de app.py: se cambia un t_lag, se borra ediciones_arribo y se edita otra cosa
    editado = dict(d, calibracion_retardo=dict(CAL, ch3=dict(CAL["ch3"], t_lag_ns=0.0)))
    editado.pop("ediciones_arribo")
    editado["experimento"] = dict(d["experimento"], temperatura_c=25.0)
    ok, msg = app.guardar_metadata_archivo(medicion, yaml.safe_dump(editado, sort_keys=False))
    assert ok and "calibrar_app" in msg
    final = _yaml(medicion)
    assert final["calibracion_retardo"] == CAL and final["ediciones_arribo"] == ED
    assert final["experimento"]["temperatura_c"] == 25.0


def test_app_no_puede_crear_calibracion(medicion):
    gm.asegurar_metadata(medicion)
    d = dict(_yaml(medicion), calibracion_retardo=CAL)
    ok, _ = app.guardar_metadata_archivo(medicion, yaml.safe_dump(d, sort_keys=False))
    assert ok and "calibracion_retardo" not in _yaml(medicion)


def test_app_no_calcula_retardos():
    with open(os.path.join(RAIZ, "app.py"), encoding="utf-8") as f:
        src = f.read()
    for nombre in ("calibrar_retardo", "bloque_calibracion_retardo", "guardar_calibracion_metadata"):
        assert nombre not in src, nombre
