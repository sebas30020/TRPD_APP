# ESPECIFICACIÓN TÉCNICA Y PROMPT DIRECTRIZ: CALIBRACIÓN DE RETARDO INSTRUMENTAL, SINCRONIZACIÓN MULTI-CANAL Y PATRÓN TRPD

> **Destinatario:** Agente de Planificación / Arquitecto de Software.  
> **Objetivo:** Generar el plan de implementación detallado (`PLAN_TRPD_Calibracion_Sincronizacion.md`) para incorporar la calibración de retardos instrumentales ($t_{\text{lag}}$), la sincronización temporal física de canales de sensores y la correcta graficación del patrón de descargas parciales resuelto en el tiempo (TRPD: Time-Resolved Partial Discharge) en la aplicación `TRPD_APP`.  
> **Ubicación del repositorio:** `C:\0_matrix\doctorado\proyectos\inv_pd_vac\TRPD_APP`  
> **Archivo de salida esperado del agente planificador:** `archivos_md/PLAN_TRPD_Calibracion_Sincronizacion.md`

---

## 1. Contexto Físico, Experimental y Metrológico

### 1.1. La física del ensayo de impulso tipo rayo (LI) y descargas parciales (DP)
En el banco de alta tensión para vacío se aplican impulsos de tensión tipo rayo normalizados (Lightning Impulse - LI, ~1.2/50 µs) a probetas dieléctricas con cavidades/vacuolas. Durante el disparo ocurren fenómenos de alta velocidad:
1. **Impulso de tensión (CH1):** Registrado mediante un divisor de tensión capacitivo conectado directamente a la salida del generador de impulsos.
2. **Respuesta en sensores (CH2, CH3, CH4):** Sensores de alta frecuencia (HFCT en CH2, Antena Vivaldi en CH3, Antena Bioinspirada en CH4) detectan la emisión electromagnética y corrientes transitorias producidas por:
   - La ruptura dieléctrica de calibración en un explosor de esferas (spark breakdown).
   - Las descargas parciales (DP) internas en las vacuolas de la probeta bajo ensayo.

### 1.2. El problema del desfase temporal instrumental ($t_{\text{lag}}$)
El osciloscopio digital multicanal (Keysight DSOS804A a $5\text{ GSa/s}$, $dt = 2\times 10^{-4}\text{ µs}$) digitaliza los canales simultáneamente respecto a su reloj interno, pero **no registra los frentes de onda en el instante físico real de emisión** debido a discrepancias en las líneas de transmisión:
- **Longitud física y factor de velocidad de cables coaxiales:** Diferencias de longitud de cables (p. ej. RG-58 vs RG-214) introducen retardos de propagación del orden de $5\text{ ns/m}$ ($v \approx 0.66c$). Una diferencia de 2 metros introduce un desfase de $\approx 10\text{ ns}$.
- **Redes de atenuadores y filtros pasivos:** Los atenuadores pasivos de alta tensión en el divisor y los filtros en las antenas agregan retardos de grupo no despreciables.
- **Tiempo de vuelo electromagnético:** La distancia en espacio libre desde el explosor/probeta hasta cada antena añade un retardo de propagación $t = d/c$ ($3.33\text{ ns/m}$).
- **Variabilidad entre campañas de ensayo:** Si un día se ejecutan 50 disparos y al día siguiente se mueven antenas, cambian cables o varían filtros, el retardo instrumental cambia. Por ende, **la calibración debe determinarse independientemente para cada canal y para cada conjunto/campaña de mediciones**.

---

## 2. Definiciones Matemáticas y Metrología de Tiempos

### 2.1. Marca de tiempo del impulso de referencia: $t_{\text{imp}}$
- **Señal:** Canal CH1 (Lightning Impulse).
- **Tratamiento:** Señal de impulso filtrada con pasa-bajos Butterworth orden 4 a 20 MHz (`IMP_FCORTE = 20e6`), eliminando ruido de conmutación.
- **Definición de $t_{\text{imp}}$:** Instante exacto en que la señal de impulso alcanza el **10 % de su valor pico máximo** ($V_{\max}$) sobre el flanco de subida:
  $$t_{\text{imp}} \equiv t_{10}$$
