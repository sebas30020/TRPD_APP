"""Pruebas de estructura y navegación de la GUI (tabs_principal, panel_estadistica, panel_calibracion)."""

from dash import no_update
import app


def _buscar_componente_por_id(componente, target_id):
    """Búsqueda recursiva en el árbol de layout de Dash."""
    if hasattr(componente, "id") and componente.id == target_id:
        return componente
    if hasattr(componente, "children"):
        children = componente.children
        if isinstance(children, list):
            for child in children:
                res = _buscar_componente_por_id(child, target_id)
                if res is not None:
                    return res
        elif children is not None:
            return _buscar_componente_por_id(children, target_id)
    return None


def test_tabs_principal_estructura():
    """tabs_principal debe contener 4 pestañas: senales, estadistica, metadata, calibracion."""
    tabs = _buscar_componente_por_id(app.app.layout, "tabs_principal")
    assert tabs is not None, "tabs_principal no encontrado en layout"
    valores_esperados = ["senales", "estadistica", "metadata", "calibracion"]
    valores_tabs = [tab.value for tab in tabs.children if hasattr(tab, "value")]
    assert valores_tabs == valores_esperados


def test_paneles_principales_existen():
    """Los 4 paneles principales deben existir en el layout."""
    for pid in ["panel_analisis", "panel_estadistica", "panel_metadata", "panel_calibracion_embed"]:
        panel = _buscar_componente_por_id(app.app.layout, pid)
        assert panel is not None, f"Panel {pid} no encontrado en layout"


def test_componentes_panel_estadistica():
    """panel_estadistica debe alojar tabla_densidad y los botones de acción."""
    panel_est = _buscar_componente_por_id(app.app.layout, "panel_estadistica")
    assert panel_est is not None
    tabla = _buscar_componente_por_id(panel_est, "tabla_densidad")
    assert tabla is not None, "tabla_densidad no encontrada dentro de panel_estadistica"
    btn_calc = _buscar_componente_por_id(panel_est, "btn_calc_todos_sensores")
    assert btn_calc is not None, "btn_calc_todos_sensores no encontrado en panel_estadistica"
    btn_limpiar = _buscar_componente_por_id(panel_est, "btn_limpiar_densidad")
    assert btn_limpiar is not None, "btn_limpiar_densidad no encontrado en panel_estadistica"
    btn_exp = _buscar_componente_por_id(panel_est, "btn_exportar_densidad")
    assert btn_exp is not None, "btn_exportar_densidad no encontrado en panel_estadistica"
    assert _buscar_componente_por_id(panel_est, "descarga_densidad") is not None


def test_interruptor_filtros_presente_y_activo():
    sw = _buscar_componente_por_id(app.app.layout, "switch_filtros")
    assert sw is not None and sw.value == ["on"]


def test_componentes_panel_calibracion_embed():
    """panel_calibracion_embed debe contener iframe_calibracion con src diferido."""
    panel_cal = _buscar_componente_por_id(app.app.layout, "panel_calibracion_embed")
    assert panel_cal is not None
    iframe = _buscar_componente_por_id(panel_cal, "iframe_calibracion")
    assert iframe is not None
    assert iframe.src == "" or iframe.src is None


def test_callbacks_navegacion_paneles():
    """Verifica que alternar_panel_principal oculte y muestre los paneles correctos."""
    assert app.alternar_panel_principal("senales") == (False, True, True, True)
    assert app.alternar_panel_principal("estadistica") == (True, False, True, True)
    assert app.alternar_panel_principal("metadata") == (True, True, False, True)
    assert app.alternar_panel_principal("calibracion") == (True, True, True, False)


def test_callback_alternar_panel_dominio():
    """Verifica que alternar_panel_dominio controle senales (gráfico + barra de edición) vs st."""
    assert app.alternar_panel_dominio("senales") == (False, False, True)
    assert app.alternar_panel_dominio("st") == (True, True, False)


def test_callback_diferir_carga_iframe():
    """El iframe sólo se carga al visitar la pestaña calibracion."""
    assert app.diferir_carga_iframe_calibracion("calibracion", "") == "http://127.0.0.1:8052"
    assert app.diferir_carga_iframe_calibracion("calibracion", "http://127.0.0.1:8052") == no_update
    assert app.diferir_carga_iframe_calibracion("senales", "") == no_update


def test_callback_ir_a_calibracion():
    """El botón de calibración en la barra superior debe activar la pestaña calibracion."""
    assert app.ir_a_pestana_calibracion(1) == "calibracion"
    assert app.ir_a_pestana_calibracion(0) == no_update
