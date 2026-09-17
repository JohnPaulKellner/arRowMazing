# arRowMazing

An arrow-escape brain puzzle written in Python 3.

## How to play

The board is a grid of **arrows drawn as thin black lines on a white board**.
Each arrow is a connected path of cells that may be a straight line of any
length, or it may bend through several right-angle turns — some arrows even
loop around other arrows. Arrow lengths vary widely — some stubs, some long
coil-snakes — which gives the board its variety: short arrows mixed with long,
looping border arrows.

- **Tap / click an arrow** to slide it off the board in the direction its
  **arrowhead** points.
- An arrow can only move if **every cell between its arrowhead and the edge in
  that direction is empty**. Tap a blocked arrow and it shakes (and counts as
  a mistake).
- **Clear every arrow** to complete the level and advance to a bigger, denser
  one.

### Controls

| Input             | Action                          |
| ----------------- | ------------------------------- |
| Mouse click / tap | Move an arrow                   |
| `H`               | Hint (pulses a movable arrow)   |
| `R`               | Restart the current level       |
| `M`               | Mute / unmute sound             |
| `F`               | Toggle fullscreen               |
| `Esc`             | Quit                            |

The window is **resizable** — drag its edges and the board re-scales to fit.
The **Full** button (or `F`) toggles fullscreen, which auto-scales the board to
your screen so the whole map is always visible.

## Setup

A virtual environment is already created in `.venv`. To recreate it from
scratch:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python main.py
```

Useful flags:

```bash
.venv/bin/python main.py --seed 42     # reproducible boards
.venv/bin/python main.py --level 56    # start at level 56 (a ~40x80 board)
```

## Tests

The core logic is pure Python and testable without a display:

```bash
.venv/bin/python test_board.py
```

This generates hundreds of boards across many levels and seeds and asserts that
every one is solvable, dense, and uses genuine multi-cell path arrows (some
straight, some bent).

## How it works

- `board.py` — pure game logic: the `Board`/`Arrow` model, the "is this arrow
  removable?" rule, path-arrow generation, and level sizing. No pygame here, so
  it's easy to test.
- `main.py` — the pygame front-end: rendering the path-arrows, input,
  slide/shake/confetti animations, HUD, and the win screen.

### Arrows are paths, not single cells

Unlike a naive grid of one-cell arrows, each arrow here is a **connected path**
of cells (its `cells` list, tail → head). The arrowhead is the last cell, and
the arrow slides in the direction of its final step. Paths are grown randomly:
a straight run with occasional right-angle turns (so the head still has a
clear, straight exit), of widely varying length — some stubs, some long
coil-snakes. This is what gives the board its variety: a mix of short arrows
and long, looping border arrows.

### Why the game is hard (and still always solvable)

Almost **every** arrow is blocked on a fresh board: the long arrows lining the
border hug the edge or point inward into the still-full interior, and only a
handful of edge arrows point straight out. Clearing those few exposes the next
handful, and so on — the whole board is one big dependency cascade, and that is
the puzzle.

Boards are generated to produce this. Cells are claimed **from the centre
outwards**; an arrow is only ever placed where its arrowhead's straight
corridor to an edge is clear *of everything placed so far*. Because the centre
is packed first, later snakes cover most earlier arrows' corridors, so almost
no arrow can move at the start. Only the last few
arrows placed (when clear corridors have run out) stay free, and those are the
only moves you start with.

This still guarantees a solution: an arrow's corridor was empty of *placed*
arrows when it was placed, so every arrow covering that corridor is placed
*after* it and therefore cleared *before* it by the player. Removing arrows in
reverse placement order is always a valid, forced solution. And because removing
an arrow only ever frees cells (it can never block another), there are no dead
ends.

### Scale and difficulty

The grid grows (portrait, taller than wide) and gets denser as the level
climbs. Level 56 is a **40×80** board, and the grid can reach **100×200** at
very high levels. The board is
always scaled to fit the window, so the whole map is visible; the window is
resizable and can be toggled to fullscreen (which auto-scales to your screen).

The look is intentionally minimal: **black arrows on a white board**, no
colours.

## Notes

- Uses **pygame-ce** (community edition), a drop-in replacement for pygame that
  ships prebuilt wheels.
- Sound effects are generated at runtime (no asset files needed) and can be
  muted with `M`.
