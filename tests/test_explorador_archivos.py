import os
import unittest.mock as mock
import pytest
from dash import no_update

import app
import rutas
from calibrar_app import datos as cal_datos
from calibrar_app import main as cal_main


@pytest.fixture
def arbol(tmp_path):
    """Árbol de prueba independiente de dónde estén los datos reales:
    raiz/
      med_a/ch1.h5, ch4.h5            (medición estándar)
      agrupadas/1v2ch1-30s.h5, 1v2ch3-30s.h5, 1v3ch1-30s.h5   (dos mediciones agrupadas)
      vacia/
    """
    raiz = tmp_path / "raiz"
    (raiz / "med_a").mkdir(parents=True)
    for c in ("ch1", "ch4"):
        (raiz / "med_a" / f"{c}.h5").write_bytes(b"")
    (raiz / "agrupadas").mkdir()
    for f in ("1v2ch1-30s.h5", "1v2ch3-30s.h5", "1v3ch1-30s.h5"):
        (raiz / "agrupadas" / f).write_bytes(b"")
    (raiz / "vacia").mkdir()
    return str(raiz)


def test_no_hay_carpeta_de_datos_fija():
    assert not hasattr(app, "MEDICIONES")
    assert not hasattr(cal_datos, "MEDICIONES")
    assert not hasattr(app, "listar_mediciones")


def test_listar_subcarpetas_inexistente():
    assert app.listar_subcarpetas(None) == []
    assert app.listar_subcarpetas("ruta/falsa/que/no/existe") == []
    assert cal_datos.listar_subcarpetas(None) == []
    assert cal_datos.listar_subcarpetas("ruta/falsa/que/no/existe") == []


def test_listar_subcarpetas(arbol):
    subs = app.listar_subcarpetas(arbol)
    assert [n for n, _, _ in subs] == ["agrupadas", "med_a", "vacia"]
    assert {n: t for n, _, t in subs} == {"agrupadas": True, "med_a": True, "vacia": False}
    assert all(os.path.isabs(p) for _, p, _ in subs)
    assert subs == cal_datos.listar_subcarpetas(arbol)


def test_equipo_y_padre():
    unidades = rutas.listar_subcarpetas(rutas.EQUIPO)
    assert unidades and all(os.path.isdir(p) for _, p, _ in unidades)
    raiz_unidad = unidades[0][1]
    if os.name == "nt":
        assert rutas.padre(raiz_unidad) == rutas.EQUIPO
    assert rutas.padre(os.path.join(raiz_unidad, "x")) == os.path.normpath(raiz_unidad)
    assert rutas.padre(rutas.EQUIPO) == rutas.EQUIPO


def test_resolucion_rutas(arbol):
    med = os.path.join(arbol, "med_a")
    assert rutas.canales_presentes(med) == ["ch1", "ch4"]
    assert rutas.ruta_canal(med, "ch4") == os.path.join(med, "ch4.h5")
    assert rutas.dir_medicion(med) == med

    agr = os.path.join(arbol, "agrupadas")
    meds = rutas.mediciones_en(agr)
    assert meds == [os.path.join(agr, "1v2-30s"), os.path.join(agr, "1v3-30s")]
    assert rutas.canales_presentes(meds[0]) == ["ch1", "ch3"]
    assert rutas.canales_presentes(meds[1]) == ["ch1"]
    assert rutas.dir_medicion(meds[0]) == agr

    assert rutas.mediciones_en(os.path.join(arbol, "vacia")) == []
    assert rutas.canales_presentes(None) == []


@pytest.mark.parametrize("modulo, destino_ctx", [(app, "app.ctx"), (cal_main, "calibrar_app.main.ctx")])
def test_explorador_callbacks(arbol, modulo, destino_ctx):
    mock_ctx = mock.MagicMock()

    # 1. Abrir: sin medición elegida parte en la ruta actual del explorador
    mock_ctx.triggered_id = "btn_examinar"
    with mock.patch(destino_ctx, mock_ctx):
        hidden, inicio, val, _ = modulo.toggle_explorador(1, 0, 0, arbol, None, [])
    assert hidden is False and inicio == arbol and val is no_update

    # ...y con una medición elegida parte en su carpeta
    med = os.path.join(arbol, "med_a")
    with mock.patch(destino_ctx, mock_ctx):
        _, inicio, _, _ = modulo.toggle_explorador(1, 0, 0, arbol, med, [])
    assert inicio == med

    # 2. Cancelar
    mock_ctx.triggered_id = "explorador_cancelar"
    with mock.patch(destino_ctx, mock_ctx):
        hidden, _, val, _ = modulo.toggle_explorador(0, 1, 0, arbol, None, [])
    assert hidden is True and val is no_update

    # 3. Confirmar una carpeta con datos
    mock_ctx.triggered_id = "explorador_confirmar"
    with mock.patch(destino_ctx, mock_ctx):
        hidden, _, val, opts = modulo.toggle_explorador(0, 0, 1, med, None, [])
    assert hidden is True and val == med
    assert [o["value"] for o in opts] == [med]

    # Confirmar una carpeta con mediciones agrupadas agrega una opción por grupo
    agr = os.path.join(arbol, "agrupadas")
    with mock.patch(destino_ctx, mock_ctx):
        _, _, val, opts2 = modulo.toggle_explorador(0, 0, 1, agr, med, opts)
    assert val == os.path.join(agr, "1v2-30s")
    assert len(opts2) == 3

    # Confirmar una carpeta sin datos no hace nada
    with mock.patch(destino_ctx, mock_ctx):
        res = modulo.toggle_explorador(0, 0, 1, os.path.join(arbol, "vacia"), None, [])
    assert all(r is no_update for r in res)

    # 4. Subir y entrar
    mock_ctx.triggered_id = "explorador_subir"
    with mock.patch(destino_ctx, mock_ctx):
        assert modulo.navegar_explorador(1, [], med) == arbol
    mock_ctx.triggered_id = {"type": "explorador_ir", "ruta": agr}
    with mock.patch(destino_ctx, mock_ctx):
        assert modulo.navegar_explorador(0, [1], arbol) == agr

    # 5. Renderizar
    filas, label, disabled = modulo.renderizar_explorador(arbol)
    assert len(filas) == 3 and label == arbol and disabled is True
    _, _, disabled = modulo.renderizar_explorador(med)
    assert disabled is False
    filas, label, disabled = modulo.renderizar_explorador(rutas.EQUIPO)
    assert len(filas) >= 1 and label == "Este equipo" and disabled is True
