"""Módulo de gráficos Plotly para calibrar_app."""

from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datos import (
    cargar_segmento,
    VENTANA_T10,
    canales_presentes,
    umbral_defecto,
    _muestras,
)
from arribo import t_arribo

_COLORES_CANALES = {
    "ch1": "#1f77b4",
    "ch2": "#2563eb",  # azul
    "ch3": "#059669",  # verde
    "ch4": "#d97706",  # naranja
}

PUNTOS_PLOT = 5000
TRIGGERS = ("ch2", "ch3", "ch4")


def umbrales_desde_relayout(relayout: dict | None, canales: list[str]) -> dict[str, float]:
    """Extrae las posiciones 'y' de las líneas de umbral movibles (shapes) desde relayoutData."""
    if not relayout:
        return {}
    trigs_presentes = [c for c in TRIGGERS if c in canales]
    cambios = {}
    for k, val in relayout.items():
        if k.startswith("shapes[") and (k.endswith(".y0") or k.endswith(".y1")):
            try:
                idx_str = k.split("[")[1].split("]")[0]
                idx = int(idx_str)
                if 0 <= idx < len(trigs_presentes):
                    ch = trigs_presentes[idx]
                    cambios[ch] = round(abs(float(val)), 2)
            except (TypeError, ValueError, IndexError):
                pass
    return cambios


def umbral_desde_relayout(relayout: dict | None, fallback: float) -> float:
    """Extrae la posición 'y' de la línea movible desde relayoutData (retrocompatibilidad)."""
    if relayout:
        for k, val in relayout.items():
            if "shapes" in k and (".y0" in k or ".y1" in k):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return fallback


