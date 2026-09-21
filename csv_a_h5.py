"""
Convierte los CSV exportados de Keysight Infiniium (formato "pares tiempo/tensión
por segmento", uno por canal: CH1.csv..CH4.csv) al mismo esquema HDF5 (.h5) que
leen app.py, calibrar_app y cadencia.py de TRPD_APP.

Formato de entrada esperado (verificado contra los CSV reales de
mediciones/old_paper/tabla_1/{1v,2v,3v,4v}/CH{1..4}.csv):
  - Filas 1-25 (índices 0-24): metadatos, una fila por atributo, un valor por
    segmento en las columnas 1..N (col 0 = etiqueta). Orden fijo verificado:
    0 Header ("" + "Channel k" x N)
    1 Revision            7 XDispOrg         13 YDispOrg        19 Date
    2 Type                8 XInc             14 YInc            20 Time
    3 Start               9 XOrg             15 YOrg            21 Time Since Seg 1::
    4 Points             10 Units (Second)   16 Units (Volt)    22 Max Bandwidth
    5 Count              11 XReference       17 YReference      23 Min Bandwidth
    6 XDispRange         12 YDispRange       18 Frame           24 sub-header "Time Tags"
  - Filas 26+ : datos. Cada fila tiene 2*N columnas (SIN columna de etiqueta):
    tiempo_seg1, volt_seg1, tiempo_seg2, volt_seg2, ..., tiempo_segN, volt_segN.
    Los valores de tensión ya están en voltios físicos (no son códigos ADC crudos).

Esquema de salida (idéntico al de un .h5 real de este proyecto, verificado con
h5py sobre mediciones/Mediciones/mediciones_filtros/cada_30s/7/ch1.h5):
  /FileType/KeysightH5FileType         dataset escalar |S40 = b"Keysight Waveform"
  /Frame/TheFrame                      dataset escalar compuesto (Model,Serial,Date)
  /Waveforms  (attrs: NumWaveforms)
    /Waveforms/Channel <n>             grupo con attrs YInc,YOrg,XInc,XOrg,NumSegments,
                                        NumPoints,XDispRange,XDispOrigin,YDispRange,
                                        YDispOrigin,YReference,XUnits,YUnits, etc.
      /Channel <n> Seg<k>Data          dataset int16, shape (NumPoints,), con attrs
                                        SegmentedTimeTag, SegmentedXOrg, StartIndex, etc.

Los valores de tensión (ya en voltios en el CSV) se re-codifican a enteros int16
"crudos" con raw = round((v - YOrg) / YInc), exactamente el inverso de la fórmula
que usa app.py para decodificar (`v = raw*YInc + YOrg`). Esto reproduce con
fidelidad de sub-mV el mismo formato que ya usan todas las mediciones del
proyecto (ver cargar_segmento en app.py / calibrar_app/datos.py).

Uso:
    python csv_a_h5.py <carpeta> [--forzar]
        Convierte CH1.csv..CH4.csv -> ch1.h5..ch4.h5 dentro de <carpeta>.
        Si ya existe chN.h5 no lo toca, salvo --forzar.

    python csv_a_h5.py --raiz <carpeta_raiz> [--forzar]
        Recorre <carpeta_raiz> recursivamente y convierte cada subcarpeta que
        contenga al menos un CH?.csv (case-insensitive).

Ejemplo real de este proyecto:
    python csv_a_h5.py --raiz "../mediciones/old_paper/tabla_1"
"""
from __future__ import annotations

import csv
import glob
import os
import re
import sys

import h5py
import numpy as np

# Filas de metadatos (0-indexadas) según el formato verificado — ver docstring.
N_FILAS_CABECERA = 25
IDX = {
    "revision": 1, "type": 2, "start": 3, "points": 4, "count": 5,
    "xdisprange": 6, "xdisporg": 7, "xinc": 8, "xorg": 9, "units_t": 10,
    "xreference": 11, "ydisprange": 12, "ydisporg": 13, "yinc": 14, "yorg": 15,
    "units_v": 16, "yreference": 17, "frame": 18, "date": 19, "time": 20,
    "timetag": 21, "maxbw": 22, "minbw": 23,
}
ETIQUETAS_ESPERADAS = {
    1: "Revision:", 3: "Start:", 4: "Points:", 6: "XDispRange:", 7: "XDispOrg:",
    8: "XInc:", 9: "XOrg:", 12: "YDispRange:", 13: "YDispOrg:", 14: "YInc:",
    15: "YOrg:", 18: "Frame:", 19: "Date:", 20: "Time:",
}

_CH_CSV_RE = re.compile(r"^ch([1-4])\.csv$", re.IGNORECASE)


