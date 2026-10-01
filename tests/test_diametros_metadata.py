"""Tests de la casilla de diámetros de vacuolas (pestaña Metadata): normalización al
formato estándar '2mm-2mm-3mm', validación contra el código de probeta y guardado en
probeta.diametros sin alterar el resto de metadata.yaml."""

from __future__ import annotations
import os
import sys

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from generate_metadata import normalizar_diametros


def test_normalizar_formatos_de_entrada():
    for texto in ("2mm-2mm-3mm", "2, 2, 3", "2 2 3", "2;2;3", "2/2/3", "2MM - 2mm-3"):
        assert normalizar_diametros(texto) == ("2mm-2mm-3mm", None), texto
    assert normalizar_diametros("2.5, 3") == ("2.5mm-3mm", None)
    assert normalizar_diametros("2.0") == ("2mm", None)


def test_normalizar_rechaza_entradas_invalidas():
    for texto in ("", None, "abc", "2, x", "0", "-"):
        norm, error = normalizar_diametros(texto)
        assert norm is None and error, texto


def test_normalizar_valida_contra_codigo():
    assert normalizar_diametros("2, 3", nro_vacuolas=3)[1]            # faltan diámetros
    assert normalizar_diametros("2, 3, 3", nro_vacuolas=3) == ("2mm-3mm-3mm", None)
    assert normalizar_diametros("2, 3", tipo_geometria="monodiametro")[1]
    assert normalizar_diametros("2, 2", tipo_geometria="monodiametro") == ("2mm-2mm", None)
    assert normalizar_diametros("2, 2", tipo_geometria="mixta")[1]
    assert normalizar_diametros("2, 3", tipo_geometria="mixta") == ("2mm-3mm", None)


def _escribir_meta(carpeta, probeta):
    meta = {
        "experimento": {"id": "x", "temperatura_c": 21.5},
        "probeta": probeta,
        "calibracion_retardo": {"ch2": {"t_lag_ns": 12.3}},
    }
    with open(os.path.join(carpeta, "metadata.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, sort_keys=False, allow_unicode=True)


def _leer_meta(carpeta):
    with open(os.path.join(carpeta, "metadata.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_guardar_diametros_preserva_resto_del_yaml(tmp_path):
    carpeta = str(tmp_path)
    _escribir_meta(carpeta, {"codigo": "3v_2mm2mm3mm_0", "tipo_geometria": "mixta",
                             "nro_vacuolas": 3, "diametros": ""})
    ok, msg = app.guardar_diametros(carpeta, "2, 2, 3")
    assert ok, msg
    meta = _leer_meta(carpeta)
    assert meta["probeta"]["diametros"] == "2mm-2mm-3mm"
    assert meta["probeta"]["codigo"] == "3v_2mm2mm3mm_0"
    assert meta["experimento"]["temperatura_c"] == 21.5
    assert meta["calibracion_retardo"]["ch2"]["t_lag_ns"] == 12.3


def test_guardar_diametros_invalidos_no_escribe(tmp_path):
    carpeta = str(tmp_path)
    _escribir_meta(carpeta, {"codigo": "3v_2mm2mm3mm_0", "tipo_geometria": "mixta",
                             "nro_vacuolas": 3, "diametros": "2mm-2mm-3mm"})
    ok, msg = app.guardar_diametros(carpeta, "2, 3")   # 2 diámetros para 3 vacuolas
    assert not ok and "3 vacuolas" in msg
    assert _leer_meta(carpeta)["probeta"]["diametros"] == "2mm-2mm-3mm"


def test_guardar_diametros_asimetrica(tmp_path):
    """Con sufijo H, tipo_geometria es 'asimetrica': valida número de vacuolas pero admite diámetros iguales o distintos."""
    carpeta = str(tmp_path)
    _escribir_meta(carpeta, {"codigo": "2VH_3mm3mm_0", "tipo_geometria": "asimetrica",
                             "nro_vacuolas": 2, "diametros": ""})
    assert not app.guardar_diametros(carpeta, "2, 3, 4")[0]  # 3 diámetros para 2 vacuolas -> error
    assert app.guardar_diametros(carpeta, "3, 3")[0]
    assert _leer_meta(carpeta)["probeta"]["diametros"] == "3mm-3mm"
    assert app.guardar_diametros(carpeta, "2, 3")[0]
    assert _leer_meta(carpeta)["probeta"]["diametros"] == "2mm-3mm"


def test_layout_tiene_casilla_diametros():
    ids = set()

    def buscar(c):
        if getattr(c, "id", None):
            ids.add(c.id)
        hijos = getattr(c, "children", None)
        for h in (hijos if isinstance(hijos, list) else [hijos] if hijos is not None else []):
            if not isinstance(h, str):
                buscar(h)

    buscar(app.app.layout)
    assert {"meta_input_diametros", "btn_guardar_diametros"} <= ids
