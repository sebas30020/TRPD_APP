"""Pipeline normativo para cálculo de parámetros de impulso según IEC 60060-1:2010.

Implementa el procedimiento del Anexo B (procedimiento de evaluación de software) y
Anexo C (guía informativa de implementación), validable según IEC 61083-2.
Módulo puro: sin I/O, sin Dash.
"""

from __future__ import annotations
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter

A_FILTRO_K = 2.2e-12  # s², constante de k(f) = 1/(1 + 2.2 f²), f en MHz
TOL = {
    "T1": (0.84, 1.56),       # µs, 1.2 µs ± 30%
    "T2": (40.0, 60.0),       # µs, 50.0 µs ± 20%
    "beta_max_pct": 10.0,     # % máx sobreoscilación
}


def compensar_base(u_raw: np.ndarray, n_pre: int, pol: int = 1) -> tuple[np.ndarray, float]:
    """Compensa polaridad y nivel base (offset) previo al disparo.

    u0 = pol * u_raw - media(pol * u_raw[:n_pre])
    """
    u = pol * np.asarray(u_raw, dtype=np.float64)
    n = max(1, min(int(n_pre), u.size))
    u_base = float(np.mean(u[:n]))
    u0 = u - u_base
    return u0, u_base


def valor_extremo(u0: np.ndarray, suavizado_muestras: int = 0) -> tuple[float, int]:
    """Determina Ue y el índice del pico máximo.

    Si suavizado_muestras > 0, busca el índice en la señal suavizada pero
    toma el valor de u0 en ese índice.
    """
    if suavizado_muestras > 1 and u0.size > suavizado_muestras:
        # Mediana móvil o filtro de caja para reducir sensibilidad al ruido
        kernel = np.ones(suavizado_muestras) / suavizado_muestras
        u_suave = np.convolve(u0, kernel, mode="same")
        i_pk = int(np.argmax(u_suave))
        ue = float(u0[i_pk])
    else:
        i_pk = int(np.argmax(u0))
        ue = float(u0[i_pk])
    return ue, i_pk


def ventana_ajuste(u0: np.ndarray, Ue: float, i_pk: int) -> tuple[int, int]:
    """Determina índices (d, e) para la ventana de ajuste [d+1, e] según Anexo B pasos d–f.

    d = último índice en el frente (i < i_pk) con u0[i] < 0.2 * Ue
    e = último índice en la cola (i > i_pk) con u0[i] > 0.4 * Ue
    """
    frente = u0[:i_pk]
    cands_d = np.nonzero(frente < 0.2 * Ue)[0]
    d = int(cands_d[-1]) if cands_d.size else 0

    cola = u0[i_pk:]
    cands_e = np.nonzero(cola > 0.4 * Ue)[0]
    e = int(cands_e[-1] + i_pk) if cands_e.size else int(u0.size - 1)
    return d, e


def curva_base(t_us: np.ndarray, U: float, tau1: float, tau2: float, td: float) -> np.ndarray:
    """Evalúa la curva base doble exponencial Um(t) sin overflow."""
    t = np.asarray(t_us, dtype=np.float64)
    out = np.zeros_like(t)
    mask = t >= td
    if not np.any(mask):
        return out
    t_pos = t[mask] - td
    t1 = max(float(tau1), 1e-9)
    t2 = max(float(tau2), 1e-9)
    arg1 = np.clip(-t_pos / t1, -700.0, 700.0)
    arg2 = np.clip(-t_pos / t2, -700.0, 700.0)
    out[mask] = U * (np.exp(arg1) - np.exp(arg2))
    return out


def ajustar_curva_base(t_us: np.ndarray, u0: np.ndarray, d: int, e: int, Ue: float,
                       diezmado: int = 1) -> dict:
    """Ajusta los parámetros U, tau1, tau2, td de la curva base por Levenberg-Marquardt

    con la normalización recomendada en el Anexo C.1.
    """
    ts = t_us[d + 1:e + 1]
    us = u0[d + 1:e + 1]
    if diezmado > 1 and ts.size > diezmado * 10:
        ts = ts[::diezmado]
        us = us[::diezmado]

    if ts.size < 4 or Ue <= 0:
        return {
            "exito": False,
            "U": float(Ue), "tau1": 70.0, "tau2": 0.4, "td": float(t_us[0]),
            "mensaje": "Muestras insuficientes para ajuste"
        }

    span = float(ts[-1] - ts[0])
    if span <= 0:
        span = 1.0

    x = (ts - ts[0]) / span
    y = us / Ue

    def model(p, x_arr):
        p1 = max(p[1], 1e-6)
        p2 = max(p[2], 1e-6)
        arg = x_arr - p[3]
        e1 = np.exp(np.clip(-arg / p1, -700.0, 700.0))
        e2 = np.exp(np.clip(-arg / p2, -700.0, 700.0))
        return p[0] * (e1 - e2)

    p0 = [1.0, 70.0 / span, 0.4 / span, -float(ts[0]) / span]

    exito = True
    mensaje = "OK"
    try:
        r = least_squares(lambda p: model(p, x) - y, p0, method="lm", max_nfev=20000)
        p_opt = r.x
        if not r.success:
            raise RuntimeError(r.message)
    except Exception:
        # Reintento con TRF acotado
        try:
            r = least_squares(
                lambda p: model(p, x) - y, p0, method="trf",
                bounds=([0.1, 0.1 / span, 0.001 / span, -5.0], [5.0, 1000.0 / span, 50.0 / span, 5.0]),
                max_nfev=20000
            )
            p_opt = r.x
            exito = r.success
            mensaje = r.message if not exito else "OK (TRF)"
        except Exception as e2:
            p_opt = p0
            exito = False
            mensaje = f"Fallo ajuste: {e2}"

    U_rec = float(p_opt[0] * Ue)
    tau1_rec = float(p_opt[1] * span)
    tau2_rec = float(p_opt[2] * span)
    td_rec = float(p_opt[3] * span + ts[0])

    return {
        "exito": exito,
        "U": U_rec,
        "tau1": tau1_rec,
        "tau2": tau2_rec,
        "td": td_rec,
        "mensaje": mensaje,
    }