- **Interpolación:** Debe determinarse mediante interpolación lineal sub-muestra entre muestras discretas adyacentes (implementada actualmente en `_cruce_subida(t, s, 0.10 * vmax, i_pico)`).
- **Referencia universal:** $t_{\text{imp}}$ establece el **origen temporal físico ($t=0$)** del evento de alta tensión para todos los canales. Puede evaluarse por segmento ($t_{10}^{(k)}$) o sobre el impulso promedio del experimento ($t_{10}^{\text{avg}}$).

### 2.2. Marca de tiempo del sensor en calibración: $t_{\text{ant}}$
- **Señal:** Canales CH2, CH3, CH4 durante disparos de calibración (ruptura en explosor de esferas).
- **Definición de $t_{\text{ant}}$:** Instante de arribo de la onda electromagnética generada por la ruptura dieléctrica.
- **Mecanismo de detección:**
  - **Trigger móvil configurable:** Evaluado con parámetros independientes por canal: umbral de calibración $u_{\text{cal}}$ [mV], tiempo mínimo de inicio $t_{\min,\text{cal}}$ [µs] y separación mínima $\Delta t_{\text{cal}}$ [µs].
  - **Inmunidad al ruido electromagnético (EMI):** Para evitar que el ruido pre-ruptura dispare en falso:
    1. Ventana temporal restrictiva: solo considerar eventos con $t \ge t_{\min,\text{cal}}$.
    2. Separación mínima entre picos sucesivos (`distance`).
    3. Criterio de arribo: $t_{\text{ant}}$ corresponde al primer pico válido o primer cruce del umbral en el frente de la señal de descarga del explosor.

### 2.3. Retardo instrumental por impulso y promedio del canal: $t_{\text{lag}}$
Para cada disparo $k \in \{1, \dots, N\}$ donde se registró ruptura válida:
$$t_{\text{lag}, c}^{(k)} = t_{\text{ant}, c}^{(k)} - t_{\text{imp}}^{(k)}$$

El retardo instrumental característico del canal $c$ para esa configuración experimental es el promedio muestral:
$$\bar{t}_{\text{lag}, c} = \frac{1}{N_{\text{valid}}} \sum_{k=1}^{N_{\text{valid}}} t_{\text{lag}, c}^{(k)}$$

Adicionalmente, se deben computar métricas estadísticas de dispersión:
- Desviación estándar: $\sigma_{t_{\text{lag}}, c} = \sqrt{\frac{1}{N_{\text{valid}}-1} \sum_{k=1}^{N_{\text{valid}}} \left(t_{\text{lag}, c}^{(k)} - \bar{t}_{\text{lag}, c}\right)^2}$
- Tasa de disparos válidos: $N_{\text{valid}} / N_{\text{total}}$ (descartando segmentos sin disparo o con ruido anómalo).

---

## 3. Sincronización Temporal y Generación del Patrón TRPD

### 3.1. Sincronización de canales
Una vez obtenido $\bar{t}_{\text{lag}, c}$, la señal del sensor se alinea físicamente restando el retardo instrumental:
$$t_{\text{sync}, c} = t_{\text{raw}, c} - \bar{t}_{\text{lag}, c}$$
Bajo esta transformación, el inicio de la señal medida por la antena coincide exactamente con el origen físico del impulso ($t_{10}$).

### 3.2. Tiempo absoluto de descarga parcial: $t_{\text{abs}}$
En los ensayos sobre probetas, cada descarga parcial ocurre en un instante pico $t_{\text{pd}}$ detectado por el algoritmo `find_peaks`. El tiempo de ocurrencia físico real relativo al inicio del impulso de alta tensión es:
$$t_{\text{abs}} = t_{\text{pd, sync}} - t_{10} = \left(t_{\text{pd}} - \bar{t}_{\text{lag}, c}\right) - t_{10} = t_{\text{pd}} - t_{10} - \bar{t}_{\text{lag}, c}$$

> **Interpretación física:**  
> $t_{\text{abs}}$ representa cuántos microsegundos (o nanosegundos) después de que la onda de tensión alcanzó el 10 % de su valor pico en la probeta se produjo la descarga parcial en la vacuola, libre de cualquier distorsión por cables o instrumentación.

### 3.3. Ejes del Patrón TRPD (Time-Resolved Partial Discharge)
El patrón TRPD grafica la nube de descargas en el plano $(t_{\text{abs}}, \text{Magnitud})$:
1. **Eje Horizontal (X):**
   - $t_{\text{abs}}$ [µs], con origen $t_{\text{abs}} = 0$ anclado al $t_{10}$ del impulso.
