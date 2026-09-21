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

## Directiva Obligatoria para la Generación y Gestión de Planes

Cada vez que el usuario solicite la elaboración o actualización de un **plan** (plan de trabajo, desarrollo, refactorización, optimización, pruebas o arquitectura):

1. **Persistencia Física Obligatoria en `.md`**:
   - El plan **NUNCA** debe quedar únicamente como texto efímero en la respuesta del chat.
   - Debe ser siempre escrito y guardado en un archivo Markdown (`.md`) dentro de la carpeta `archivos_md`:
     `g:\Mi unidad\yo\usm\investigacion\proyectos\inv_pd_vac\TRPD_APP\archivos_md` (o `./archivos_md` relativo a la raíz del proyecto).
   - **Creación de directorio**: Si la carpeta `archivos_md` no existe en el proyecto, debe ser creada automáticamente antes de generar el archivo.

2. **Diseñado para Ejecución por Otro Agente**:
   - El plan debe redactarse **siempre en función de que otro agente leerá el documento y lo ejecutará autónomamente**.
   - Debe ser completamente autocontenido, estructurado y sin ambigüedades:
     - Indicar claramente el destinatario al inicio (`> **Destinatario:** Agente ejecutor / implementador`).
     - Detallar el diagnóstico, contexto e hipótesis de partida.
     - Especificar los archivos exactos a crear o modificar (rutas, funciones y firmas).
     - Desglosar los pasos de forma secuencial, atómica y priorizada.
     - Proveer comandos exactos de terminal y entorno (ej. uso explícito del intérprete de entorno virtual).
     - Definir criterios objetivos de verificación y pruebas deterministas para dar por completada cada fase.

3. **Nomenclatura del Archivo `.md`**:
   - Siempre se debe acordar o definir el nombre del archivo `.md`:
     - El agente debe consultar al usuario por el nombre deseado o proponer un nombre descriptivo siguiendo la convención del proyecto (ejemplo: `PLAN_<TemaDescriptivo>.md`).
   - Todos los planes deben quedar centralizados dentro de `archivos_md/`.

