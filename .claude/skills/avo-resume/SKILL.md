---
name: avo-resume
description: Restaura el contexto de trabajo de este proyecto antes de tocar cualquier archivo — lee la memoria persistente (.avo/state.md, ledger reciente, deadends) y declara el siguiente movimiento. Úsalo al empezar cualquier sesión de trabajo en un proyecto con harness AVO instalado, o cada vez que retomes trabajo tras una interrupción.
---

# avo-resume

Objetivo: reanudar desde el estado real del proyecto, no reconstruir la
búsqueda desde cero. Esto es lo que en el paper de AVO permite sostener
horizontes largos — la memoria evita que cada sesión repita el trabajo de
orientación de la anterior.

## Cuándo usar esta skill

- Al principio de cualquier sesión en un proyecto con `.avo/` instalado
  (el hook `session-start-load-memory.sh` ya inyectó el contexto — esta
  skill es la disciplina de *usarlo* antes de actuar, no de leerlo de nuevo).
- Después de una interrupción larga, un `/compact`, o cuando no estés
  seguro de en qué enfoque se quedó el trabajo.

## Pasos

1. **Lee el contexto ya inyectado** (`<avo_memory_context>` del inicio de
   sesión): `state.md`, las últimas entradas del ledger, los deadends
   recientes. Si por alguna razón no está disponible, léelos directamente:
   `.avo/state.md`, últimas 5 líneas de `.avo/ledger.jsonl`, y
   `.avo/deadends.md`.
2. **Verifica el estado real de git** — `git status` y `git log -n 3`.
   La memoria puede quedar desincronizada de lo que hay en disco (p. ej.
   si alguien commiteó fuera del ciclo AVO); git es la fuente de verdad
   final sobre qué existe.
3. **Revisa `.avo/knowledge.md`** — invariantes del proyecto que no debes
   violar ni re-descubrir.
4. **Revisa los deadends recientes** — antes de proponer un enfoque,
   confirma que no está ya descartado con una `approach_tag` similar.
5. **Declara explícitamente el siguiente movimiento** antes de editar
   nada: qué hipótesis vas a probar, con qué `approach_tag`, y por qué
   crees que puede mover la métrica objetivo de `state.md`. Esto es lo
   que la skill `avo-attempt` recogerá como punto de partida.

## Qué NO hacer

- No empieces a editar código/contenido sin haber completado el paso 5.
- No asumas que `state.md` está actualizado si `git log` muestra commits
  que no coinciden con lo que dice — en ese caso, reconcilia primero.
