"""Reproduce el análisis TRPD de una medición solo a partir de su metadata.yaml.

Lee de metadata.yaml, para cada canal trigger (ch2, ch3, ch4):
  - canales.<ch>.trigger: umbral_mv, distancia_us, tmin_us y filtrado (lo guarda
    app.py al pulsar «Calcular peaks» / «Calcular todos los sensores»);
  - ediciones_peaks.<ch>.historial: peaks añadidos, quitados y disparos excluidos;
  - calibracion_retardo.<ch>.t_lag_ns: retardo del sensor (t_abs).
y recalcula los peaks con las mismas funciones que la app, de modo que el conteo,
la tabla de densidad (N_PD, V̄_pp, t̄_abs) y el mapa TRPD salen idénticos.

Uso:
    python reproducir_trpd.py <medición> [<medición> ...] [--csv salida.csv]

<medición> es la carpeta con ch1..ch4.h5 (o una carpeta que las contenga: se
recorren todas). Los canales sin trigger guardado se omiten con aviso.
"""
import os
import sys

import numpy as np

import app
import rutas
from generate_metadata import buscar_mediciones


def trigger_guardado(carpeta, canal):
    """{umbral, dist, tmin, filtrado} guardado en canales.<canal>.trigger, o None."""
    trig = ((app.obtener_metadata(carpeta).get("canales") or {}).get(canal) or {}).get("trigger")
    if not isinstance(trig, dict) or trig.get("umbral_mv") is None:
        return None
    dist, tmin = trig.get("distancia_us"), trig.get("tmin_us")
    return {
        "umbral": float(trig["umbral_mv"]),
        "dist": float(app.DIST_DEFECTO_US if dist is None else dist),
        "tmin": float(app.TMIN_DEFECTO_US if tmin is None else tmin),
        "filtrado": bool(trig.get("filtrado", True)),
    }


def lag_guardado_us(carpeta, canal):
    """Retardo del sensor (µs) según calibracion_retardo de metadata.yaml (0 sin
    calibrar), el mismo que usa la app."""
    return app.lag_canal(app.calibracion_desde_metadata(carpeta), carpeta, canal)


def resultado_canal(carpeta, canal):
    """Captura editada, conteo por disparo y fila de la tabla del canal, o None si
    el canal no tiene trigger guardado."""
    cfg = trigger_guardado(carpeta, canal)
    if cfg is None or canal not in app.canales_presentes(carpeta):
        return None
    ed = app.ediciones_canal(carpeta, canal)
    t_lag = lag_guardado_us(carpeta, canal)
    args = (carpeta, canal, cfg["umbral"], cfg["dist"], cfg["tmin"])
    cap = app.captura_editada(*args, filtrado=cfg["filtrado"], ediciones=ed)
    segs, cuentas = app.contar_peaks(*args, ediciones=ed, filtrado=cfg["filtrado"])
    fila = app.calcular_fila_densidad(*args, t_lag_us=t_lag, ediciones=ed, filtrado=cfg["filtrado"])
    return {"canal": canal, "cfg": cfg, "t_lag_us": t_lag, "cap": cap,
            "t_abs": app.t_abs_captura(cap, t_lag), "segs": segs, "cuentas": cuentas,
            "fila": fila, "n_ediciones": len(ed["historial"])}


def resultado_medicion(carpeta):
    """{canal: resultado_canal} de los canales trigger con trigger guardado."""
    out = {}
    for ch in app.TRIGGERS:
        r = resultado_canal(carpeta, ch)
        if r is None:
            print(f"Aviso: {rutas.etiqueta(carpeta)} {ch.upper()} sin trigger guardado; se omite.")
        else:
            out[ch] = r
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_out = None
    if "--csv" in sys.argv:
        i = sys.argv.index("--csv")
        csv_out = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        args = [a for a in args if a != csv_out]
    if not args:
        print(__doc__)
        sys.exit(1)
    mediciones = []
    for a in args:
        ruta = os.path.abspath(a)
        mediciones += [ruta] if rutas.canales_presentes(ruta) else buscar_mediciones(ruta)

    filas = []
    for carpeta in mediciones:
        for ch, r in resultado_medicion(carpeta).items():
            f, c = r["fila"], r["cfg"]
            filas.append(f)
            print(f"{rutas.etiqueta(carpeta):<20} {ch.upper()}  umbral={c['umbral']:g} mV "
                  f"Δt={c['dist']:g} µs t_mín={c['tmin']:g} µs "
                  f"{'filtrado' if c['filtrado'] else 'sin filtro'} | "
                  f"{int(np.sum(r['cuentas']))} peaks, {r['n_ediciones']} ediciones | "
                  f"N_PD {f['distribucion']}  N_PD=N_cav {f['n_coinc']}  "
                  f"V̄pp {f['vpp_media']} V  t̄abs {f['tabs_media']} µs")
    if csv_out:
        with open(csv_out, "w", encoding="utf-8", newline="") as fh:
            fh.write(app.csv_tabla_densidad(filas))
        print(f"Tabla guardada en {csv_out}")


if __name__ == "__main__":
    main()
