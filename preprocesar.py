"""
Preprocesado: filtro paso-alto de 5 MHz al canal 2.

Lee ch2.h5, aplica un Butterworth paso-alto (fase cero) a cada segmento sobre la
senal completa, y escribe un archivo extra `ch2_hp5MHz.h5` con la MISMA estructura
que los originales (mismos nombres de grupo/dataset), pero con los datos ya en
voltios (YInc=1, YOrg=0) para que la app lo cargue sin cambios.

Ejecutar:  python3 preprocesar.py
"""
import os

import h5py
import numpy as np
from scipy.signal import butter, sosfiltfilt

AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(AQUI, "ch2.h5")
DESTINO = os.path.join(AQUI, "ch2_hp5MHz.h5")

FCORTE = 5e6   # Hz, frecuencia de corte del paso-alto
ORDEN = 4      # orden del Butterworth


def main():
    with h5py.File(ORIGEN, "r") as fin:
        chan = list(fin["Waveforms"].keys())[0]           # "Channel 2"
        gin = fin["Waveforms/" + chan]
        xinc, xorg = float(gin.attrs["XInc"]), float(gin.attrs["XOrg"])
        yinc, yorg = float(gin.attrs["YInc"]), float(gin.attrs["YOrg"])
        nsegs = int(gin.attrs["NumSegments"])
        npts = int(gin.attrs["NumPoints"])

        fs = 1.0 / xinc
        sos = butter(ORDEN, FCORTE, btype="highpass", fs=fs, output="sos")
        print(f"Fs = {fs:.3e} Sa/s | paso-alto {FCORTE/1e6:.1f} MHz (Butterworth orden {ORDEN})")

        with h5py.File(DESTINO, "w") as fout:
            gout = fout.create_group("Waveforms/" + chan)
            # Datos ya en voltios -> escala identidad
            gout.attrs["YInc"] = 1.0
            gout.attrs["YOrg"] = 0.0
            gout.attrs["XInc"] = xinc
            gout.attrs["XOrg"] = xorg
            gout.attrs["NumSegments"] = nsegs
            gout.attrs["NumPoints"] = npts
            gout.attrs["Filtro"] = f"highpass Butterworth {FCORTE:.0f} Hz orden {ORDEN}"

            for s in range(1, nsegs + 1):
                raw = gin[f"{chan} Seg{s}Data"][:]
                v = raw.astype(np.float64) * yinc + yorg
                vf = sosfiltfilt(sos, v).astype(np.float32)
                gout.create_dataset(f"{chan} Seg{s}Data", data=vf, compression="gzip", compression_opts=1)
                if s == 1 or s % 10 == 0 or s == nsegs:
                    print(f"  segmento {s}/{nsegs} filtrado")

    print("Archivo extra generado:", DESTINO)


if __name__ == "__main__":
    main()