2. **Eje Vertical (Y) — Modos de Magnitud:**
   - **Modo $V_{\max}$:** Amplitud pico absoluta instantánea $V_{\max} = \max(|v(t)|)$ en el pulso de DP (en mV o V).
   - **Modo $V_{\text{pp}}$:** Tensión pico a pico $V_{\text{pp}} = \max(W_i) - \min(W_i)$ evaluada en la ventana normalizada de $70\text{ ns}$ ($-7\text{ ns}$ a $+63\text{ ns}$) alrededor del peak.
3. **Traza de Referencia del Impulso de Tensión (CH1):**
   - La curva del impulso promedio de CH1 debe superponerse en el gráfico TRPD trasladada en el tiempo:
     $$t_{\text{CH1, plot}} = t_{\text{CH1}} - t_{10}$$
     De esta forma, en $t_{\text{abs}} = 0$ la curva de tensión pasa exactamente por el 10 % de su cresta, permitiendo correlacionar visualmente la fase y nivel de tensión instantáneo del impulso en el que se gatilló cada descarga.

---

## 4. Requerimientos Funcionales del Sistema

### RF-1: Motor de Calibración de Retardos por Canal
- Permitir ejecutar la calibración para los canales `ch2`, `ch3` y `ch4` de forma independiente.
- Calcular $t_{\text{imp}}^{(k)} = t_{10}^{(k)}$ en cada segmento de CH1.
- Detectar $t_{\text{ant}}^{(k)}$ mediante búsqueda de transitorio de ruptura en la ventana de interés ($t \ge t_{\min,\text{cal}}$, umbral móvil $u_{\text{cal}}$, distancia $\Delta t_{\text{cal}}$).
- Calcular $t_{\text{lag}, c}^{(k)} = t_{\text{ant}, c}^{(k)} - t_{\text{imp}}^{(k)}$ para todos los segmentos del set.
- Calcular $\bar{t}_{\text{lag}, c}$, desviación estándar $\sigma$ y porcentaje de disparos consistentes.
- Soportar dos orígenes de calibración:
  1. **Calibración desde el set actual:** Cuando la carpeta cargada es un set de disparos de calibración (explosor de esferas).
  2. **Carga de calibración previa / Ingreso manual:** Posibilidad de cargar los $\bar{t}_{\text{lag}}$ calculados en una carpeta de calibración específica o editarlos numéricamente en la interfaz.

### RF-2: Persistencia y Gestión de Metadatos
- Guardar los valores calibrados $\bar{t}_{\text{lag}}$ en `metadata.yaml` de la carpeta de medición bajo una clave estructurada:
  ```yaml
  calibracion_retardo:
    fecha: "2026-09-16"
    fuente_calibracion: "calibracion_esferas_30kV"
    ch2:
      sensor: "HFCT"
      t_lag_ns: 12.4
      sigma_ns: 0.8
      n_valid: 50
    ch3:
      sensor: "Antena Vivaldi"
      t_lag_ns: 8.1
      sigma_ns: 0.5
      n_valid: 49
    ch4:
      sensor: "Antena Bioinspirada"
      t_lag_ns: 15.6
      sigma_ns: 1.1
      n_valid: 50
  ```
- Mantener un `dcc.Store(id="calibracion_store")` en la app para disponibilidad reactiva en todos los callbacks sin relecturas de disco.

### RF-3: Integración en la GUI de la App
- **Tarjeta/Barra de Calibración:**
  - Desplegar en la interfaz el retardo activo por canal con badges informativos:
    `CH2: 12.4 ns` | `CH3: 8.1 ns` | `CH4: 15.6 ns`.
  - Botón **"⚙️ Calibrar Retardos"** que abra un modal o expanda controles para:
    - Ver el histograma o dispersión de $t_{\text{lag}}$ de los 50 impulsos.
    - Ajustar umbral y $t_{\min}$ de calibración si hubo falsos triggers.
    - Aplicar / Guardar la calibración calculada.
  - Indicador de estado: "Calibrado" (verde) o "Sin calibrar / Retardo 0 ns" (ámbar).

