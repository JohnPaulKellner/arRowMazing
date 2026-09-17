"""Core logic for arRowMazing -- an arrow-escape puzzle.

A board is a grid of cells. Arrows are *paths*: a connected chain of cells that
starts at one cell (the arrow's tail) and ends at another cell (the arrowhead).
The path may be a short stub, or it may coil and zig-zag through many
right-angle turns, with arrows of wildly different lengths lining the whole
border and snaking around each other.

Rules
-----
* Tapping an arrow slides it off the board in the direction its **arrowhead**
  points, but only if every cell between the arrowhead and the edge in that
  direction is empty (the arrow's own body cells never block it).
* An arrow occupies *every* cell along its path.
* Clear every arrow to win the level.

Why the boards are *hard* (and still always solvable)
-----------------------------------------------------
* Almost every arrow on the finished board is blocked at the
  start: a free arrow is rare, and pulling out the few free ones exposes more,
  one cascade step at a time. That dependency cascade *is* the puzzle. The old
  generator grew arrows through an almost-empty board, so nearly every arrow
  had a clear exit from the start -- trivial and boring. This generator instead
  *packs* the board: cells are claimed one snake at a time, and an arrow is
  only accepted while its head's corridor (head cell -> edge, straight line)
  contains no already-placed cell. As the board packs, fewer and fewer heads
  have a still-clear corridor, so most arrows end up covered by snakes placed
  *later* (inward- or along-facing heads) -- blocked at start. Only the last
  handful of arrows placed (when clear corridors have all but run out) stay
  free: those are the only moves available at the start of play.
* Solvability: generation order = reverse removal order. A placed arrow's
  corridor was empty of placed arrows at its placement; everything that later
  covers that corridor is placed afterwards, so the player removes those
  *before* it. Removing arrows from the last-placed backwards is therefore
  always a valid full solution (any arrow that blocks this one's corridor is
  cleared earlier). And removing an arrow only ever frees cells, so no dead
  end is ever possible. ``solve_greedy`` verifies this in the tests.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
DIRECTIONS = (UP, DOWN, LEFT, RIGHT)

# (row_delta, col_delta) step for each direction.
DELTA = {
    UP: (-1, 0),
    DOWN: (1, 0),
    LEFT: (0, -1),
    RIGHT: (0, 1),
}


@dataclass
class Arrow:
    """A single arrow: a connected path of cells ending in an arrowhead.

    ``cells`` is the ordered list of ``(row, col)`` cells the arrow occupies,
    from its tail (index 0) to its head (last index). ``direction`` is the
    direction the arrowhead points -- the direction the arrow slides when
    tapped.
    """

    cells: List[Tuple[int, int]] = None  # type: ignore[assignment]
    direction: str = RIGHT

    def __post_init__(self):
        if self.cells is None:
            self.cells = []

    @property
    def head(self) -> Tuple[int, int]:
        return self.cells[-1]

    @property
    def tail(self) -> Tuple[int, int]:
        return self.cells[0]

    @property
    def row(self) -> int:
        return self.cells[0][0]

    @property
    def col(self) -> int:
        return self.cells[0][1]

    @property
    def length(self) -> int:
        return len(self.cells)

    @property
    def turns(self) -> int:
        """Number of right-angle bends in the path (straight line = 0)."""
        t = 0
        for i in range(2, len(self.cells)):
            d1 = (self.cells[i - 1][0] - self.cells[i - 2][0],
                  self.cells[i - 1][1] - self.cells[i - 2][1])
            d2 = (self.cells[i][0] - self.cells[i - 1][0],
                  self.cells[i][1] - self.cells[i - 1][1])
            if d1 != d2:
                t += 1
        return t


class Board:
    """A grid of path-arrows with the rules of the game."""

    def __init__(self, rows: int, cols: int, arrows: Optional[List[Arrow]] = None):
        self.rows = rows
        self.cols = cols
        self.grid: List[List[Optional[Arrow]]] = [[None] * cols for _ in range(rows)]
        self.arrows: List[Arrow] = []
        if arrows:
            for a in arrows:
                self._place(a)

    def _place(self, arrow: Arrow) -> None:
        for (r, c) in arrow.cells:
            self.grid[r][c] = arrow
        self.arrows.append(arrow)

    # -- queries -----------------------------------------------------------
    def arrow_at(self, row: int, col: int) -> Optional[Arrow]:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.grid[row][col]
        return None

    def is_removable(self, arrow: Arrow) -> bool:
        """True if the arrowhead's straight ray to the edge is totally clear.

        An arrow is a *rigid* snake that slides out tip-first: if ANY cell on
        the ray from the arrowhead to the edge is occupied -- even by the
        arrow's own body (a tail that wraps around in front of its tip) -- the
        arrow is stuck and cannot move.
        """
        hr, hc = arrow.head
        dr, dc = DELTA[arrow.direction]
        r, c = hr + dr, hc + dc
        while 0 <= r < self.rows and 0 <= c < self.cols:
            cell = self.grid[r][c]
            if cell is not None:
                return False
            r += dr
            c += dc
        return True

    def removable_arrows(self) -> List[Arrow]:
        return [a for a in self.arrows if self.is_removable(a)]

    def hint(self) -> Optional[Arrow]:
        """Return one currently-removable arrow, or None if the board is empty."""
        rem = self.removable_arrows()
        return rem[0] if rem else None

    def is_solved(self) -> bool:
        return not self.arrows

    # -- mutations ---------------------------------------------------------
    def remove(self, arrow: Arrow) -> None:
        for (r, c) in arrow.cells:
            self.grid[r][c] = None
        self.arrows.remove(arrow)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _corridor_clear(grid, rows: int, cols: int, head: Tuple[int, int],
                    direction: str) -> bool:
    """True if every cell between ``head`` and the edge in ``direction`` (not
    counting ``head`` itself) is empty on ``grid``.

    At placement time this is exactly "nothing placed so far blocks this
    arrow's exit" -- a necessary condition for the arrow to be solvable.
    """
    dr, dc = DELTA[direction]
    r, c = head[0] + dr, head[1] + dc
    while 0 <= r < rows and 0 <= c < cols:
        if grid[r][c] is not None:
            return False
        r += dr
        c += dc
    return True


def _is_edge_outward(row: int, col: int, direction: str,
                    rows: int, cols: int) -> bool:
    """True if standing at (row, col), ``direction`` points *off* the board.

    Edge arrows hug the border tangentially or point inward --
    they never sit on the border pointing straight out (that is exactly the
    "too many free arrows" problem we are fixing), so outward-pointing heads
    are illegal and such arrows can only be freed by a cascade.
    """
    return ((direction == UP and row == 0) or
            (direction == DOWN and row == rows - 1) or
            (direction == LEFT and col == 0) or
            (direction == RIGHT and col == cols - 1))


_OPPOSITE = {UP: DOWN, DOWN: UP, LEFT: RIGHT, RIGHT: LEFT}


def _body_blocks_tip(body: List[Tuple[int, int]], direction: str) -> bool:
    """True if any body cell lies on the arrowhead's exit ray.

    A snake leaves tip-first, so its own cells sitting on the straight ray from
    the head to the edge (in ``direction``) block the snake from sliding out --
    exactly the highlighted "G" that points left but has body cells further
    left. Such an arrow could never be removed, so it must not be placed.
    """
    hr, hc = body[-1]
    if direction == UP:
        return any(pc == hc and pr < hr for pr, pc in body[:-1])
    if direction == DOWN:
        return any(pc == hc and pr > hr for pr, pc in body[:-1])
    if direction == LEFT:
        return any(pr == hr and pc < hc for pr, pc in body[:-1])
    return any(pr == hr and pc > hc for pr, pc in body[:-1])


def _grow_body(grid, rows: int, cols: int, head: Tuple[int, int], head_dir: str,
               rng: random.Random, target_len: int, min_len: int,
               turn_prob: float, stub_prob: float) -> Optional[List[Tuple[int, int]]]:
    """Grow an arrow's body through empty cells, ending exactly at ``head``.

    The arrowhead *always* points directly away from its own line: the final
    step into ``head`` runs in ``head_dir`` itself, so the last segment is
    collinear with the tip and every direction change happens at least one
    FULL segment before the head (never at the head cell). The walk therefore
    starts by stepping straight back from the head (opposite ``head_dir``) and
    only *then* may it wiggly -- continuing straight most of the time and
    turning to a free perpendicular with probability ``turn_prob``, plus
    stopping early with small probability so lengths vary (stubby Ls next to
    long coil-snakes). It stops when boxed in. Returns cells
    in tail -> head order (so ``cells[-1]`` is ``head`` and
    ``head - cells[-2] == DELTA[head_dir]``), or None if the needed first cell
    is unavailable or the body could not reach ``min_len``.
    """
    hr, hc = head
    if grid[hr][hc] is not None:
        return None
    cur = _OPPOSITE[head_dir]  # line approaches the head straight-on
    pr, pc = hr + DELTA[cur][0], hc + DELTA[cur][1]
    if not (0 <= pr < rows and 0 <= pc < cols) or grid[pr][pc] is not None:
        return None
    cells: List[Tuple[int, int]] = [(hr, hc), (pr, pc)]
    occupied = {(hr, hc), (pr, pc)}
    r, c = pr, pc
    while len(cells) < target_len:
        if len(cells) >= min_len and rng.random() < stub_prob:
            break  # vary length: many stubs, some long snakes
        free = [d for d in DIRECTIONS
                if 0 <= r + DELTA[d][0] < rows and 0 <= c + DELTA[d][1] < cols
                and grid[r + DELTA[d][0]][c + DELTA[d][1]] is None
                and (r + DELTA[d][0], c + DELTA[d][1]) not in occupied]
        if not free:
            break
        # Prefer to continue straight unless we turn, to keep snakes snake-like.
        if cur in free and rng.random() >= turn_prob:
            nxt = cur
        else:
            rng.shuffle(free)
            nxt = free[0]
        r, c = r + DELTA[nxt][0], c + DELTA[nxt][1]
        cells.append((r, c))
        occupied.add((r, c))
        cur = nxt
    if len(cells) < min_len:
        return None
    cells.reverse()  # tail -> head order (head is the *last* cell)
    return cells


def generate_board(rows: int, cols: int, rng: Optional[random.Random] = None,
                   min_len: int = 4, max_len: int = 26,
                   turn_prob: float = 0.5, stub_prob: float = 0.14,
                   tile: int = 8) -> Board:
    """Generate a *dense, interlocked, solvable* board of path-arrows.

    Two properties make a board good rather than trivial or fake-looking:

    1. *Difficulty.* A cell can only become an arrow's head while the straight
       ray from that cell toward the edge is still empty of placed arrows, so
       every head that gets placed becomes blocked only by arrows placed
       *later* -- arrows the player (playing in reverse placement order)
       clears *before* it. Once a region packs, clear rays run out, placement
       saturates, and almost nothing is movable at the start: the board opens
       only as a dependency cascade.
    2. *Natural look.* Cells are claimed in **random order inside small
       tiles**. A globally centre-outwards order (or any global sweep) biases
       every quadrant: arrows in the top-left would all point up/left, etc.,
       because by the time a cell is visited only the outward ray is still
       free. Working per small tile keeps the head-order locally local, so all
       four directions stay well represented in every part of the board.

    Edge cells never point *outward* off the board (``_is_edge_outward``), and
    an arrow whose own body sits on its tip's exit ray (a self-blocking coil)
    is never placed (``_body_blocks_tip``).

    Solvability: an arrow's ray was empty of *placed* arrows at its placement
    time; everything now covering that ray was placed after it, so the player
    clears those first. Removing arrows in reverse placement order is always a
    valid, forced solution.
    """
    rng = rng or random.Random()
    rows = max(rows, min_len + 1)
    cols = max(cols, min_len + 1)
    board = Board(rows, cols)

    # Claim cells tile by tile in random order: heads near the tile's own edge
    # get placed at random times, so which directions are still "open" when a
    # cell is claimed is itself unbiased -- all four head directions stay
    # evenly represented everywhere, unlike any global sweep order.
    for tb in range(0, rows, tile):
        for tc in range(0, cols, tile):
            cells = [(r, c)
                     for r in range(tb, min(tb + tile, rows))
                     for c in range(tc, min(tc + tile, cols))]
            rng.shuffle(cells)
            for cell in cells:
                r, c = cell
                if board.grid[r][c] is not None:
                    continue
                dirs = [d for d in DIRECTIONS
                        if not _is_edge_outward(r, c, d, rows, cols)]
                rng.shuffle(dirs)
                for d in dirs:
                    if not _corridor_clear(board.grid, rows, cols, cell, d):
                        continue
                    target = rng.randint(min_len, max_len)
                    body = _grow_body(board.grid, rows, cols, cell, d, rng,
                                      target, min_len, turn_prob, stub_prob)
                    if body is None or body[-1] != cell:
                        continue
                    # A rigid snake can only leave tip-first: if its own body
                    # (tail) lies on the tip's exit ray it blocks itself.
                    if _body_blocks_tip(body, d):
                        continue
                    board._place(Arrow(body, d))
                    break
    return board



def level_config(level: int) -> Tuple[int, int, int, int]:
    """Return ``(rows, cols, min_len, max_len)`` for a 1-based level number.

    The grid grows (portrait, taller than wide) and the arrows get longer as
    the level rises, so late levels are big boards of long, deeply interlocking
    snakes whose cascades run very deep. Level 56 is a ~40x80 board, and the
    grid reaches 100x200 at high levels.
    """
    level = max(1, level)
    # Grid grows with level: ~10x16 at level 1, ~40x80 at level 56, capped at
    # a large portrait board of 100x200.
    cols = min(10 + (level - 1) * 30 // 55, 100)
    rows = min(16 + (level - 1) * 64 // 55, 200)
    # Arrows are wiggly multi-turn snakes. A higher min length avoids the sea
    # of 2-3 cell stubs that cluttered early boards, so arrows stay long and
    # interesting, and short leftover pockets stay empty
    # rather than becoming tiny parallel stub arrows.
    min_len = 4
    max_len = 10 + min(level, 22)
    return rows, cols, min_len, max_len


def solve_greedy(board: Board) -> bool:
    """Repeatedly remove any removable arrow until the board is empty or stuck.

    Used for self-testing: for a correctly generated board this should always
    succeed (see the module docstring for why the reverse placement order is a
    valid solution for *any* pick order).
    """
    while not board.is_solved():
        rem = board.removable_arrows()
        if not rem:
            return False
        board.remove(rem[0])
    return True
