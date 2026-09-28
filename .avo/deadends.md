# Callejones Sin Salida

Bitácora **append-only** de enfoques ya descartados. Cada entrada de aquí
existe para que un ciclo futuro no vuelva a gastar tiempo probando lo
mismo. Se añade una entrada obligatoriamente cada vez que un intento
termina en `verdict: reject` (ver skill `avo-record`).

No se edita ni se borra retroactivamente: si un descarte resulta haber
sido un error, se documenta como una entrada nueva que lo corrige, no se
reescribe la vieja.

<!-- Formato de cada entrada:
### [YYYY-MM-DD] Intento #id: Tag `approach-tag`
- **Hipótesis:** qué se intentó y por qué se creía que funcionaría.
- **Causa de rechazo:** qué falló, con datos concretos (no "no funcionó").
- **Invariante aprendida:** qué regla general se puede extraer, si alguna.
-->

### [2026-09-28] Intento: Tag `arranque-entorno`
- **Hipótesis:** mantener el `.venv` dentro de Google Drive (`G:\Mi unidad\...\TRPD_APP\.venv`) marcándolo "Disponible sin conexión" bastaría para bajar el arranque de `app.py` de 178.7 s a < 10 s.
- **Causa de rechazo:** el arranque siguió siendo de minutos (el usuario reportó que `run_app.cmd` "nunca arranca"). Además, un `python.exe -u app.py` lanzado desde ese `.venv` (PID 23732, 25/09) quedó colgado reteniendo el puerto 8050 e inmune a `taskkill /F`, `Stop-Process -Force` y al reinicio de Drive; en cambio, el mismo servidor lanzado desde el venv local murió al instante con `Stop-Process`.
- **Invariante aprendida:** no ejecutar intérpretes ni `site-packages` desde Google Drive. El entorno vive en `%LOCALAPPDATA%\venvs\trpd_app` (import de `app` 2.2 s en caliente, servidor con 200 en 3.2 s).
