"""Tests de sincronización entre "Configuración Multi-Trigger" y el gráfico de señales:
umbral, Δt y t_mín escritos a mano deben reflejarse en la barra de umbral y en las
cruces de peaks, igual que en el cálculo de "⚡ Calcular peaks"."""

from __future__ import annotations
import os
import sys
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, RAIZ)

import app
from app import actualizar, figura, _captura_vigente

PARAMS = [f"{p}_{ch}" for ch in ("ch2", "ch3", "ch4") for p in ("umbral", "dist", "tmin")]


def _componentes(componente):
    yield componente
    hijos = getattr(componente, "children", None)
    if isinstance(hijos, list):
        for h in hijos:
            yield from _componentes(h)
    elif hijos is not None and not isinstance(hijos, str):
        yield from _componentes(hijos)


def test_callback_grafico_escucha_umbral_dist_tmin():
    """Los 9 campos son Input (no State) del callback que dibuja `grafico`."""
    # Callback principal del gráfico (salidas grafico.figure + rango_x.data, sin allow_duplicate)
    entrada = next(v for k, v in app.app.callback_map.items()
                   if k == "grafico.figure" or k.startswith("..grafico.figure..."))
    inputs = {f"{i['id']}.{i['property']}" for i in entrada["inputs"]}
    for pid in PARAMS:
        assert f"{pid}.value" in inputs, f"{pid} no redibuja el gráfico"


def test_campos_multitrigger_con_debounce():
    """Los campos redibujan al confirmar (Enter/blur), no en cada tecla."""
    por_id = {getattr(c, "id", None): c for c in _componentes(app.app.layout)}
    for pid in PARAMS:
        assert getattr(por_id[pid], "debounce", False) is True, pid


def _datos_sinteticos(monkeypatch):
    t = np.linspace(-5, 30, 3501)
    v = np.zeros_like(t)
    v[[1000, 2000, 3000]] = 20.0
    monkeypatch.setattr(app, "canales_presentes", lambda carpeta: ["ch2", "ch3", "ch4"])
    monkeypatch.setattr(app, "cargar_segmento", lambda carpeta, canal, seg, **k: (t, v))
    monkeypatch.setattr(app, "meta_medicion",
                        lambda carpeta: {ch: {"xinc": 1e-8} for ch in ("ch2", "ch3", "ch4")})


def _cfg(u4, dist=0.035, tmin=0.15):
    return {ch: {"umbral": u, "dist": dist, "tmin": tmin}
            for ch, u in (("ch2", 5.0), ("ch3", 6.0), ("ch4", u4))}


def test_barra_umbral_sigue_valor_escrito(monkeypatch):
    """La barra del canal se dibuja en el umbral escrito, y editrevision cambia con
    él para que el valor escrito prevalezca sobre una barra arrastrada antes."""
    _datos_sinteticos(monkeypatch)
    fig_a = figura("m", 1, "ch4", cfg_sensores=_cfg(7.0))
    fig_b = figura("m", 1, "ch4", cfg_sensores=_cfg(9.5))
    # shapes en el orden de TRIGGERS presentes: ch2, ch3, ch4
    assert fig_a.layout.shapes[2].y0 == 7.0
    assert fig_b.layout.shapes[2].y0 == 9.5
    assert fig_a.layout.editrevision != fig_b.layout.editrevision
    assert fig_a.layout.uirevision == fig_b.layout.uirevision  # zoom se conserva


def test_cruces_usan_tmin_escrito(monkeypatch):
    """Las cruces de vista previa respetan t_mín: peaks antes de t_mín desaparecen."""
    _datos_sinteticos(monkeypatch)
    t = np.linspace(-5, 30, 3501)
    t_peaks = t[[1000, 2000, 3000]]

    def cruces(fig):
        return [tr for tr in fig.data if tr.name == "peaks CH4"][0].x

    todas = cruces(figura("m", 1, "ch4", cfg_sensores=_cfg(10.0, tmin=-5.0)))
    tardias = cruces(figura("m", 1, "ch4", cfg_sensores=_cfg(10.0, tmin=t_peaks[1] + 0.1)))
    assert len(todas) == 3
    assert len(tardias) == 1


def test_captura_vigente():
    p = {"umbral": 10.0, "dist": 0.035, "tmin": 0.15}
    assert _captura_vigente(p, {"umbral": 10.0, "dist": 0.035, "tmin": 0.15})
    assert not _captura_vigente(p, {"umbral": 12.0, "dist": 0.035, "tmin": 0.15})
    assert not _captura_vigente(p, {"umbral": 10.0, "dist": 0.1, "tmin": 0.15})
    assert not _captura_vigente(p, {"umbral": 10.0, "dist": 0.035, "tmin": 1.0})
    assert _captura_vigente(p, {"umbral": None, "dist": 0.035, "tmin": 0.15})


def test_actualizar_descarta_captura_obsoleta(monkeypatch):
    """Tras editar un parámetro después de "⚡ Calcular peaks", el gráfico vuelve a
    vista previa en vez de mostrar las cruces del snapshot anterior (con las ediciones visibles)."""
    llamadas = []
    monkeypatch.setattr(app, "_cap_p", lambda p, ed=None: "CAP")   # captura editada del snapshot
    monkeypatch.setattr(app, "_ed", lambda store, carpeta, canal: {"historial": []})
    monkeypatch.setattr(app, "figura", lambda carpeta, seg, canal, cfg_sensores=None, cap=None, **k:
                        llamadas.append((cap, k.get("vista_previa"))))
    p = {"carpeta": "m", "canal": "ch4", "umbral": 10.0, "dist": 0.035, "tmin": 0.15}
    comunes = ("m", 1, "ch4", p, 5, 0.035, 0.15, 6, 0.035, 0.15)

    actualizar(*comunes, 10.0, 0.035, 0.15)   # coincide con el snapshot
    actualizar(*comunes, 12.0, 0.035, 0.15)   # umbral editado
    actualizar(*comunes, 10.0, 0.035, 0.50)   # t_mín editado
    # Con parámetros editados las cruces son de vista previa, pero la captura (manuales y
    # quitados) se sigue pasando para que ninguna edición quede invisible.
    assert llamadas == [("CAP", False), ("CAP", True), ("CAP", True)]