def coeficientes_k(dt_s: float) -> tuple[float, float]:
    """Calcula coeficientes (b0, a1) del filtro IIR de la función de ensayo k(f).

    dt_s: tiempo de muestreo en SEGUNDOS (Ts).
    Retorna (b0, a1) con >= 6 cifras significativas.
    """
    assert dt_s < 1e-6, f"dt_s debe estar en segundos (< 1e-6 s), recibido: {dt_s}"
    x = float(np.tan(np.pi * dt_s / np.sqrt(A_FILTRO_K)))
    b0 = x / (1.0 + x)
    a1 = (1.0 - x) / (1.0 + x)
    return b0, a1


def filtro_k(x: np.ndarray, dt_s: float) -> np.ndarray:
    """Filtro de la función de tensión de ensayo k(f) = 1/(1 + 2.2 f²), f en MHz.

    Implementación vectorizada de fase cero idéntica a la doble pasada de §7:
    primera pasada sobre el array invertido (luego reinvertido) y segunda hacia adelante.
    """
    x_arr = np.asarray(x, dtype=np.float64)
    if x_arr.size == 0:
        return np.array([], dtype=np.float64)
    b0, a1 = coeficientes_k(dt_s)
    b = np.array([b0, b0], dtype=np.float64)
    a = np.array([1.0, -a1], dtype=np.float64)
    # Primera pasada hacia atrás
    y1 = lfilter(b, a, np.ascontiguousarray(x_arr[::-1]))[::-1]
    # Segunda pasada hacia adelante
    y2 = lfilter(b, a, np.ascontiguousarray(y1))
    return np.ascontiguousarray(y2)


def respuesta_k(f_mhz: np.ndarray) -> np.ndarray:
    """Respuesta teórica analítica de k(f) = 1 / (1 + 2.2 * f^2), con f en MHz."""
    f = np.asarray(f_mhz, dtype=np.float64)
    return 1.0 / (1.0 + 2.2 * (f ** 2))


def cruce_frente_ultimo(t: np.ndarray, u: np.ndarray, nivel: float, i_pk: int) -> float | None:
    """Último cruce ascendente de nivel antes de i_pk con interpolación lineal sub-muestra.

    Corrige el bug de P7 que devolvía el primer cruce.
    """
    if i_pk <= 0 or i_pk > u.size:
        return None
    frente = u[:i_pk]
    # Buscar el último índice j < i_pk donde u[j] < nivel y u[j+1] >= nivel
    sub = (frente[:-1] < nivel) & (frente[1:] >= nivel)
    idx = np.nonzero(sub)[0]
    if idx.size == 0:
        # Fallback: si toda la señal sobrepasa el nivel o no cruza
        if frente[0] >= nivel:
            return float(t[0])
        return None
    j = int(idx[-1])
    du = u[j + 1] - u[j]
    if du <= 0:
        return float(t[j])
    return float(t[j] + (nivel - u[j]) * (t[j + 1] - t[j]) / du)


def cruce_frente_primero(t: np.ndarray, u: np.ndarray, nivel: float, i_pk: int) -> float | None:
    """Primer cruce ascendente de nivel antes de i_pk con interpolación lineal sub-muestra."""
    if i_pk <= 0 or i_pk > u.size:
        return None
    frente = u[:i_pk]
    sub = (frente[:-1] < nivel) & (frente[1:] >= nivel)
    idx = np.nonzero(sub)[0]
    if idx.size == 0:
        if frente[0] >= nivel:
            return float(t[0])
        return None
    j = int(idx[0])
    du = u[j + 1] - u[j]
    if du <= 0:
        return float(t[j])
    return float(t[j] + (nivel - u[j]) * (t[j + 1] - t[j]) / du)


def cruce_cola(t: np.ndarray, u: np.ndarray, nivel: float, i_pk: int) -> float | None:
    """Primer cruce descendente de nivel después de i_pk con interpolación lineal sub-muestra."""
    if i_pk < 0 or i_pk >= u.size - 1:
        return None
    cola = u[i_pk:]
    sub = (cola[:-1] >= nivel) & (cola[1:] < nivel)
    idx = np.nonzero(sub)[0]
    if idx.size == 0:
        return None
    j = int(idx[0] + i_pk)
    du = u[j + 1] - u[j]
    if du == 0:
        return float(t[j])
    return float(t[j] + (nivel - u[j]) * (t[j + 1] - t[j]) / du)