def figura_canal(carpeta: str, canal: str, seg: int,
                 umbral: float | None = None,
                 dist_us: float = 0.035,
                 tmin: float | None = None,
                 ancla_us: float | None = None,
                 t_arr_us: float | None = None,
                 referencia_nombre: str = "t10",
                 cfg_sensores: dict | None = None) -> go.Figure:
    """Gráfico multicanal sincronizado (CH1..CH4) con eje X compartido, triggers independientes por canal y marcas."""
    canales_todos = ["ch1", "ch2", "ch3", "ch4"]
    disponibles = canales_presentes(carpeta) if carpeta else canales_todos
    canales = [c for c in canales_todos if c in disponibles]
    if not canales:
        canales = [canal]

    trigs_presentes = [c for c in TRIGGERS if c in canales]
    cfg = dict(cfg_sensores or {})

    titles = []
    sensores_nombres = {"ch2": "HFCT", "ch3": "Vivaldi", "ch4": "Bioinspirada"}
    for c in canales:
        if c == "ch1":
            ancla_txt = f" (Ancla {referencia_nombre} = {ancla_us:.3f} µs)" if ancla_us is not None else ""
            titles.append(f"CH1 — Impulso de Referencia{ancla_txt}")
        else:
            s_nom = sensores_nombres.get(c, "Sensor")
            foco_txt = " ★ CANAL ACTIVO" if c == canal and canal != "todos" else ""
            titles.append(f"{c.upper()} — {s_nom}{foco_txt}")

    fig = make_subplots(
        rows=len(canales), cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        subplot_titles=titles,
    )

    # 1. Cargar señales y agregar PRIMERO las trazas Scattergl para inicializar los subplots
    datos_canales = {}
    for i, c in enumerate(canales, start=1):
        fig.update_yaxes(title_text="mV", row=i, col=1)
        t, v = cargar_segmento(carpeta, c, seg, ventana=VENTANA_T10)
        datos_canales[c] = (t, v)
        color = _COLORES_CANALES.get(c, "#2563eb")

        if v.size > 0:
            fig.add_trace(
                go.Scattergl(
                    x=t.astype(np.float32), y=v.astype(np.float32), mode="lines", name=c.upper(),
                    line=dict(color=color, width=1.2 if c == "ch1" or c == canal else 0.9),
                    hovertemplate="t=%{x:.4f} µs<br>v=%{y:.2f} mV<extra>" + c.upper() + "</extra>",
                    showlegend=False,
                ),
                row=i, col=1,
            )

    # 2. Agregar líneas de umbral horizontales EDITABLES (+u) para trigs_presentes.
    # Al estar ya inicializados los subplots por las trazas, Plotly crea shapes[0], shapes[1], shapes[2]
    # garantizando el orden exacto para umbrales_desde_relayout.
    u_canales = {}
    for ch in trigs_presentes:
        fila = canales.index(ch) + 1
        cfg_ch = cfg.get(ch, {})
        if cfg_ch.get("umbral") is not None:
            u_c = float(cfg_ch["umbral"])
        elif ch == canal and umbral is not None:
            u_c = float(umbral)
        else:
            u_c = float(umbral_defecto(carpeta, ch, seg=seg))
        u_canales[ch] = u_c

        color_u = _COLORES_CANALES.get(ch, "#dc2626")
        ancho_u = 1.8
        dash_u = "dash"
        label_u = f"u_{ch} = {u_c:.2f} mV"

        fig.add_hline(
            y=u_c, row=fila, col=1,
            line=dict(color=color_u, width=ancho_u, dash=dash_u),
            annotation_text=label_u,
            annotation_position="top left",
            editable=True,
        )

    # 3. Agregar líneas verticales (ancla y t_min), marcas de arribo y anotaciones
    for i, c in enumerate(canales, start=1):
        t, v = datos_canales.get(c, (np.array([]), np.array([])))

        # Línea vertical de ancla de impulso (t10 u O1) visible en todos los subplots
        if ancla_us is not None:
            fig.add_vline(
                x=ancla_us, row=i, col=1,
                line=dict(color="#10b981", width=1.5 if c == "ch1" else 1.0, dash="dot"),
            )

        if c == "ch1":
            if ancla_us is not None:
                fig.add_annotation(
                    xref=f"x{i} domain" if i > 1 else "x domain",
                    yref=f"y{i} domain" if i > 1 else "y domain",
                    x=0.98, y=0.92,
                    text=f"<b>Ancla {referencia_nombre}</b> = {ancla_us:.4f} µs",
                    showarrow=False, align="right",
                    font=dict(size=10, color="#065f46"), bgcolor="rgba(236,253,245,0.85)",
                    bordercolor="#a7f3d0", borderwidth=1, borderpad=4
                )
            continue

        # Canales sensores (CH2, CH3, CH4)
        cfg_c = cfg.get(c, {})
        tmin_c = float(cfg_c.get("tmin", tmin if tmin is not None else 0.15))
        u_c = u_canales.get(c, float(umbral_defecto(carpeta, c, seg=seg)))

        # Línea vertical de t_mín independiente por canal
        fig.add_vline(x=tmin_c, row=i, col=1, line=dict(color="#94a3b8", width=1, dash="dash"))

        # Detección de arribo independiente
        dist_m = _muestras(carpeta, c, dist_us) or 1
        ta = t_arribo(t, v, u_c, dist_m, tmin_c) if v.size > 0 else None

        tlag_str = "—"
        if ta is not None and v.size > 0:
            v_arr = float(np.interp(ta, t, v))
            fig.add_trace(
                go.Scatter(
                    x=[ta], y=[v_arr], mode="markers", name=f"arribo {c}",
                    marker=dict(symbol="x", color="black", size=9, line=dict(width=2)),
                    hovertemplate=f"t_ant={ta:.4f} µs<br>v={v_arr:.2f} mV<extra>{c.upper()}</extra>",
                    showlegend=False,
                ),
                row=i, col=1,
            )
            if ancla_us is not None:
                tlag_ns = (ta - ancla_us) * 1e3
                tlag_str = f"{tlag_ns:.2f} ns"

            anotacion_texto = f"<b>{c.upper()}</b> · t_ant = {ta:.4f} µs · <b>t_lag = {tlag_str}</b>"
            badge_bg = "rgba(255,255,255,0.9)"
            badge_border = "#cbd5e1"
        else:
            anotacion_texto = f"<b>{c.upper()}</b> · Sin cruce de umbral"
            badge_bg = "rgba(254,242,242,0.85)"
            badge_border = "#fecaca"

        fig.add_annotation(
            xref=f"x{i} domain" if i > 1 else "x domain",
            yref=f"y{i} domain" if i > 1 else "y domain",
            x=0.98, y=0.92,
            text=anotacion_texto, showarrow=False, align="right",
            font=dict(size=10, color="#1e293b"), bgcolor=badge_bg,
            bordercolor=badge_border, borderwidth=1, borderpad=4
        )

    fig.update_xaxes(title_text="Tiempo [µs]", row=len(canales), col=1)
    fig.update_layout(
        height=680,
        margin=dict(t=50, b=40, l=55, r=25),
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False,
        uirevision=f"{carpeta}",
    )
    return fig


