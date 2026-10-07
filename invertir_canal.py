"""Copia una medición invirtiendo la polaridad de un canal (p. ej. HFCT montado al revés).

Copia <origen> (una probeta <probeta>/<X>kV/chN.h5 o una sola carpeta <X>kV) en <destino> y, en el
chN.h5 del canal indicado, cambia de signo YInc e YOrg: como la app lee v = raw·YInc + YOrg, la
señal queda exactamente −v sin reescribir las muestras. El original no se toca. Cada archivo
invertido lleva el atributo TRPD_polaridad_invertida en el grupo del canal.

Uso:
    python invertir_canal.py <origen> <destino> [--canal ch2]
"""

import argparse
import os
import shutil
import sys

import h5py

ATRIBUTO = "TRPD_polaridad_invertida"


def invertir_h5(ruta):
    with h5py.File(ruta, "r+") as f:
        for nombre, g in f["Waveforms"].items():
            if ATRIBUTO in g.attrs:
                raise SystemExit(f"{ruta}: '{nombre}' ya estaba invertido")
            g.attrs["YInc"] = -g.attrs["YInc"]
            g.attrs["YOrg"] = -g.attrs["YOrg"]
            g.attrs[ATRIBUTO] = "YInc e YOrg cambiados de signo (sensor montado al revés)"


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("origen")
    ap.add_argument("destino")
    ap.add_argument("--canal", default="ch2")
    a = ap.parse_args()
    if os.path.exists(a.destino):
        sys.exit(f"El destino ya existe: {a.destino}")
    shutil.copytree(a.origen, a.destino)
    n = 0
    for raiz, _, archivos in os.walk(a.destino):
        if f"{a.canal}.h5" in archivos:
            invertir_h5(os.path.join(raiz, f"{a.canal}.h5"))
            print(f"invertido: {os.path.join(raiz, a.canal + '.h5')}", flush=True)
            n += 1
    print(f"{n} archivos {a.canal}.h5 invertidos en {a.destino}")


if __name__ == "__main__":
    main()