def _leer_cabecera(ruta_csv):
    """Lee las 25 filas de metadatos y valida el formato esperado.

    Devuelve (filas, nseg, nombre_canal) con filas = lista de 25 listas de str.
    """
    with open(ruta_csv, "r", newline="") as f:
        reader = csv.reader(f)
        filas = [next(reader) for _ in range(N_FILAS_CABECERA)]

    nseg = len(filas[0]) - 1
    if nseg <= 0:
        raise ValueError(f"{ruta_csv}: no se detectaron columnas de segmento en la cabecera")

    for idx, etiqueta in ETIQUETAS_ESPERADAS.items():
        real = filas[idx][0].strip()
        if real != etiqueta:
            raise ValueError(
                f"{ruta_csv}: fila {idx} esperaba etiqueta '{etiqueta}', encontró '{real}'. "
                "El formato del CSV no coincide con el esperado por este script."
            )

    nombre_canal = filas[0][1].strip()  # p.ej. "Channel 1"
    return filas, nseg, nombre_canal


def _valor_unico(filas, fila_idx, caster=float):
    """Toma el primer valor de una fila de metadatos (asume constante entre segmentos)."""
    return caster(filas[fila_idx][1].strip())


def _valores_por_segmento(filas, fila_idx, nseg, caster=float):
    return [caster(filas[fila_idx][1 + k].strip()) for k in range(nseg)]


def _leer_datos(ruta_csv, nseg):
    """Lee la matriz de tensiones (NumPoints x nseg), en voltios, decimando la
    columna de tiempo (no se usa: el eje temporal real se reconstruye desde
    XOrg/XInc de la cabecera, igual que hace _meta()/cargar_segmento en la app)."""
    usecols = range(1, 2 * nseg, 2)  # columnas impares = tensión de cada segmento
    return np.loadtxt(ruta_csv, delimiter=",", skiprows=N_FILAS_CABECERA,
                       usecols=usecols, dtype=np.float64)


def convertir_archivo(ruta_csv, ruta_h5, forzar=False, log=print):
    """Convierte un CSV de un canal (CH<n>.csv) al .h5 con el esquema del proyecto."""
    if os.path.exists(ruta_h5) and not forzar:
        log(f"  Ya existe, no se sobrescribe: {ruta_h5}")
        return False

    log(f"  Leyendo cabecera de {os.path.basename(ruta_csv)} ...")
    filas, nseg, nombre_canal = _leer_cabecera(ruta_csv)

    points = int(_valor_unico(filas, IDX["points"], int))
    count_val = int(_valor_unico(filas, IDX["count"], int))
    start_val = int(_valor_unico(filas, IDX["start"], int))
    xdisprange = _valor_unico(filas, IDX["xdisprange"])
    xdisporg = _valor_unico(filas, IDX["xdisporg"])
    xinc = _valor_unico(filas, IDX["xinc"])
    ydisprange = _valor_unico(filas, IDX["ydisprange"])
    ydisporg = _valor_unico(filas, IDX["ydisporg"])
    yinc = _valor_unico(filas, IDX["yinc"])
    yorg = _valor_unico(filas, IDX["yorg"])
    yreference = int(_valor_unico(filas, IDX["yreference"], int))
    maxbw = _valor_unico(filas, IDX["maxbw"])
    minbw = _valor_unico(filas, IDX["minbw"])

    xorg_seg = _valores_por_segmento(filas, IDX["xorg"], nseg)
    timetag_seg = _valores_por_segmento(filas, IDX["timetag"], nseg)

    frame_str = filas[IDX["frame"]][1].strip()
    modelo, _, serial = frame_str.partition(":")
    fecha_str = filas[IDX["date"]][1].strip()
    hora_str = filas[IDX["time"]][1].strip()
    fecha_hora = f"{fecha_str} {hora_str}"

    log(f"  Leyendo {points} muestras x {nseg} segmentos (esto puede tardar ~30-60 s) ...")
    datos_v = _leer_datos(ruta_csv, nseg)  # shape (points, nseg), en voltios
    if datos_v.shape != (points, nseg):
        raise ValueError(
            f"{ruta_csv}: se esperaban {points}x{nseg} muestras, se leyeron {datos_v.shape}"
        )

    raw = np.round((datos_v - yorg) / yinc)
    n_clip = int(np.sum((raw < -32768) | (raw > 32767)))
    if n_clip:
        log(f"  ADVERTENCIA: {n_clip} muestras fuera de rango int16, se recortan (clip).")
    raw = np.clip(raw, -32768, 32767).astype(np.int16)

    os.makedirs(os.path.dirname(ruta_h5), exist_ok=True)
    tmp_path = ruta_h5 + ".tmp"
    with h5py.File(tmp_path, "w") as f:
        ft = f.create_group("FileType")
        ft.create_dataset("KeysightH5FileType", data=np.bytes_("Keysight Waveform"),
                           dtype="S40")

        frame_dt = np.dtype([("Model", "S12"), ("Serial", "S12"), ("Date", "S22")])
        frame_val = np.array(
            (modelo.strip().encode(), serial.strip().encode(), fecha_hora.encode()),
            dtype=frame_dt,
        )
        fr = f.create_group("Frame")
        fr.create_dataset("TheFrame", data=frame_val, dtype=frame_dt)

        wf = f.create_group("Waveforms")
        wf.attrs["NumWaveforms"] = np.int32(nseg)

        g = wf.create_group(nombre_canal)
        g.attrs["ColorGradeHeight"] = np.int32(0)
        g.attrs["ColorGradeWidth"] = np.int32(0)
        g.attrs["Count"] = np.int32(count_val)
        g.attrs["DispInterpFactor"] = np.int32(1)
        g.attrs["FFT_RBW"] = np.float64(0.0)
        g.attrs["InterpSetting"] = np.int16(1)
        g.attrs["MaxBandwidth"] = np.float64(maxbw)
        g.attrs["MinBandwidth"] = np.float64(minbw)
        g.attrs["NumPoints"] = np.int32(points)
        g.attrs["NumSegments"] = np.int32(nseg)
        g.attrs["SavedInterpFactor"] = np.int32(1)
        g.attrs["Start"] = np.int32(start_val)
        g.attrs["WavAttr"] = np.int32(0)
        g.attrs["WaveformType"] = np.int16(1)
        g.attrs["XDispOrigin"] = np.float64(xdisporg)
        g.attrs["XDispRange"] = np.float32(xdisprange)
        g.attrs["XInc"] = np.float64(xinc)
        g.attrs["XOrg"] = np.float64(xorg_seg[0])
        g.attrs["XUnits"] = np.bytes_("Second")
        g.attrs["YDispOrigin"] = np.float64(ydisporg)
        g.attrs["YDispRange"] = np.float32(ydisprange)
        g.attrs["YInc"] = np.float64(yinc)
        g.attrs["YOrg"] = np.float64(yorg)
        g.attrs["YReference"] = np.int32(yreference)
        g.attrs["YUnits"] = np.bytes_("Volt")

        for k in range(nseg):
            seg = k + 1
            ds = g.create_dataset(f"{nombre_canal} Seg{seg}Data", data=raw[:, k])
            ds.attrs["DataType"] = np.int32(1)
            ds.attrs["DecMode"] = np.int32(0)
            ds.attrs["InfoValid"] = np.int32(1)
            ds.attrs["LfdSeed"] = np.int32(0)
            ds.attrs["MemConIntlvMode"] = np.int32(0)
            ds.attrs["PktSize"] = np.int32(1)
            ds.attrs["RawNumPts"] = np.int32(points)
            ds.attrs["ReductionAllowed"] = np.int32(points)
            ds.attrs["SegmentedTimeTag"] = np.float64(timetag_seg[k])
            ds.attrs["SegmentedXOrg"] = np.float64(xorg_seg[k])
            ds.attrs["StartIndex"] = np.int32(start_val)

    os.replace(tmp_path, ruta_h5)
    log(f"  OK -> {ruta_h5} ({nseg} segmentos x {points} muestras)")
    return True


def convertir_carpeta(carpeta, forzar=False, log=print):
    """Convierte CH1.csv..CH4.csv -> ch1.h5..ch4.h5 dentro de una carpeta."""
    convertidos = 0
    for ruta_csv in sorted(glob.glob(os.path.join(carpeta, "*.csv"))):
        m = _CH_CSV_RE.match(os.path.basename(ruta_csv))
        if not m:
            continue
        n = m.group(1)
        ruta_h5 = os.path.join(carpeta, f"ch{n}.h5")
        log(f"{carpeta} :: CH{n}.csv -> ch{n}.h5")
        try:
            if convertir_archivo(ruta_csv, ruta_h5, forzar=forzar, log=log):
                convertidos += 1
        except Exception as e:
            log(f"  ERROR convirtiendo {ruta_csv}: {e}")
    return convertidos


def convertir_raiz(raiz, forzar=False, log=print):
    """Recorre <raiz> recursivamente y convierte cada carpeta con CH?.csv."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(raiz):
        if any(_CH_CSV_RE.match(fn) for fn in filenames):
            total += convertir_carpeta(dirpath, forzar=forzar, log=log)
    return total


def main():
    args = sys.argv[1:]
    forzar = "--forzar" in args
    args = [a for a in args if a != "--forzar"]

    if len(args) >= 2 and args[0] == "--raiz":
        n = convertir_raiz(args[1], forzar=forzar)
        print(f"\nTotal convertidos: {n}")
    elif len(args) == 1:
        n = convertir_carpeta(args[0], forzar=forzar)
        print(f"\nTotal convertidos: {n}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