def figura_impulso_iec(carpeta: str, seg: int, res_iec: dict) -> go.Figure:
    """Gráfico del impulso CH1 con el ajuste IEC 60060-1, curva base y residual sin solapamiento."""
    fig = go.Figure()
    if not res_iec.get("exito"):
        fig.update_layout(
            title=f"Evaluación IEC CH1 — Segmento {seg} (No disponible)",
            height=380, margin=dict(t=50, b=40, l=50, r=20),
            plot_bgcolor="white", paper_bgcolor="white",
        )
        return fig

    u0 = res_iec.get("u0")
    Um = res_iec.get("Um")
    Utc = res_iec.get("Ut_curva")
    t = cargar_segmento(carpeta, "ch1", seg, ventana=None)[0]

    if t.size > 0 and u0 is not None:
        paso = max(1, t.size // PUNTOS_PLOT)
        fig.add_trace(go.Scattergl(
            x=t[::paso], y=u0[::paso], mode="lines", name="u0(t) registrada",
            line=dict(color="#94a3b8", width=1), opacity=0.7,
        ))
        if Um is not None:
            fig.add_trace(go.Scattergl(
                x=t[::paso], y=Um[::paso], mode="lines", name="Um(t) base ajustada",
                line=dict(color="#f59e0b", width=1.2, dash="dash"),
            ))
        if Utc is not None:
            fig.add_trace(go.Scattergl(
                x=t[::paso], y=Utc[::paso], mode="lines", name="Ut(t) ensayo filtrada",
                line=dict(color="#2563eb", width=1.5),
            ))

    # Líneas verticales normativas con posiciones alternadas
    vlines = [
        ("O1", res_iec.get("O1"), "#dc2626", "solid", "O1", "top left"),
        ("t10", res_iec.get("t10"), "#10b981", "dot", "t10", "bottom left"),
        ("t30", res_iec.get("t30"), "#059669", "dash", "t30", "top right"),
        ("t90", res_iec.get("t90"), "#059669", "dash", "t90", "bottom right"),
        ("t50", res_iec.get("t50"), "#7c3aed", "dot", "t50", "top right"),
    ]
    for tag, val, col, dash, label, pos in vlines:
        if val is not None:
            fig.add_vline(x=val, line=dict(color=col, width=1.2, dash=dash),
                          annotation_text=label, annotation_position=pos)

    T1_str = f"{res_iec.get('T1', 0):.3f}" if res_iec.get("T1") is not None else "—"
    T2_str = f"{res_iec.get('T2', 0):.2f}" if res_iec.get("T2") is not None else "—"
    beta_str = f"{res_iec.get('beta_pct', 0):.2f}" if res_iec.get("beta_pct") is not None else "—"
    O1_str = f"{res_iec.get('O1', 0):.4f}" if res_iec.get("O1") is not None else "—"
    t10_str = f"{res_iec.get('t10', 0):.4f}" if res_iec.get("t10") is not None else "—"
    t30_str = f"{res_iec.get('t30', 0):.4f}" if res_iec.get("t30") is not None else "—"
    t90_str = f"{res_iec.get('t90', 0):.4f}" if res_iec.get("t90") is not None else "—"
    t50_str = f"{res_iec.get('t50', 0):.2f}" if res_iec.get("t50") is not None else "—"

    # Tarjeta resumen en la esquina superior derecha (donde la señal ya cayó)
    anotacion_tiempos = (
        f"<b>Parámetros de Impulso (CH1)</b><br>"
        f"<span style='color:#dc2626'>■</span> O1 = {O1_str} µs<br>"
        f"<span style='color:#10b981'>■</span> t10 = {t10_str} µs<br>"
        f"<span style='color:#059669'>■</span> t30 = {t30_str} µs<br>"
        f"<span style='color:#059669'>■</span> t90 = {t90_str} µs<br>"
        f"<span style='color:#7c3aed'>■</span> t50 = {t50_str} µs"
    )
    fig.add_annotation(
        xref="paper", yref="paper", x=0.98, y=0.95,
        text=anotacion_tiempos, showarrow=False, align="right",
        font=dict(size=10, color="#1e293b"), bgcolor="rgba(255,255,255,0.9)",
        bordercolor="#cbd5e1", borderwidth=1, borderpad=6
    )

    subtitulo = f"T1 = {T1_str} µs · T2 = {T2_str} µs · β' = {beta_str} % · O1 = {O1_str} µs"
    fig.update_layout(
        title=f"Evaluación Normativa IEC 60060-1 (CH1 Seg {seg})<br><sub>{subtitulo}</sub>",
        xaxis_title="Tiempo [µs]", yaxis_title="Tensión [mV]",
        height=380, margin=dict(t=75, b=60, l=55, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
        uirevision=f"{carpeta}|{seg}",
    )
    return fig


def figura_dispersion_lag(resultados: dict, canal: str = "") -> go.Figure:
    """Subplots (1x2): Dispersión de t_lag por segmento e Histograma de frecuencias."""
    ch = (canal or resultados.get("canal", "ch4")).lower()
    sensores_map = {"ch2": "HFCT", "ch3": "Vivaldi", "ch4": "Bioinspirada"}
    sensor_nom = sensores_map.get(ch, ch.upper())

    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True,
        column_widths=[0.7, 0.3], horizontal_spacing=0.03,
        subplot_titles=[f"Retardo t_lag por disparo — {ch.upper()} ({sensor_nom})", "Distribución"]
    )
    if not resultados:
        fig.update_layout(
            height=330, plot_bgcolor="white", paper_bgcolor="white",
            annotations=[dict(
                text=f"Sin calibración para {ch.upper()} ({sensor_nom}). Pulsa ▶ Calcular Retardo.",
                xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                font=dict(size=12, color="#64748b")
            )]
        )
        return fig

    color = _COLORES_CANALES.get(ch, "#2563eb")
    segs = np.asarray(resultados.get("segs", []))
    t_lag_us = np.asarray(resultados.get("t_lag", []), dtype=np.float64)
    t_lag_ns = t_lag_us * 1e3
    val = np.asarray(resultados.get("valido", []), dtype=bool)

    if np.any(val):
        # Puntos válidos
        fig.add_trace(
            go.Scatter(
                x=segs[val], y=t_lag_ns[val], mode="markers",
                name=f"Válidos ({resultados.get('n_valid')}/{resultados.get('n_total')})",
                marker=dict(color=color, size=7),
                hovertemplate="Disparo %{x}<br>t_lag=%{y:.2f} ns<extra></extra>",
            ),
            row=1, col=1,
        )
        # Histograma
        fig.add_trace(
            go.Histogram(
                y=t_lag_ns[val], name="Frecuencia",
                marker=dict(color=color), opacity=0.6,
                showlegend=False,
            ),
            row=1, col=2,
        )

    # Atípicos / inválidos
    atip = np.asarray(resultados.get("atipico", []), dtype=bool)
    if np.any(atip):
        fig.add_trace(
            go.Scatter(
                x=segs[atip], y=t_lag_ns[atip], mode="markers",
                name=f"Atípicos ({np.sum(atip)})",
                marker=dict(color="#ef4444", symbol="x", size=8),
                hovertemplate="Disparo %{x}<br>t_lag=%{y:.2f} ns (atípico)<extra></extra>",
            ),
            row=1, col=1,
        )

    # Línea de media
    media_us = resultados.get("t_lag_us")
    if media_us is not None:
        m_ns = media_us * 1e3
        sigma_ns = (resultados.get("sigma_us") or 0.0) * 1e3
        fig.add_hline(
            y=m_ns, line=dict(color="#0f172a", width=1.5, dash="dash"),
            annotation_text=f"Media: {m_ns:.2f} ± {sigma_ns:.2f} ns",
            annotation_position="bottom right", row=1, col=1,
        )

    fig.update_xaxes(title_text="Disparo", row=1, col=1)
    fig.update_yaxes(title_text="t_lag [ns]", row=1, col=1)
    fig.update_xaxes(title_text="Conteo", row=1, col=2)

    fig.update_layout(
        height=330, margin=dict(t=45, b=55, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
    )
    return fig


def figura_ancla_por_segmento(carpeta: str, referencia: str, ancla_arr: np.ndarray) -> go.Figure:
    """Gráfico de evolución temporal de las marcas de ancla por segmento."""
    fig = go.Figure()
    if ancla_arr.size == 0:
        return fig
    segs = np.arange(1, ancla_arr.size + 1)
    fig.add_trace(go.Scatter(
        x=segs, y=ancla_arr, mode="lines+markers",
        name=referencia, marker=dict(color="#10b981", size=6),
        line=dict(color="#10b981", width=1.2),
        hovertemplate="Disparo %{x}<br>Ancla=%{y:.4f} µs<extra></extra>",
    ))
    fig.update_layout(
        title=f"Marcas de Referencia Temporal ({referencia}) por Disparo",
        xaxis_title="Disparo", yaxis_title="Tiempo de Ancla [µs]",
        height=260, margin=dict(t=40, b=35, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig
