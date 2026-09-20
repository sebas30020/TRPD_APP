---
name: avo-record
description: Cierra un ciclo de avo-attempt registrando el veredicto (commit/reject/park) en .avo/ledger.jsonl, actualizando .avo/state.md, y — si el veredicto es reject — añadiendo la entrada a .avo/deadends.md. Úsalo siempre al final de un intento, nunca lo omitas aunque el cambio parezca trivial.
---

# avo-record

Objetivo: cerrar el ciclo formalmente. Registrar los rechazos, no solo
los éxitos, es lo que en AVO evita re-explorar direcciones ya descartadas
— es la mitad del ahorro de acciones observado frente a no tener memoria.

## Cómo registrar

Usa el CLI incluido, que valida el JSON y evita entradas corruptas:

```bash
.avo/bin/avo record <commit|reject|park> \
  --tag "<approach_tag>" \
  --hypothesis "<qué se probó y por qué>" \
  [--parent <id>] \
  [--change "<resumen del cambio>"] \
  [--metric-name "<nombre>"] [--metric-value <n>] [--baseline <n>] \
  [--signals "tests:28/28,lint:clean"] \
  [--notes "<detalle, especialmente la causa si es reject>"] \
  [--commit-hash <sha>]
```

`--parent` por defecto es el id de la última entrada del ledger — solo
pásalo explícitamente si este intento retoma un linaje distinto (p. ej.
tras un `avo-pivot`).

## Según el veredicto

- **`commit`** — el intento superó `.avo/verify.sh` y mueve la métrica
  objetivo (o resuelve la tarea). Después de registrar:
  1. Actualiza `.avo/state.md` con el nuevo estado (línea base movida,
     próxima acción).
  2. `git add` + `git commit` del cambio real, con un mensaje que
     referencie el id del intento (p. ej. `avo(#c8e1): ...`).
- **`reject`** — falló la verificación o empeoró la métrica. El CLI ya
  añade una entrada base a `.avo/deadends.md` con el `--notes` que le
  pases — si la causa es más matizada, completa esa entrada a mano
  inmediatamente después. Luego:
  1. Revierte el cambio del árbol de trabajo (`git restore .` /
     `git checkout -- .` según corresponda) para dejarlo limpio, salvo que
     el propio `--notes` documente por qué se conserva parcialmente.
  2. Actualiza `.avo/state.md` con la lección aprendida, no solo con "se
     descartó X".
- **`park`** — enfoque prometedor pero bloqueado por algo externo
  (dependencia, decisión pendiente, refactor previo necesario). Documenta
  en `--notes` qué lo desbloquea. No lo trates como un callejón sin
  salida: no va a `deadends.md`, va a quedar referenciado en `state.md`
  como algo a retomar.

## Qué NO hacer

- No inventes el JSON del ledger a mano cuando puedas usar el CLI — el
  CLI valida el esquema y evita una línea corrupta que rompa a todo lector
  futuro del ledger.
- No dejes `state.md` sin tocar después de un `commit` o `reject` — es la
  única razón por la que `state.md` sirve de algo la próxima sesión.
- No marques `commit` si `.avo/verify.sh` no pasó. El veredicto tiene que
  reflejar la señal anclada, no tu impresión del cambio.
