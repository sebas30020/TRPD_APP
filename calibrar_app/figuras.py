"""Módulo de gráficos Plotly para calibrar_app."""

from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datos import cargar_segmento, VENTANA_T10

_COLORES_CANALES = {
    "ch1": "#1f77b4",
    "ch2": "#2563eb",  # azul
    "ch3": "#059669",  # verde
    "ch4": "#d97706",  # naranja
}

PUNTOS_PLOT = 5000


def umbral_desde_relayout(relayout: dict | None, fallback: float) -> float:
    """Extrae la posición 'y' de la línea movible (shapes[0]) desde relayoutData."""
    if relayout:
        for k, val in relayout.items():
            if k.startswith("shapes[") and k.endswith(".y0"):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return fallback


def figura_canal(carpeta: str, canal: str, seg: int, umbral: float,
                 dist_us: float, tmin: float, ancla_us: float | None,
                 t_arr_us: float | None) -> go.Figure:
    """Gráfico interactivo de la señal del sensor con línea de umbral editable y marcas."""
    fig = go.Figure()
    color = _COLORES_CANALES.get(canal, "#2563eb")

    t, v = cargar_segmento(carpeta, canal, seg, ventana=VENTANA_T10)
    if v.size > 0:
        paso = max(1, t.size // PUNTOS_PLOT)
        fig.add_trace(go.Scattergl(
            x=t[::paso], y=v[::paso], mode="lines", name=canal.upper(),
            line=dict(color=color, width=1.0),
            hovertemplate="t=%{x:.4f} µs<br>v=%{y:.2f} mV<extra>" + canal.upper() + "</extra>",
        ))

    # Línea vertical de t_mínimo
    if tmin is not None:
        fig.add_vline(x=tmin, line=dict(color="#94a3b8", width=1, dash="dash"),
                      annotation_text="t_mín", annotation_position="bottom right")

    # Línea vertical de ancla de impulso (t10 u O1)
    if ancla_us is not None:
        fig.add_vline(x=ancla_us, line=dict(color="#10b981", width=1.5, dash="dot"),
                      annotation_text=f"Ancla ({ancla_us:.3f} µs)", annotation_position="top left")

    # Línea horizontal de umbral móvil (shapes[0] editable)
    fig.add_hline(
        y=umbral,
        line=dict(color="#dc2626", width=2.0, dash="dash"),
        annotation_text=f"u = {umbral:.2f} mV",
        annotation_position="top left",
    )

    # Marca del tiempo de arribo
    tlag_str = "—"
    if t_arr_us is not None and v.size > 0:
        dt = t[1] - t[0] if t.size > 1 else 0.0002
        idx_cercano = int(np.clip(round((t_arr_us - t[0]) / dt), 0, v.size - 1))
        v_arr = float(v[idx_cercano])
        fig.add_trace(go.Scatter(
            x=[t_arr_us], y=[v_arr], mode="markers", name="t_arribo",
            marker=dict(symbol="x", color="black", size=11, line=dict(width=2)),
            hovertemplate=f"t_ant={t_arr_us:.4f} µs<br>v={v_arr:.2f} mV<extra>arribo</extra>",
            showlegend=False,
        ))
        if ancla_us is not None:
            tlag_ns = (t_arr_us - ancla_us) * 1e3
            tlag_str = f"{tlag_ns:.2f} ns"

    anotacion_texto = (
        f"<b>Segmento {seg}</b><br>"
        f"t_ant = {t_arr_us:.4f} µs<br>" if t_arr_us is not None else f"<b>Segmento {seg}</b><br>t_ant = Sin cruce<br>"
    )
    if ancla_us is not None:
        anotacion_texto += f"t_ancla = {ancla_us:.4f} µs<br><b>t_lag = {tlag_str}</b>"

    fig.add_annotation(
        xref="paper", yref="paper", x=0.98, y=0.95,
        text=anotacion_texto, showarrow=False, align="right",
        font=dict(size=11, color="#1e293b"), bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#cbd5e1", borderwidth=1, borderpad=6
    )

    fig.update_layout(
        title=f"Inspección de Arribo — Canal {canal.upper()} · Segmento {seg}",
        xaxis_title="Tiempo [µs]", yaxis_title="Tensión [mV]",
        height=380, margin=dict(t=50, b=40, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        uirevision=f"{carpeta}|{canal}",
    )
    return fig


def figura_impulso_iec(carpeta: str, seg: int, res_iec: dict) -> go.Figure:
    """Gráfico del impulso CH1 con el ajuste IEC 60060-1, curva base y residual."""
    fig = go.Figure()
    if not res_iec.get("exito"):
        fig.update_layout(
            title=f"Evaluación IEC CH1 — Segmento {seg} (No disponible)",
            height=380, margin=dict(t=50, b=40, l=50, r=20),
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

    # Líneas verticales normativas
    vlines = [
        ("O1", res_iec.get("O1"), "#dc2626", "solid", "O1 (origen virtual)"),
        ("t10", res_iec.get("t10"), "#10b981", "dot", "t10 (10%)"),
        ("t30", res_iec.get("t30"), "#059669", "dash", "t30 (30%)"),
        ("t90", res_iec.get("t90"), "#059669", "dash", "t90 (90%)"),
        ("t50", res_iec.get("t50"), "#7c3aed", "dot", "t50 (50% cola)"),
    ]
    for tag, val, col, dash, label in vlines:
        if val is not None:
            fig.add_vline(x=val, line=dict(color=col, width=1.2, dash=dash),
                          annotation_text=label, annotation_position="top left")

    T1_str = f"{res_iec.get('T1', 0):.3f}" if res_iec.get("T1") is not None else "—"
    T2_str = f"{res_iec.get('T2', 0):.2f}" if res_iec.get("T2") is not None else "—"
    beta_str = f"{res_iec.get('beta_pct', 0):.2f}" if res_iec.get("beta_pct") is not None else "—"
    O1_str = f"{res_iec.get('O1', 0):.4f}" if res_iec.get("O1") is not None else "—"

    subtitulo = f"T1 = {T1_str} µs · T2 = {T2_str} µs · β' = {beta_str} % · O1 = {O1_str} µs"
    fig.update_layout(
        title=f"Evaluación Normativa IEC 60060-1 (CH1 Seg {seg})<br><sub>{subtitulo}</sub>",
        xaxis_title="Tiempo [µs]", yaxis_title="Tensión [mV]",
        height=380, margin=dict(t=65, b=40, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=1.05, x=0),
    )
    return fig


def figura_dispersion_lag(resultados: dict) -> go.Figure:
    """Subplots (1x2): Dispersión de t_lag por segmento e Histograma de frecuencias."""
    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True,
        column_widths=[0.7, 0.3], horizontal_spacing=0.03,
        subplot_titles=["Retardo instrumental t_lag por disparo", "Distribución"]
    )
    if not resultados:
        fig.update_layout(height=300, plot_bgcolor="white", paper_bgcolor="white")
        return fig

    ch = resultados.get("canal", "ch")
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
        height=320, margin=dict(t=40, b=40, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=1.12, x=0),
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
