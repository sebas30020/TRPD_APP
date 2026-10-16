---
name: avo-attempt
description: Ejecuta un ciclo acotado de variación (hipótesis, cambio, verificación, veredicto) sobre el proyecto. Úsalo para cualquier intento de mover la métrica objetivo declarada en .avo/state.md, ya sea código, investigación o contenido. Siempre se cierra con la skill avo-record, nunca se deja a medias.
---

# avo-attempt

Objetivo: un ciclo de variación disciplinado. Del paper de AVO tomamos
los cuatro verbos — proponer, reparar, criticar, verificar — como
**obligaciones del ciclo, no una secuencia rígida**: el agente decide qué
inspeccionar, cambiar, probar y commitear, no sigue un pipeline fijo.

## Precondición

Haber completado `avo-resume` en esta sesión (o tener ya declarado un
`approach_tag` e hipótesis activos en `state.md`).

## El ciclo

1. **Proponer** — define la hipótesis concreta y el `approach_tag` si no
   vienen ya de `avo-resume`. Una hipótesis útil predice qué debería pasar
   con la métrica objetivo, no solo describe la acción.
2. **Modificar** — aplica el cambio mínimo necesario para probar la
   hipótesis. No mezcles dos hipótesis distintas en un mismo intento: si
   descubres que necesitas probar algo no relacionado, ciérralo como un
   intento aparte.
3. **Verificar** — ejecuta `.avo/verify.sh` (o `.avo/bin/avo check` para
   un chequeo de salud más amplio). Este es el paso no-negociable: la
   señal viene del entorno, no de tu propia lectura del cambio.
   - **Perfil software**: `verify.sh` ya corre tests/typecheck/lint del
     proyecto.
   - **Perfil research/contenido**: `verify.sh` exige además
     `.avo/critique.json`, producido por un **agente de contexto fresco**
     (invócalo con la herramienta de sub-agentes, sin el historial de esta
     sesión) que puntúe el resultado contra `.avo/rubric.md`. No lo
     escribas tú mismo simulando ser ese crítico — el punto es que no sea
     el autor quien se autoevalúa.
4. **Evaluar y, si hace falta, reparar** — si `verify.sh` falla, puedes
   intentar una reparación localizada (máx. 2 iteraciones) antes de
   declarar el intento `reject`. Una tercera falla en la misma
   `approach_tag` es señal de que el enfoque, no la implementación, es el
   problema — considera pivotar (`avo-pivot`) en vez de seguir reparando.

## Cierre obligatorio

Todo intento — pase, falle, o quede bloqueado por algo externo — termina
en la skill **`avo-record`**. No dejes un intento sin registrar: es
exactamente lo que el hook `stop-require-ledger.sh` bloqueará al final de
la sesión, y es lo que hace que la próxima sesión (o el próximo agente)
tenga que reconstruir lo que tú ya sabes ahora.
