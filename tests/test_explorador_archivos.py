import os
import unittest.mock as mock
import pytest
from dash import no_update

import app
from calibrar_app import datos as cal_datos
from calibrar_app import main as cal_main


def test_listar_subcarpetas_inexistente():
    assert app.listar_subcarpetas(None) == []
    assert app.listar_subcarpetas("ruta/falsa/que/no/existe") == []
    assert cal_datos.listar_subcarpetas(None) == []
    assert cal_datos.listar_subcarpetas("ruta/falsa/que/no/existe") == []


def test_listar_subcarpetas_mediciones():
    med_dir = app.MEDICIONES
    if not os.path.isdir(med_dir):
        pytest.skip("No existe MEDICIONES")

    subs_app = app.listar_subcarpetas(med_dir)
    subs_cal = cal_datos.listar_subcarpetas(med_dir)

    assert len(subs_app) > 0
    assert len(subs_app) == len(subs_cal)
    for nombre, ruta, tiene_h5 in subs_app:
        assert os.path.isabs(ruta)
        assert isinstance(tiene_h5, bool)


def test_explorador_callbacks_app():
    # 1. Abrir examinador
    mock_ctx = mock.MagicMock()
    mock_ctx.triggered_id = "btn_examinar"
    with mock.patch("app.ctx", mock_ctx):
        hidden, inicio, val, opts = app.toggle_explorador(1, 0, 0, None, "", [])
        assert hidden is False
        assert os.path.isdir(inicio)
        assert val is no_update

    # 2. Cancelar
    mock_ctx.triggered_id = "explorador_cancelar"
    with mock.patch("app.ctx", mock_ctx):
        hidden, inicio, val, opts = app.toggle_explorador(0, 1, 0, inicio, "", [])
        assert hidden is True
        assert val is no_update

    # 3. Confirmar seleccion
    ruta_test = "C:/ruta/falsa/medicion"
    opciones_orig = [{"label": "m1", "value": "m1"}]
    mock_ctx.triggered_id = "explorador_confirmar"
    with mock.patch("app.ctx", mock_ctx):
        hidden, _, val, opts = app.toggle_explorador(0, 0, 1, ruta_test, "m1", opciones_orig)
        assert hidden is True
        assert val == ruta_test
        assert any(o["value"] == ruta_test for o in opts)

    # 4. Navegar subir
    ruta_hijo = os.path.join(app.MEDICIONES, "cada_30s")
    if os.path.isdir(ruta_hijo):
        mock_ctx.triggered_id = "explorador_subir"
        with mock.patch("app.ctx", mock_ctx):
            padre = app.navegar_explorador(1, [], ruta_hijo)
            assert os.path.normpath(padre) == os.path.normpath(app.MEDICIONES)

    # 5. Navegar entrar a carpeta
    mock_ctx.triggered_id = {"type": "explorador_ir", "ruta": "/destino/prueba"}
    with mock.patch("app.ctx", mock_ctx):
        destino = app.navegar_explorador(0, [1], "/origen")
        assert destino == "/destino/prueba"

    # 6. Renderizar
    filas, label, disabled = app.renderizar_explorador(app.MEDICIONES)
    assert len(filas) > 0
    assert label == app.MEDICIONES


def test_explorador_callbacks_calibrar_app():
    mock_ctx = mock.MagicMock()

    # 1. Abrir examinador en calibrar_app
    mock_ctx.triggered_id = "btn_examinar"
    with mock.patch("calibrar_app.main.ctx", mock_ctx):
        hidden, inicio, val, opts = cal_main.toggle_explorador(1, 0, 0, None, "", [])
        assert hidden is False
        assert os.path.isdir(inicio)

    # 2. Cancelar
    mock_ctx.triggered_id = "explorador_cancelar"
    with mock.patch("calibrar_app.main.ctx", mock_ctx):
        hidden, _, _, _ = cal_main.toggle_explorador(0, 1, 0, inicio, "", [])
        assert hidden is True

    # 3. Confirmar seleccion
    ruta_test = "C:/otra/ruta/medicion"
    mock_ctx.triggered_id = "explorador_confirmar"
    with mock.patch("calibrar_app.main.ctx", mock_ctx):
        hidden, _, val, opts = cal_main.toggle_explorador(0, 0, 1, ruta_test, "", [])
        assert hidden is True
        assert val == ruta_test
        assert any(o["value"] == ruta_test for o in opts)

    # 4. Renderizar
    filas, label, disabled = cal_main.renderizar_explorador(cal_datos.MEDICIONES)
    assert len(filas) > 0
    assert label == cal_datos.MEDICIONES
