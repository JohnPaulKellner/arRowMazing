#!/usr/bin/env python3
"""Headless self-test for the arRowMazing core logic.

Verifies that generated boards are always solvable (greedy removal clears the
board) across a range of levels and seeds, that they are dense, that they are
genuinely *hard* (very few arrows movable at the start -- a cascade, not a
free-for-all), that border arrows never point outward off the board, and that
the arrows are genuine multi-cell paths with turns. Run with the venv python:

    .venv/bin/python test_board.py
"""

import random

from board import (
    UP, DOWN, LEFT, RIGHT,
    generate_board,
    level_config,
    solve_greedy,
)


def main():
    failures = 0
    total = 0
    start_move_stats = []
    for level in range(1, 60):
        rows, cols, min_len, max_len = level_config(level)
        for seed in range(10):
            rng = random.Random(seed * 1000 + level)
            board = generate_board(rows, cols, rng, min_len, max_len)
            total += 1
            if not board.arrows:
                print(f"  FAIL level {level} seed {seed}: empty board")
                failures += 1
                continue
            # Difficulty ramp: low levels stay casual-ish (a chunk of
            # arrows free), but by level 20+ only a small fraction are free at
            # the start -- the rest open only through a cascade. This was the
            # whole point: the old generator was already trivial (most arrows
            # free from the start).
            start_moves = board.removable_arrows()
            frac = len(start_moves) / len(board.arrows)
            start_move_stats.append((level, frac))
            # Low levels are casual by design (plenty free); enforce the cascade
            # (few free) only from mid levels up.
            if level >= 12:
                cap = 0.48 if level <= 32 else 0.37
                if frac > cap:
                    print(f"  FAIL level {level} seed {seed}: too many starting "
                          f"moves ({frac:.0%}) > cap {cap:.0%}")
                    failures += 1
                    continue
            # Border arrows must not point outward off the board.
            bad_edge = [a for a in board.arrows
                        if _points_off_board(a, board.rows, board.cols)]
            if bad_edge:
                print(f"  FAIL level {level} seed {seed}: {len(bad_edge)} edge "
                      f"arrows point outward (should never be free)")
                failures += 1
                continue
            # Arrows should be real paths: long and wiggly at hard levels.
            lengths = [a.length for a in board.arrows]
            if max(lengths) < 2:
                print(f"  FAIL level {level} seed {seed}: no multi-cell arrows")
                failures += 1
            if not any(a.turns >= 2 for a in board.arrows):
                print(f"  FAIL level {level} seed {seed}: no wiggly arrows")
                failures += 1
            # Coverage should be high: the board is packed near-solid.
            covered = sum(len(a.cells) for a in board.arrows)
            if covered < rows * cols * 0.55:
                print(f"  FAIL level {level} seed {seed}: sparse board "
                      f"({covered}/{rows*cols} covered)")
                failures += 1
                continue
            # Arrowheads must point directly away from their line: the final
            # step into the head must run in exactly the arrow's direction --
            # collinear with the tip, with every bend at least one full
            # segment before the head (never a 90-degree bend right at it).
            bad_tip = [a for a in board.arrows
                       if len(a.cells) >= 2 and not _tip_straight_on(a)]
            if bad_tip:
                print(f"  FAIL level {level} seed {seed}: {len(bad_tip)} arrows "
                      f"whose tip doesn't point straight out of its line")
                failures += 1
                continue
            # Greedy solve must clear the board.
            if not solve_greedy(board):
                print(f"  FAIL level {level} seed {seed}: unsolvable "
                      f"({len(board.arrows)} arrows left)")
                failures += 1
            elif not board.is_solved():
                print(f"  FAIL level {level} seed {seed}: not fully cleared")
                failures += 1

    early = [f for lvl, f in start_move_stats if lvl == 1]
    late = [f for lvl, f in start_move_stats if 50 <= lvl <= 59]
    early_free = (sum(early) / len(early)) if early else 0.0
    late_free = (sum(late) / len(late)) if late else 0.0
    print(f"\n{total} boards tested. Direction balance / free-at-start:")
    print(f"  arrows movable at start: level 1 {early_free:.0%} (casual) -> level 50+ {late_free:.0%} (deep cascade).")
    print(f"{failures} failures.")
    if failures == 0:
        print("All boards are solvable, dense interlocked cascades. \u2714")
    return failures


def _points_off_board(arrow, rows: int, cols: int) -> bool:
    """True if the head sits on a border and its direction exits straight out."""
    r, c = arrow.head
    return ((arrow.direction == UP and r == 0) or
            (arrow.direction == DOWN and r == rows - 1) or
            (arrow.direction == LEFT and c == 0) or
            (arrow.direction == RIGHT and c == cols - 1))


def _tip_straight_on(arrow) -> bool:
    """True if the final step into the head runs exactly in the arrow's
    direction, i.e. the tip points straight out of the end of the line (the
    last segment is collinear with the arrowhead)."""
    (hr, hc), (pr, pc) = arrow.cells[-1], arrow.cells[-2]
    # tail -> head step must equal the arrow's direction (tip out of the end).
    return (hr - pr, hc - pc) == _dir_vec(arrow.direction)


def _dir_vec(d):
    return {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}[d]


if __name__ == "__main__":
    raise SystemExit(main())
