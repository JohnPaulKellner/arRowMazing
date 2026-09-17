#!/usr/bin/env python3
"""arRowMazing -- an arrow-escape puzzle.

Arrows are thin black lines of varying length on a white board. Each arrow is a
connected path of cells that may be straight or bend through several right-angle
turns (some even loop around other arrows). Tap an arrow to slide it off the
board in the direction its arrowhead points, but only if its path to the edge
is clear. Clear the whole board to advance to the next, larger level.

Run:
    python main.py            # play
    python main.py --seed 42  # reproducible boards (handy for testing)
    python main.py --level 56 # start at a specific level

Controls:
    Mouse click / tap   move an arrow
    Drag (left button)  pan around the board (while zoomed in)
    Mouse wheel         zoom in / out (kept centred on the cursor)
    + / -               zoom in / out (kept centred on the screen)
    0                   reset the view (fit the whole board)
    Arrow keys          pan (nudge)
    H                   hint (pulses a movable arrow)
    R                   restart the level
    M                   mute / unmute
    F                   fullscreen
    Esc                 quit
"""

from __future__ import annotations

import math
import random
import sys

import pygame

from board import (
    Arrow,
    Board,
    DELTA,
    UP,
    DOWN,
    LEFT,
    RIGHT,
    generate_board,
    level_config,
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
HUD_HEIGHT = 96
FPS = 60
MIN_CELL = 3  # smallest cell size (the board scales to fit the window)
SLIDE_DUR = 0.45  # seconds an arrow takes to uncoil and slide off the board
MIN_ZOOM = 1.0    # zoomed all the way out (whole board visible)
MAX_ZOOM = 12.0   # maximum magnification
ZOOM_STEP = 1.25  # zoom factor per wheel notch / +/- key press
PAN_STEP = 40     # pixels an arrow-key pan nudge moves the view

# ---------------------------------------------------------------------------
# Palette -- plain white board with black arrows (no colours, per request).
# ---------------------------------------------------------------------------
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (120, 120, 120)
GRAY_LIGHT = (200, 200, 200)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def ease_out(t):
    """Cubic ease-out for a snappy slide."""
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


def fade_color(t):
    """Black -> white as t goes 0 -> 1 (a cheap fade on a white board)."""
    v = int(255 * clamp(t, 0.0, 1.0))
    return (v, v, v)


def difficulty_label(level):
    """A difficulty word for the HUD."""
    if level < 10:
        return "Easy"
    if level < 25:
        return "Medium"
    if level < 45:
        return "Hard"
    return "Super Hard"


def make_font(size, bold=False):
    return pygame.font.SysFont("dejavusans,arial,helvetica", size, bold=bold)


# ---------------------------------------------------------------------------
# Sound (optional -- generated beeps, no asset files needed)
# ---------------------------------------------------------------------------
class Sound:
    def __init__(self):
        self.enabled = True
        self._ready = False
        self._sounds = {}
        try:
            import numpy as np
            import pygame.sndarray
            self._np = np
            self._sndarray = pygame.sndarray
            self._build(np, pygame.sndarray)
            self._ready = True
        except Exception:
            self._ready = False

    def _build(self, np, sndarray):
        def tone(freq, ms, vol=0.35):
            sr = 44100
            n = int(sr * ms / 1000)
            t = np.linspace(0, ms / 1000, n, endpoint=False)
            wave = np.sin(2 * np.pi * freq * t)
            fade = np.linspace(1.0, 0.0, n)
            wave = (wave * fade * vol * 32767).astype(np.int16)
            return sndarray.make_sound(wave)

        self._sounds["good"] = tone(660, 120)
        self._sounds["bad"] = tone(160, 160, 0.3)
        self._sounds["win"] = tone(880, 220, 0.4)

    def play(self, name):
        if self.enabled and self._ready and name in self._sounds:
            try:
                self._sounds[name].play()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Confetti (black / grey squares, to stay monochrome)
# ---------------------------------------------------------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "rot", "vr", "size", "color", "life")

    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.vx = random.uniform(-260, 260)
        self.vy = random.uniform(-520, -180)
        self.rot = random.uniform(0, math.tau)
        self.vr = random.uniform(-8, 8)
        self.size = random.uniform(5, 11)
        self.color = color
        self.life = random.uniform(1.2, 2.2)

    def update(self, dt):
        self.vy += 900 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.vr * dt
        self.life -= dt


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, seed=None, start_level=1):
        self.rng = random.Random(seed)
        self.level = max(1, start_level)
        self.mistakes = 0
        self.sound = Sound()

        self.font_title = make_font(26, bold=True)
        self.font_big = make_font(48, bold=True)
        self.font_hud = make_font(24, bold=True)
        self.font_hud_small = make_font(18)
        self.font_btn = make_font(20, bold=True)
        self.font_star = make_font(38, bold=True)

        self.state = "playing"  # playing | win
        self.win_time = 0.0
        self.particles: list[Particle] = []

        self.hint_arrow = None
        self.hint_time = 0.0
        self.hint_ttl = 3.0

        self.hover_arrow = None

        # View (camera) state for zoom / pan. ``zoom == 1`` shows the whole
        # board; higher zoom magnifies and lets the player pan around.
        self.zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self.fit_cell = MIN_CELL
        self.cell = MIN_CELL

        # Window state (resizable + optional fullscreen).
        self.fullscreen = False
        self.window_w, self.window_h = 900, 1200  # default; main() caps to desktop
        self._windowed_w, self._windowed_h = self.window_w, self.window_h

        # pan drag state
        self._dragging = False
        self._drag_last = (0, 0)
        self._drag_moved = False

        self._build_level()

    # -- level setup -------------------------------------------------------
    def _build_level(self):
        rows, cols, min_len, max_len = level_config(self.level)
        self.board = generate_board(rows, cols, self.rng, min_len, max_len)
        self.rows, self.cols = rows, cols
        self.sliding: list[dict] = []
        self.shaking: dict[int, float] = {}
        self.hint_arrow = None
        self.hover_arrow = None
        self.state = "playing"
        # fresh view for the new level
        self._pan_x = 0
        self._pan_y = 0
        self.zoom = 1.0
        self._dragging = False
        self._layout()

    def _layout(self):
        """Recompute the on-screen cell size from the zoom and reposition the
        board. At zoom 1 the board is centred in the play area; zoomed in, the
        (clamped) pan offset decides where it sits."""
        avail_w = max(50, self.window_w - 48)
        avail_h = max(50, self.window_h - HUD_HEIGHT - 40)
        self.fit_cell = max(MIN_CELL, min(avail_w // self.cols,
                                          avail_h // self.rows))
        self.cell = max(MIN_CELL, int(round(self.fit_cell * self.zoom)))
        self._apply_camera()

    def _apply_camera(self):
        """Position the board from the current cell size + pan offset. When the
        board fits the view it stays centred (pan forced to 0); when it's
        larger than the view the pan offset is clamped so at least a strip
        stays on screen and it can't be dragged fully away."""
        bw, bh = self.cell * self.cols, self.cell * self.rows
        cx = (self.window_w - bw) // 2
        cy = HUD_HEIGHT + (self.window_h - HUD_HEIGHT - bh) // 2
        if bw <= self.window_w:
            self._pan_x = 0
            self.board_x = cx
        else:
            lim = (bw - self.window_w) / 2 + 60
            self._pan_x = clamp(self._pan_x, -lim, lim)
            self.board_x = int(cx + self._pan_x)
        if bh <= self.window_h - HUD_HEIGHT:
            self._pan_y = 0
            self.board_y = cy
        else:
            lim = (bh - (self.window_h - HUD_HEIGHT)) / 2 + 60
            self._pan_y = clamp(self._pan_y, -lim, lim)
            self.board_y = int(cy + self._pan_y)

    def cell_center(self, row, col):
        x = self.board_x + col * self.cell + self.cell // 2
        y = self.board_y + row * self.cell + self.cell // 2
        return x, y

    def arrow_at_pixel(self, px, py):
        if self.state != "playing":
            return None
        col = (px - self.board_x) // self.cell
        row = (py - self.board_y) // self.cell
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.board.arrow_at(row, col)
        return None

    # -- zoom / pan ----------------------------------------------------------
    def set_zoom(self, new_zoom, focus=None):
        """Set the zoom level, keeping the board point currently under the
        focus screen pixel (default: screen centre) fixed on screen."""
        new_zoom = clamp(new_zoom, MIN_ZOOM, MAX_ZOOM)
        if abs(new_zoom - self.zoom) < 1e-9:
            return
        fx, fy = focus if focus is not None else (
            self.window_w / 2, (self.window_h + HUD_HEIGHT) / 2)
        # board point (in fit-cell units) under the focus before the change
        bcx = (fx - self.board_x) / (self.fit_cell * self.zoom)
        bcy = (fy - self.board_y) / (self.fit_cell * self.zoom)
        self.zoom = new_zoom
        self.cell = max(MIN_CELL, int(round(self.fit_cell * self.zoom)))
        # choose pan so that board point lands back under the focus pixel
        bw, bh = self.cell * self.cols, self.cell * self.rows
        cx = (self.window_w - bw) // 2
        cy = HUD_HEIGHT + (self.window_h - HUD_HEIGHT - bh) // 2
        self._pan_x = fx - bcx * self.fit_cell * new_zoom - cx
        self._pan_y = fy - bcy * self.fit_cell * new_zoom - cy
        self._apply_camera()

    def zoom_by(self, factor, focus=None):
        self.set_zoom(self.zoom * factor, focus)

    def zoom_reset(self):
        self.zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self.cell = self.fit_cell
        self._apply_camera()

    def pan_by(self, dx, dy):
        self._pan_x += dx
        self._pan_y += dy
        self._apply_camera()

    # -- pointer handlers (drag to pan, click to tap) ----------------------
    def on_press(self, px, py):
        self._dragging = True
        self._drag_last = (px, py)
        self._drag_moved = False

    def on_release(self, px, py):
        was_click = not self._drag_moved
        self._dragging = False
        if was_click:
            self.tap(px, py)

    def on_motion(self, px, py):
        if self._dragging:
            lx, ly = self._drag_last
            self._drag_last = (px, py)
            if abs(px - lx) + abs(py - ly) > 0:
                self._drag_moved = True
                self.pan_by(px - lx, py - ly)
        self.hover_arrow = self.arrow_at_pixel(px, py)

    # -- actions -----------------------------------------------------------
    def tap(self, px, py):
        if self.state == "win":
            if self.next_btn.collidepoint(px, py):
                self.level += 1
                self.mistakes = 0
                self._build_level()
            return

        # HUD buttons (top bar).
        if self.hint_btn.collidepoint(px, py):
            self.show_hint()
            return
        if self.restart_btn.collidepoint(px, py):
            self.restart()
            return
        if self.mute_btn.collidepoint(px, py):
            self.sound.enabled = not self.sound.enabled
            return
        if self.full_btn.collidepoint(px, py):
            self.toggle_fullscreen()
            return
        if self.zoom_in_btn.collidepoint(px, py):
            self.zoom_by(ZOOM_STEP)
            return
        if self.zoom_out_btn.collidepoint(px, py):
            self.zoom_by(1 / ZOOM_STEP)
            return
        if self.zoom_fit_btn.collidepoint(px, py):
            self.zoom_reset()
            return

        arrow = self.arrow_at_pixel(px, py)
        if arrow is None:
            return
        if self.board.is_removable(arrow):
            self._start_slide(arrow)
            self.sound.play("good")
        else:
            self.mistakes += 1
            self.shaking[id(arrow)] = 0.35
            self.sound.play("bad")

    def _start_slide(self, arrow):
        """Uncoil-slide: the arrow is treated as a flexible rope lying along
        its own cell path (the 'pipe'). Tapping pulls the tip in the exit
        direction; every body segment slides forward along the path, turning
        the corner at the head cell and straightening into a straight line
        that continues in the exit direction -- so the snake uncoils one
        segment at a time and leaves as a single straight line.

        The slide stores the arrow's cells (not pixels) so a zoom/pan change
        mid-animation still renders it in the right place.
        """
        self.board.remove(arrow)
        dr, dc = DELTA[arrow.direction]
        self.sliding.append({
            "cells": list(arrow.cells),
            "vx": dc, "vy": dr,
            "t": 0.0,
        })
        if self.board.is_solved():
            self._on_win()

    def _on_win(self):
        self.state = "win"
        self.win_time = 0.0
        self.sound.play("win")
        self._spawn_confetti()

    def _spawn_confetti(self):
        colors = [BLACK, GRAY, GRAY_LIGHT]
        for _ in range(120):
            x = random.uniform(0, self.window_w)
            y = random.uniform(-40, self.window_h * 0.3)
            self.particles.append(Particle(x, y, random.choice(colors)))

    def show_hint(self):
        if self.state != "playing":
            return
        a = self.board.hint()
        if a is not None:
            self.hint_arrow = a
            self.hint_time = 0.0

    def restart(self):
        self.mistakes = 0
        self._build_level()

    def toggle_fullscreen(self):
        """Toggle between windowed and fullscreen (auto-scaled to the screen)."""
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self._windowed_w, self._windowed_h = self.window_w, self.window_h
            try:
                dw, dh = pygame.display.get_desktop_sizes()[0]
            except Exception:
                dw, dh = 1280, 900
            self.window_w, self.window_h = dw, dh
            flags = pygame.RESIZABLE | pygame.FULLSCREEN
        else:
            self.window_w, self.window_h = self._windowed_w, self._windowed_h
            flags = pygame.RESIZABLE
        pygame.display.set_mode((self.window_w, self.window_h), flags)
        self._layout()
        self._init_buttons()

    # -- update ------------------------------------------------------------
    def update(self, dt):
        for s in self.sliding:
            s["t"] += dt / SLIDE_DUR
        self.sliding = [s for s in self.sliding if s["t"] < 1.0]

        for k in list(self.shaking):
            self.shaking[k] -= dt
            if self.shaking[k] <= 0:
                del self.shaking[k]

        if self.hint_arrow is not None:
            self.hint_time += dt
            if self.hint_time > self.hint_ttl:
                self.hint_arrow = None

        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles
                          if p.life > 0 and p.y < self.window_h + 40]

        if self.state == "win":
            self.win_time += dt

    # -- drawing -----------------------------------------------------------
    def draw(self, screen):
        screen.fill(WHITE)
        self._draw_board(screen)
        self._draw_sliding(screen)
        self._draw_hud(screen)
        self._draw_confetti(screen)
        if self.state == "win":
            self._draw_win_overlay(screen)

    def _draw_board(self, screen):
        # A thin frame around the board region for a little definition.
        bx, by = self.board_x, self.board_y
        bw, bh = self.cols * self.cell, self.rows * self.cell
        pygame.draw.rect(screen, GRAY_LIGHT, (bx - 2, by - 2, bw + 4, bh + 4),
                         width=1, border_radius=8)

        base_w = max(2, self.cell // 4)
        for arrow in self.board.arrows:
            width = base_w
            ox = 0
            # hint pulse
            if self.hint_arrow is arrow:
                width = int(base_w * (1.4 + 0.5 * math.sin(self.hint_time * 10)))
            # hover highlight (thicker = "you can grab me")
            if self.hover_arrow is arrow:
                width = max(width, int(base_w * 1.7))
            # shake offset for a blocked tap
            if id(arrow) in self.shaking:
                t = self.shaking[id(arrow)]
                ox = int(5 * math.sin(t * 40) * (t / 0.35))
            self._draw_arrow(screen, arrow, ox, 0, width, BLACK)

    def _draw_arrow(self, screen, arrow, dx, dy, width, color):
        """Draw a path-arrow: a continuous line through its cells + an arrowhead."""
        pts = []
        for (r, c) in arrow.cells:
            cx, cy = self.cell_center(r, c)
            pts.append((cx + dx, cy + dy))
        # Draw each segment with draw.line (draw.lines is broken in this
        # pygame-ce build -- it renders nothing).
        for i in range(1, len(pts)):
            pygame.draw.line(screen, color, pts[i - 1], pts[i], width)
        # small rounded caps at the joints for smooth corners
        for (x, y) in pts:
            pygame.draw.circle(screen, color, (int(x), int(y)), max(1, width // 2))
        # arrowhead at the head cell, pointing in the arrow's direction
        hx, hy = pts[-1]
        dr, dc = DELTA[arrow.direction]
        vx, vy = dc, dr          # pixel direction (col -> x, row -> y)
        px, py = -vy, vx         # perpendicular
        ah_len = self.cell * 0.55
        ah_w = self.cell * 0.34
        tip = (hx + vx * ah_len, hy + vy * ah_len)
        b1 = (hx - vx * ah_len * 0.15 + px * ah_w, hy - vy * ah_len * 0.15 + py * ah_w)
        b2 = (hx - vx * ah_len * 0.15 - px * ah_w, hy - vy * ah_len * 0.15 - py * ah_w)
        pygame.draw.polygon(screen, color, [tip, b1, b2])

    def _draw_sliding(self, screen):
        for s in self.sliding:
            t = ease_out(s["t"])
            color = fade_color(t)
            width = max(2, self.cell // 4)
            self._draw_uncoiling(screen, s, t, width, color)

    def _draw_uncoiling(self, screen, s, t, width, color):
        """Draw the sliding arrow as a flexible rope being pulled out of the
        board along its own cell path (the pipe) and into a straight line.

        The rope's material runs from tail (arc position 0) to head (arc
        position L). Pulling by ``pull`` shifts each material point forward
        along the pipe; past the head corner it continues in a straight line
        in the exit direction, so the snake visibly straightens out segment
        by segment as it leaves.

        Points are derived from the stored cells and the *current* cell size on
        every draw, so zoom/pan changes during the slide stay correct.
        """
        cells = s["cells"]
        seg = self.cell
        pts = [self.cell_center(r, c) for (r, c) in cells]
        L = seg * (len(pts) - 1)
        hr, hc = cells[-1]
        vx, vy = s["vx"], s["vy"]
        # distance (in pixels) from the head to the board edge in the exit dir
        if vx > 0:
            edge = (self.cols - hc) * seg
        elif vx < 0:
            edge = (hc + 1) * seg
        elif vy > 0:
            edge = (self.rows - hr) * seg
        else:
            edge = (hr + 1) * seg
        pull = t * (L + edge + seg)

        def at(a):
            """Point at arc-length ``a`` along the pipe (tail -> head),
            continuing straight past the head in the exit direction."""
            if a >= L:
                hx, hy = pts[-1]
                return (hx + vx * (a - L), hy + vy * (a - L))
            i = min(int(a // seg), len(pts) - 2)
            rem = a - i * seg
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            return (x0 + (x1 - x0) * (rem / seg), y0 + (y1 - y0) * (rem / seg))

        # material points at original arc positions 0, seg, ..., L
        drawn = [at(p + pull) for p in range(0, len(pts) * seg, seg)]
        for i in range(1, len(drawn)):
            pygame.draw.line(screen, color, drawn[i - 1], drawn[i], width)
        for (x, y) in drawn:
            pygame.draw.circle(screen, color, (int(x), int(y)), max(1, width // 2))
        # arrowhead rides along at the tip, always pointing in the exit dir
        hx, hy = pts[-1]
        hx += vx * pull
        hy += vy * pull
        ah_len = self.cell * 0.55
        ah_w = self.cell * 0.34
        px, py = -vy, vx
        tip = (hx + vx * ah_len, hy + vy * ah_len)
        b1 = (hx - vx * ah_len * 0.15 + px * ah_w, hy - vy * ah_len * 0.15 + py * ah_w)
        b2 = (hx - vx * ah_len * 0.15 - px * ah_w, hy - vy * ah_len * 0.15 - py * ah_w)
        pygame.draw.polygon(screen, color, [tip, b1, b2])

    def _draw_confetti(self, screen):
        for p in self.particles:
            surf = pygame.Surface((p.size, p.size), pygame.SRCALPHA)
            surf.fill((*p.color, int(255 * clamp(p.life, 0, 1))))
            surf = pygame.transform.rotate(surf, math.degrees(p.rot))
            screen.blit(surf, (int(p.x - p.size / 2), int(p.y - p.size / 2)))

    # -- HUD ---------------------------------------------------------------
    def _draw_hud(self, screen):
        title = self.font_title.render("arRowMazing", True, BLACK)
        screen.blit(title, (20, 8))

        lvl = self.font_hud.render(f"Level {self.level}", True, BLACK)
        screen.blit(lvl, (20, 40))
        diff = self.font_hud_small.render(difficulty_label(self.level), True, GRAY)
        screen.blit(diff, (20, 66))
        if self.zoom > 1.01:
            z = self.font_hud_small.render(f"zoom x{self.zoom:.1f}", True, GRAY)
            screen.blit(z, (20, 86))
        elif self.cols > 40:
            # hint that the board is pannable on dense levels
            tip = self.font_hud_small.render("scroll to zoom, drag to pan",
                                             True, GRAY_LIGHT)
            screen.blit(tip, (20, 86))

        self._draw_button(screen, self.hint_btn, "Hint", self.font_hud_small)
        self._draw_button(screen, self.restart_btn, "Restart", self.font_hud_small)
        self._draw_button(screen, self.mute_btn,
                          "Mute" if not self.sound.enabled else "Sound",
                          self.font_hud_small)
        self._draw_button(screen, self.full_btn,
                          "Window" if self.fullscreen else "Full", self.font_hud_small)
        self._draw_button(screen, self.zoom_out_btn, "-", self.font_hud_small)
        self._draw_button(screen, self.zoom_in_btn, "+", self.font_hud_small)
        self._draw_button(screen, self.zoom_fit_btn, "Fit", self.font_hud_small)

    def _draw_button(self, screen, rect, label, font):
        hover = rect.collidepoint(pygame.mouse.get_pos())
        if hover:
            pygame.draw.rect(screen, BLACK, rect, border_radius=8)
            txt = font.render(label, True, WHITE)
        else:
            pygame.draw.rect(screen, WHITE, rect, width=2, border_radius=8)
            txt = font.render(label, True, BLACK)
        screen.blit(txt, txt.get_rect(center=rect.center))

    def _draw_win_overlay(self, screen):
        overlay = pygame.Surface((self.window_w, self.window_h), pygame.SRCALPHA)
        overlay.fill((255, 255, 255, 170))
        screen.blit(overlay, (0, 0))

        panel_w, panel_h = min(460, self.window_w - 40), 300
        px = (self.window_w - panel_w) // 2
        py = (self.window_h - panel_h) // 2
        panel = pygame.Rect(px, py, panel_w, panel_h)
        pygame.draw.rect(screen, WHITE, panel, border_radius=18)
        pygame.draw.rect(screen, BLACK, panel, width=2, border_radius=18)

        head = self.font_big.render("Level Complete!", True, BLACK)
        screen.blit(head, head.get_rect(center=(self.window_w // 2, py + 62)))

        stars = 3 if self.mistakes == 0 else (2 if self.mistakes <= 2 else 1)
        star_txt = self.font_star.render("*" * stars, True, BLACK)
        screen.blit(star_txt, star_txt.get_rect(center=(self.window_w // 2, py + 120)))
        sub = self.font_hud_small.render(
            f"{self.mistakes} mistake{'s' if self.mistakes != 1 else ''}", True, GRAY)
        screen.blit(sub, sub.get_rect(center=(self.window_w // 2, py + 162)))

        self.next_btn = pygame.Rect(self.window_w // 2 - 110, py + panel_h - 84, 220, 50)
        hover = self.next_btn.collidepoint(pygame.mouse.get_pos())
        if hover:
            pygame.draw.rect(screen, BLACK, self.next_btn, border_radius=10)
            btn_txt = self.font_btn.render("Next Level  >", True, WHITE)
        else:
            pygame.draw.rect(screen, WHITE, self.next_btn, width=2, border_radius=10)
            btn_txt = self.font_btn.render("Next Level  >", True, BLACK)
        screen.blit(btn_txt, btn_txt.get_rect(center=self.next_btn.center))

    # -- button rects (built once) ----------------------------------------
    def _init_buttons(self):
        y, h, gap = 6, 42, 6
        # place buttons right-to-left along the top bar
        x = self.window_w - 10
        self.full_btn = pygame.Rect(x - 74, y, 74, h); x -= 74 + gap
        self.mute_btn = pygame.Rect(x - 76, y, 76, h); x -= 76 + gap
        self.zoom_in_btn = pygame.Rect(x - 46, y, 46, h); x -= 46 + gap
        self.zoom_out_btn = pygame.Rect(x - 46, y, 46, h); x -= 46 + gap
        self.zoom_fit_btn = pygame.Rect(x - 50, y, 50, h); x -= 50 + gap
        self.restart_btn = pygame.Rect(x - 90, y, 90, h); x -= 90 + gap
        self.hint_btn = pygame.Rect(max(180, x - 66), y, 66, h)
        self.next_btn = pygame.Rect(0, 0, 1, 1)


def main():
    seed = None
    start_level = 1
    args = sys.argv[1:]
    if "--seed" in args:
        seed = int(args[args.index("--seed") + 1])
    if "--level" in args:
        start_level = int(args[args.index("--level") + 1])

    pygame.init()
    game = Game(seed=seed, start_level=start_level)

    # Cap the initial window to the desktop so the whole board is visible.
    try:
        dw, dh = pygame.display.get_desktop_sizes()[0]
    except Exception:
        dw, dh = 1280, 900
    game.window_w = min(game.window_w, int(dw * 0.95))
    game.window_h = min(game.window_h, int(dh * 0.95))
    game._layout()
    game._init_buttons()

    screen = pygame.display.set_mode((game.window_w, game.window_h),
                                     pygame.RESIZABLE)
    pygame.display.set_caption("arRowMazing")
    clock = pygame.time.Clock()

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                game.window_w = event.w
                game.window_h = event.h
                game._layout()
                game._init_buttons()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                game.on_press(*event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.on_release(*event.pos)
            elif event.type == pygame.MOUSEMOTION:
                game.on_motion(*event.pos)
            elif event.type == pygame.MOUSEWHEEL:
                game.zoom_by(ZOOM_STEP ** event.y, pygame.mouse.get_pos())
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_h:
                    game.show_hint()
                elif event.key == pygame.K_r:
                    game.restart()
                elif event.key == pygame.K_m:
                    game.sound.enabled = not game.sound.enabled
                elif event.key == pygame.K_f:
                    game.toggle_fullscreen()
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    game.zoom_by(ZOOM_STEP)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    game.zoom_by(1 / ZOOM_STEP)
                elif event.key == pygame.K_0:
                    game.zoom_reset()
                elif event.key == pygame.K_LEFT:
                    game.pan_by(PAN_STEP, 0)
                elif event.key == pygame.K_RIGHT:
                    game.pan_by(-PAN_STEP, 0)
                elif event.key == pygame.K_UP:
                    game.pan_by(0, PAN_STEP)
                elif event.key == pygame.K_DOWN:
                    game.pan_by(0, -PAN_STEP)

        game.update(dt)
        # Re-fetch the surface each frame so resizes / fullscreen are honoured.
        screen = pygame.display.get_surface()
        game.draw(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
