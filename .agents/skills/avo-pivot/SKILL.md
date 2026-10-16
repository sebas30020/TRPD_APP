---
name: avo-pivot
description: Fuerza un cambio de dirección cuando un approach_tag se ha estancado — varios intentos seguidos sin mover la métrica, o repitiendo esencialmente la misma idea. Úsalo en vez de seguir intentando variaciones menores del mismo enfoque fallido.
---

# avo-pivot

Objetivo: reconocer estancamiento y cambiar de vector explícitamente, en
vez de seguir puliendo un enfoque que el propio ledger ya muestra que no
funciona. En v1 esto es una disciplina que el agente aplica leyendo el
ledger él mismo — el supervisor automático que detectaría esto sin
intervención humana está diseñado pero no construido (ver
`docs/playbook.md`, sección "Fuera de alcance en v1"). El esquema del
ledger (`approach_tag` + `metric_value` en cada entrada) ya está pensado
para que ese supervisor, cuando se construya, sea barato de escribir.

## Señales de estancamiento (revísalas antes de otro `avo-attempt`)

- 3 o más intentos seguidos con el mismo `approach_tag` y ningún `commit`.
- `metric_value` sin movimiento apreciable entre intentos, o oscilando sin
  tendencia clara.
- Un `reject` reciente cuya causa en `deadends.md` es esencialmente la
  misma que la de un `reject` anterior con otro `approach_tag`.

Puedes revisar esto con `.avo/bin/avo log 15` o filtrando por tag/veredicto
directamente sobre `.avo/ledger.jsonl`.

## Pasos

1. **Confirma el estancamiento** con datos del ledger, no con intuición —
   cita los ids de los intentos que lo muestran.
2. **Lee `.avo/deadends.md` completo** (no solo las últimas entradas) en
   busca de la familia de causas del `approach_tag` estancado.
3. **Descarta explícitamente esa familia de hipótesis** — si aún no hay
   una entrada en `deadends.md` que generalice la causa raíz (más allá del
   intento individual), añádela ahora como la invariante aprendida.
4. **Selecciona un vector de exploración distinto**, no una variación
   menor del mismo. Diferente `approach_tag`, y si es pertinente, revisa
   `.avo/knowledge.md` por si el estancamiento revela que una asunción ahí
   registrada ya no es válida (actualízala si es así).
5. **Documenta el pivote en `.avo/state.md`**: qué enfoque se abandona,
   por qué, y cuál es el nuevo. La próxima sesión (o el próximo agente)
   debe poder leer esto y entender el cambio de dirección sin releer todo
   el ledger.
6. Continúa con `avo-attempt` sobre el nuevo enfoque.

## Qué NO hacer

- No pivotes tras un solo `reject` — eso es el ciclo normal de
  `avo-attempt`, no estancamiento.
- No abandones un enfoque sin dejar la causa raíz en `deadends.md`: si no
  la registras, el próximo ciclo puede volver a probarlo sin saberlo.
