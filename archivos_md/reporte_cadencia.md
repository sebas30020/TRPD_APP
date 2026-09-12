# Reporte de cadencia de adquisición

Generado por `cadencia.py` el 2026-09-12 18:41.

- **Fuente:** atributo `SegmentedTimeTag` [s] de cada segmento (`Waveforms/Channel N/Channel N SegKData`), relativo al segmento 1. `Frame/TheFrame.Date` es la hora de guardado del archivo, no de adquisición.
- **Criterio:** mediana de Δt a ±2 s de 60 s → `cada_1min`; de 30 s → `cada_30s`; si no → `otros`.
- **Anómalo:** Δt que se aparta más de 2 s del nominal de su clase.

## Resumen

| Medición | Ubicación | Canales | Segmentos | Duración [s] | Δt mediana [s] | Δt mín [s] | Δt máx [s] | Clase |
|---|---|---|---|---|---|---|---|---|
| 1 | `cada_1min/1` | ch1, ch2, ch3, ch4 | 10 | 542.17 | 60.25 | 60.19 | 60.27 | **cada_1min** |
| 2 | `cada_30s/2` | ch1, ch2, ch3, ch4 | 16 | 551.93 | 30.12 | 30.09 | 130.22 | **cada_30s** |
| 3 | `cada_30s/3` | ch1, ch2, ch3, ch4 | 10 | 278.66 | 30.13 | 30.08 | 37.70 | **cada_30s** |
| 4 | `otros/4` | ch2, ch3, ch4 | 5 | 43.69 | 10.86 | 9.70 | 12.26 | **otros** |
| 5 | `cada_30s/5` | ch1, ch2, ch3, ch4 | 15 | 446.16 | 30.12 | 30.08 | 54.55 | **cada_30s** |
| 6 | `cada_30s/6` | ch1, ch2, ch3, ch4 | 10 | 271.09 | 30.12 | 30.09 | 30.17 | **cada_30s** |
| 7 | `cada_30s/7` | ch1, ch2, ch3, ch4 | 50 | 1475.89 | 30.12 | 30.06 | 30.17 | **cada_30s** |

## Conteo por clase

- `cada_1min`: 1 (1)
- `cada_30s`: 5 (2, 3, 5, 6, 7)
- `otros`: 1 (4)

## Anomalías

- Medición 2 (`cada_30s`): Seg15 → Seg16, Δt = 130.22 s
- Medición 3 (`cada_30s`): Seg1 → Seg2, Δt = 37.70 s
- Medición 4: cadencia no reconocida (mediana 10.86 s).
- Medición 5 (`cada_30s`): Seg1 → Seg2, Δt = 54.55 s

## Δt por medición [s]

- **1:** 60.25, 60.25, 60.25, 60.21, 60.25, 60.25, 60.25, 60.19, 60.27
- **2:** 30.15, 30.12, 30.09, 30.16, 30.11, 30.10, 30.15, 30.13, 30.09, 30.12, 30.10, 30.13, 30.17, 30.11, 130.22
- **3:** 37.70, 30.15, 30.08, 30.15, 30.10, 30.13, 30.11, 30.15, 30.11
- **4:** 11.61, 12.26, 9.70, 10.11
- **5:** 54.55, 30.17, 30.11, 30.08, 30.17, 30.11, 30.11, 30.15, 30.13, 30.08, 30.13, 30.11, 30.12, 30.17
- **6:** 30.15, 30.13, 30.09, 30.17, 30.10, 30.11, 30.15, 30.12, 30.09
- **7:** 30.14, 30.11, 30.15, 30.10, 30.10, 30.11, 30.16, 30.11, 30.10, 30.11, 30.17, 30.13, 30.10, 30.13, 30.10, 30.13, 30.10, 30.11, 30.13, 30.11, 30.16, 30.13, 30.11, 30.12, 30.11, 30.12, 30.11, 30.12, 30.10, 30.13, 30.11, 30.13, 30.17, 30.06, 30.17, 30.13, 30.10, 30.13, 30.10, 30.12, 30.11, 30.13, 30.11, 30.13, 30.14, 30.13, 30.13, 30.10, 30.13