### RF-4: Actualización del Gráfico TRPD (`figura_scatter`)
- Sustituir el eje horizontal actual `x = cap["t_peak"]` por el tiempo absoluto calibrado:
  $$x = t_{\text{abs}} = \text{cap}["t\_peak"] - t_{10} - \bar{t}_{\text{lag}, c}$$
- Alinear la traza del impulso de CH1 restando $t_{10}$:
  $$x_{\text{ref}} = t_{\text{ref}} - t_{10}$$
- Etiqueta del eje X: `"Tiempo relativo al impulso t_abs [µs] (t10 = 0)"`.
- Actualizar el `hovertemplate` para mostrar:
  - $t_{\text{abs}}$ [µs o ns].
  - $t_{\text{osc}}$ (tiempo crudo del osciloscopio).
  - Magnitud $V_{\max}$ y $V_{\text{pp}}$ en mV.
  - Segmento de origen.
- Mantener la selección interactiva 1:1 con las ventanas, FFT y Transformada S (reglas R-C1 a R-C4).

### RF-5: Actualización de la Tabla de Densidad de Eventos (`tabla_densidad`)
- Modificar el cálculo de la columna `t̄_abs (µs)` para que refleje el promedio de $t_{\text{abs}}$ sincronizado:
  $$\bar{t}_{\text{abs}} = \text{mean}(t_{\text{pd}} - t_{10} - \bar{t}_{\text{lag}, c})$$
  en lugar del promedio crudo de `cap["t_peak"]`.

---

## 5. Casos de Borde y Criterios de Robustez Numérica

1. **Disparos fallidos o sin descarga:** Si un impulso del set de calibración no produjo chispa o el sensor no superó el umbral $u_{\text{cal}}$, ese disparo debe descartarse del promedio $\bar{t}_{\text{lag}}$ sin abortar el cálculo de los demás.
2. **Impulso CH1 ruidoso o atípico:** Si en un segmento individual falla el cálculo de $t_{10}$, usar el $t_{10}$ del impulso promedio como fallback.
3. **Ausencia de calibración previa:** Si un experimento no tiene calibración registrada en su metadata ni en sesión, asumir por defecto $\bar{t}_{\text{lag}} = 0.0\text{ µs}$ y alertar al usuario con un badge informativo en la GUI, permitiendo calcular el TRPD preliminar sin desfase instrumental.
4. **Preservación del rendimiento (WebGL):** El cálculo de $t_{\text{abs}}$ es una traslación vectorial elemental en NumPy ($O(N)$), por lo que no introduce sobrecarga perceptible al renderizado de `Scattergl`.
5. **Consistencia de `uirevision`:** Al recalibrar o alternar entre modos, preservar el estado de paneo/zoom de los gráficos.

---

## 6. Instrucciones Específicas para el Agente que Construirá el Plan

El agente receptor deberá generar un documento exhaustivo titulado `archivos_md/PLAN_TRPD_Calibracion_Sincronizacion.md` siguiendo estrictamente la metodología de ingeniería de software del repositorio:

1. **Fase de Preparación y Git:**
   - Comprobación de estado limpio de git.
   - Creación de una rama específica (ej. `feature/trpd-calibracion-sincronizacion`).
2. **Fase de Backend y Métodos Matemáticos:**
   - Funciones auxiliares en `app.py` o módulo especializado para detección de $t_{\text{ant}}$ y cálculo estadístico de $t_{\text{lag}}$.
   - Adaptación de `capturar` y funciones derivadas para propagar $t_{\text{abs}}$.
3. **Fase de Metadatos y Persistencia:**
   - Integración con `generate_metadata.py` y lectura/escritura en `metadata.yaml`.
4. **Fase de Frontend Dash (Layout y Callbacks):**
   - Inclusión de stores (`calibracion_store`).
   - Controles de UI y badges de retardo por canal.
   - Callbacks para ejecución de calibración, actualización de `figura_scatter` y `tabla_densidad`.
5. **Fase de Verificación Experimental y Validación:**
   - Comprobación con archivos reales de `Mediciones/`.
   - Comparación numérica del TRPD antes y después de aplicar $\bar{t}_{\text{lag}}$.
6. **Fase de Documentación:**
   - Actualización de las secciones correspondientes en `archivos_md/DOCUMENTACION.md` incorporando las nuevas reglas de calibración y TRPD.