def veredicto_tolerancias(Ut: float, T1: float, T2: float, beta_pct: float) -> dict:
    """Verifica cumplimiento de tolerancias normativas IEC 60060-1 (7.2.2)."""
    ok_t1 = (TOL["T1"][0] <= T1 <= TOL["T1"][1]) if T1 is not None else False
    ok_t2 = (TOL["T2"][0] <= T2 <= TOL["T2"][1]) if T2 is not None else False
    ok_beta = (beta_pct <= TOL["beta_max_pct"]) if beta_pct is not None else False
    valido = bool(ok_t1 and ok_t2 and ok_beta)
    return {
        "conforme": valido,
        "ok_T1": ok_t1,
        "ok_T2": ok_t2,
        "ok_beta": ok_beta,
        "detalles": f"T1={T1:.3f}µs({'OK' if ok_t1 else 'FAIL'}), T2={T2:.2f}µs({'OK' if ok_t2 else 'FAIL'}), β'={beta_pct:.2f}%({'OK' if ok_beta else 'FAIL'})"
    }


def evaluar_impulso(t_us: np.ndarray, u_raw: np.ndarray, dt_s: float, n_pre: int,
                     pol: int = 1, diezmado_ajuste: int = 1, suavizado_ue_ns: float = 0.0,
                     con_curva: bool = False) -> dict:
    """Evalúa un impulso tipo rayo completo según el procedimiento del Anexo B de IEC 60060-1.

    Entradas:
      t_us: vector temporal en microsegundos
      u_raw: vector de tensión cruda
      dt_s: intervalo de muestreo en segundos
      n_pre: número de muestras para línea base
      pol: polaridad (+1 o -1)
      diezmado_ajuste: factor de diezmado para el ajuste LM (acelera cómputo)
      suavizado_ue_ns: suavizado en ns para Ue si la señal es ruidosa
      con_curva: si True, retorna Ut_curva y Um en el dict

    Retorna diccionario con parámetros normativos (Ut, T1, T2, O1, beta, etc.).
    """
    assert dt_s < 1e-6, f"dt_s debe estar en segundos (< 1e-6), valor: {dt_s}"
    u0, u_base = compensar_base(u_raw, n_pre, pol=pol)
    dt_us = dt_s * 1e6
    suav_muestras = int(round(suavizado_ue_ns / dt_us)) if (suavizado_ue_ns > 0 and dt_us > 0) else 0

    Ue, i_pk = valor_extremo(u0, suavizado_muestras=suav_muestras)
    if Ue <= 0 or i_pk <= 0:
        return {"exito": False, "mensaje": "Pico máximo de tensión no detectable"}

    d, e = ventana_ajuste(u0, Ue, i_pk)
    ajuste = ajustar_curva_base(t_us, u0, d, e, Ue, diezmado=diezmado_ajuste)

    Um = curva_base(t_us, ajuste["U"], ajuste["tau1"], ajuste["tau2"], ajuste["td"])
    residual = u0 - Um
    Rf = filtro_k(residual, dt_s)
    Utc = Um + Rf

    Ut = float(np.max(Utc))
    i_pk_t = int(np.argmax(Utc))
    Ub = float(np.max(Um)) if Um.size else 0.0
    beta_pct = float(100.0 * (Ue - Ub) / Ue) if Ue > 0 else 0.0

    # P9: Cruces de umbral
    t10 = cruce_frente_ultimo(t_us, Utc, 0.10 * Ut, i_pk_t)
    t30 = cruce_frente_ultimo(t_us, Utc, 0.30 * Ut, i_pk_t)
    t90 = cruce_frente_primero(t_us, Utc, 0.90 * Ut, i_pk_t)
    t50 = cruce_cola(t_us, Utc, 0.50 * Ut, i_pk_t)

    if t30 is not None and t90 is not None:
        T = float(t90 - t30)
        T1 = float(T / 0.6)
        O1 = float(t30 - 0.3 * T1)
    else:
        T = T1 = O1 = None

    T2 = float(t50 - O1) if (t50 is not None and O1 is not None) else None
    veredicto = veredicto_tolerancias(Ut, T1, T2, beta_pct)

    res = {
        "exito": True,
        "Ue": Ue,
        "Ut": Ut,
        "Ub": Ub,
        "beta_pct": beta_pct,
        "t10": t10,
        "t30": t30,
        "t90": t90,
        "t50": t50,
        "T": T,
        "T1": T1,
        "O1": O1,
        "T2": T2,
        "tau1": ajuste["tau1"],
        "tau2": ajuste["tau2"],
        "td": ajuste["td"],
        "exito_ajuste": ajuste["exito"],
        "veredicto": veredicto,
    }
    if con_curva:
        res["u0"] = u0
        res["Um"] = Um
        res["Ut_curva"] = Utc
    return res
