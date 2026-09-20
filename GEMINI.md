<!-- avo-harness:begin -->
## Harness AVO — memoria persistente y feedback anclado

Este proyecto tiene instalado el harness AVO (`.avo/`). Antes de asumir que
un archivo no tiene contexto previo, revisa `.avo/state.md` — puede que
otra sesión (tuya o de otro agente) ya haya dejado el objetivo actual, el
enfoque en curso y por qué.

**Por qué existe:** el trabajo de horizonte largo no depende de memoria
dentro de tu propia ventana de contexto — depende de memoria en disco que
sobrevive entre sesiones, y de feedback que viene del entorno, no de tu
propia opinión sobre si un cambio "se ve bien". Ver `docs/playbook.md` en
el repo `tool` para el razonamiento completo detrás de cada pieza.

### El ciclo

A diferencia de un pipeline fijo, esto son obligaciones, no pasos rígidos:
tú decides qué inspeccionar, cambiar, probar y commitear. Los comandos de
abajo son el andamiaje de ese ciclo, no una secuencia obligatoria.

- **`/avo:resume`** — al empezar a trabajar en este proyecto, o tras
  cualquier interrupción larga. Carga `state.md`, el ledger reciente y los
  deadends, y te hace declarar el siguiente movimiento antes de tocar nada.
- **`/avo:attempt [pista opcional]`** — un ciclo de variación: hipótesis,
  cambio mínimo, `.avo/verify.sh`, evaluación (repara hasta 2 veces si
  falla; a la tercera, considera `/avo:pivot`).
- **`/avo:record <commit|reject|park> --tag ... --hypothesis ...`** —
  cierra todo intento, sin excepción. Es lo que hace que la próxima sesión
  (tuya, de otro agente, de otro humano) no tenga que reconstruir lo que tú
  ya sabes ahora. Los detalles de cada veredicto están en el comando.
- **`/avo:pivot`** — cuando el ledger muestra 3+ intentos con el mismo
  `approach_tag` sin mover la métrica. Fuerza un cambio de dirección
  explícito en vez de seguir puliendo un enfoque que ya se estancó.

Si trabajas sin invocar los comandos (p. ej. una tarea muy corta), la
disciplina sigue aplicando igual: no des un cambio por bueno sin correr
`.avo/verify.sh`, y no dejes la sesión sin que `.avo/ledger.jsonl` refleje
lo que hiciste — un hook de `Stop` en este proyecto bloqueará el cierre de
la sesión si el árbol de trabajo cambió y el ledger no.

### El contrato de verificación

`.avo/verify.sh` imprime un único JSON (`{"pass": bool, ...}`) y sale 0/1.
Es la fuente de verdad, no tu lectura del diff. Regla que no se negocia:
**el verificador nunca le pregunta al agente autor si lo hizo bien.**

- Perfil software: corre los tests/typecheck/lint que el proyecto ya
  tenga.
- Perfil investigación/contenido: además de chequeos deterministas
  (citas, enlaces, reproducibilidad), exige `.avo/critique.json` —
  escrito por **otro agente, invocado aparte, sin el historial de esta
  sesión**, que puntúe el resultado contra `.avo/rubric.md`. No lo
  simules tú mismo asumiendo ese rol.

### Memoria: qué se reescribe y qué se acumula

- `.avo/state.md` se **reescribe** cada sesión o ciclo — es el estado
  actual, acotado (~200 líneas), no un log. Si lo dejas crecer sin límite
  deja de servir para lo que existe.
- `.avo/ledger.jsonl` y `.avo/deadends.md` son **append-only** — el
  historial completo, con linaje (`parent`) entre intentos.
- `.avo/knowledge.md` son los invariantes del proyecto — revísalo antes de
  proponer algo que podría violarlos.

Todo `.avo/` se versiona en git — en contenedores efímeros, memoria no
commiteada es memoria perdida.
<!-- avo-harness:end -->
