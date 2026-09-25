"""Tests de generate_metadata.py con archivos .h5 sintéticos (estructura Keysight),
independientes de dónde estén los datos reales."""

import h5py
import numpy as np
import pytest
import yaml

import generate_metadata as gm

XINC = 2e-10          # 5 GSa/s
XORG = -10e-6         # 10 us de pre-trigger
NPTS = 200_000        # 40 us por segmento
YINC = 1e-4
TAGS = [0.0, 60.2, 120.4, 180.6, 245.0]   # último salto anómalo (64.4 s)


def _escribir_canal(ruta, n_canal, senal, yrango=8.0, bw=1e9):
    with h5py.File(ruta, "w") as f:
        dt = np.dtype([("Model", "S12"), ("Serial", "S12"), ("Date", "S22")])
        f.create_group("Frame").create_dataset(
            "TheFrame", data=np.array((b"DSOS804A", b"MY123", b"22-Sep-2026 10:00:00"), dtype=dt))
        g = f.create_group("Waveforms").create_group(f"Channel {n_canal}")
        for k, v in {"YInc": YINC, "YOrg": 0.0, "XInc": XINC, "XOrg": XORG, "NumPoints": NPTS,
                     "NumSegments": len(TAGS), "YDispRange": yrango, "YDispOrigin": 0.0,
                     "XDispRange": 200e-6, "XDispOrigin": -19.556e-6, "MaxBandwidth": bw}.items():
            g.attrs[k] = v
        for i, tag in enumerate(TAGS, start=1):
            raw = np.round(senal(i) / YINC).astype(np.int16)
            ds = g.create_dataset(f"Channel {n_canal} Seg{i}Data", data=raw)
            ds.attrs["SegmentedTimeTag"] = tag
            ds.attrs["SegmentedXOrg"] = XORG + i * 1e-11


@pytest.fixture
def medicion(tmp_path):
    """Medición sintética: CH1 impulso positivo que cruza 1.0 V en t = 0 (pico 2 V);
    CH3 con un pulso de 1 V que se sale de la pantalla (±0.8 V)."""
    t = XORG + np.arange(NPTS) * XINC
    rng = np.random.default_rng(0)

    def impulso(_):
        v = np.where(t < -0.5e-6, 0.0, 2.0 * (1 - np.exp(-(t + 0.5e-6) / 0.5e-6)))
        return v + rng.normal(0, 0.005, NPTS)

    def uhf(_):
        return np.where(np.abs(t - 1e-6) < 5e-9, 1.0, 0.0) + rng.normal(0, 0.002, NPTS)

    d = tmp_path / "3V224_30kV"
    d.mkdir()
    _escribir_canal(str(d / "ch1.h5"), 1, impulso)
    _escribir_canal(str(d / "ch3.h5"), 3, uhf, yrango=1.6, bw=2.5e9)
    return str(d)


def test_analizar_cadencia():
    marcas = {"ch1": TAGS, "ch3": TAGS}
    cad = gm.analizar_cadencia(marcas)
    assert cad["clase"] == "cada_1min"
    assert cad["dt_mediana_s"] == pytest.approx(60.2, abs=0.01)
    assert cad["duracion_total_s"] == 245.0
    assert cad["anomalias"] == [{"desde_seg": 4, "hasta_seg": 5, "dt_s": 64.4}]
    assert cad["marcas_coinciden_entre_canales"] is True

    assert gm.analizar_cadencia({"ch1": TAGS, "ch2": TAGS[:-1]})["marcas_coinciden_entre_canales"] is False
    assert gm.clasificar_cadencia(30.1) == ("cada_30s", 30.0)
    assert gm.clasificar_cadencia(45.0) == ("otros", None)
    assert gm.analizar_cadencia({}) is None


def test_plantilla_rellena_automaticamente(medicion):
    d = gm.plantilla_metadata(medicion, medicion)

    assert d["cadencia"]["clase"] == "cada_1min"
    assert d["circuito_impulso"]["intervalo_entre_disparos_s"] == pytest.approx(60.2, abs=0.01)
    assert d["circuito_impulso"]["nro_disparos_programados"] == len(TAGS)
    assert d["circuito_impulso"]["polaridad"] == "positiva"
    assert d["circuito_impulso"]["v_pico_divisor_media_v"] == pytest.approx(2.0, abs=0.05)

    trig = d["trigger"]
    assert trig["canal_origen"] == "ch1" and trig["pendiente"] == "positiva"
    assert trig["nivel_v"] == pytest.approx(1.26, abs=0.05)   # 2*(1-e^-1)
    assert trig["posicion_horizontal_pct"] == pytest.approx(9.78, abs=0.01)
    assert trig["jitter_trigger_ns"] == pytest.approx(0.04, abs=1e-3)

    ch = d["canales"]
    assert ch["ch1"]["presente"] and not ch["ch2"]["presente"]
    assert ch["ch3"]["ancho_banda_ghz"] == 2.5
    assert ch["ch3"]["senal"]["n_segmentos_fuera_de_pantalla"] == len(TAGS)
    assert ch["ch1"]["senal"]["n_segmentos_fuera_de_pantalla"] == 0

    assert d["probeta"]["codigo"] == "3V224"
    pend = d["generado_automaticamente"]["campos_pendientes"]
    assert "experimento.temperatura_c" in pend and "trigger.nivel_v" not in pend


def test_trigger_no_en_ch1(tmp_path):
    """Si CH1 está en su línea base en t = 0, el trigger no se atribuye a CH1."""
    t = XORG + np.arange(NPTS) * XINC
    d = tmp_path / "m"
    d.mkdir()
    _escribir_canal(str(d / "ch1.h5"), 1,
                    lambda _: np.where(t > 5e-6, 2.0, 0.0) + np.random.default_rng(1).normal(0, 0.005, NPTS))
    trig = gm.plantilla_metadata(str(d), str(d))["trigger"]
    assert trig["canal_origen"] is None and trig["nivel_v"] is None


def test_generar_completar_conserva_lo_manual(medicion):
    destino = gm.generar(medicion)
    datos = yaml.safe_load(open(destino, encoding="utf-8"))
    assert datos["cadencia"]["clase"] == "cada_1min"

    # Edición manual + un campo automático borrado
    datos["experimento"]["temperatura_c"] = 21.5
    datos["circuito_impulso"]["polaridad"] = "negativa"
    del datos["cadencia"]
    with open(destino, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, allow_unicode=True, sort_keys=False)

    gm.generar(medicion)                       # sin opciones: no toca el archivo
    assert "cadencia" not in yaml.safe_load(open(destino, encoding="utf-8"))

    gm.generar(medicion, completar=True)
    datos = yaml.safe_load(open(destino, encoding="utf-8"))
    assert datos["experimento"]["temperatura_c"] == 21.5
    assert datos["circuito_impulso"]["polaridad"] == "negativa"
    assert datos["cadencia"]["clase"] == "cada_1min"
    assert "experimento.temperatura_c" not in datos["generado_automaticamente"]["campos_pendientes"]

    gm.generar(medicion, forzar=True)
    assert yaml.safe_load(open(destino, encoding="utf-8"))["experimento"]["temperatura_c"] is None


def test_buscar_mediciones_recursivo(medicion, tmp_path):
    assert gm.buscar_mediciones(str(tmp_path)) == [medicion]
    with pytest.raises(FileNotFoundError):
        gm.generar(str(tmp_path / "no_existe"))
