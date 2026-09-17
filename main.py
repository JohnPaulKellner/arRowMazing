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
    H                   hint (pulses a movable arrow)
    R                   restart the level
    M                   mute / unmute
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

        # Window state (resizable + optional fullscreen).
        self.fullscreen = False
        self.window_w, self.window_h = 900, 1200  # default; main() caps to desktop
        self._windowed_w, self._windowed_h = self.window_w, self.window_h

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
        self._layout()

    def _layout(self):
        """Scale the board to fit the current window and centre it.

        The cell size is derived from the window, so the whole board is always
        visible no matter how the window is resized or whether it's fullscreen.
        """
        avail_w = max(50, self.window_w - 48)
        avail_h = max(50, self.window_h - HUD_HEIGHT - 40)
        self.cell = max(MIN_CELL, min(avail_w // self.cols, avail_h // self.rows))
        board_w = self.cell * self.cols
        board_h = self.cell * self.rows
        self.board_x = (self.window_w - board_w) // 2
        self.board_y = HUD_HEIGHT + (self.window_h - HUD_HEIGHT - board_h) // 2

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
        self.board.remove(arrow)
        hr, hc = arrow.head
        cell = self.cell
        if arrow.direction == UP:
            dist = (hr + 1) * cell
            dx, dy = 0, -dist
        elif arrow.direction == DOWN:
            dist = (self.rows - hr) * cell
            dx, dy = 0, dist
        elif arrow.direction == LEFT:
            dist = (hc + 1) * cell
            dx, dy = -dist, 0
        else:
            dist = (self.cols - hc) * cell
            dx, dy = dist, 0
        self.sliding.append({"arrow": arrow, "dx": dx, "dy": dy, "t": 0.0})
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
            s["t"] += dt / 0.30
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
            dx = s["dx"] * t
            dy = s["dy"] * t
            color = fade_color(t)
            width = max(2, self.cell // 4)
            self._draw_arrow(screen, s["arrow"], dx, dy, width, color)

    def _draw_confetti(self, screen):
        for p in self.particles:
            surf = pygame.Surface((p.size, p.size), pygame.SRCALPHA)
            surf.fill((*p.color, int(255 * clamp(p.life, 0, 1))))
            surf = pygame.transform.rotate(surf, math.degrees(p.rot))
            screen.blit(surf, (int(p.x - p.size / 2), int(p.y - p.size / 2)))

    # -- HUD ---------------------------------------------------------------
    def _draw_hud(self, screen):
        title = self.font_title.render("arRowMazing", True, BLACK)
        screen.blit(title, (20, 18))

        lvl = self.font_hud.render(f"Level {self.level}", True, BLACK)
        screen.blit(lvl, (20, 52))
        diff = self.font_hud_small.render(difficulty_label(self.level), True, GRAY)
        screen.blit(diff, (20, 80))

        self._draw_button(screen, self.hint_btn, "Hint", self.font_btn)
        self._draw_button(screen, self.restart_btn, "Restart", self.font_btn)
        self._draw_button(screen, self.mute_btn,
                          "Mute" if not self.sound.enabled else "Sound",
                          self.font_btn)
        self._draw_button(screen, self.full_btn,
                          "Window" if self.fullscreen else "Full", self.font_btn)

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
        self.hint_btn = pygame.Rect(self.window_w - 392, 60, 84, 42)
        self.restart_btn = pygame.Rect(self.window_w - 300, 60, 96, 42)
        self.mute_btn = pygame.Rect(self.window_w - 196, 60, 84, 42)
        self.full_btn = pygame.Rect(self.window_w - 104, 60, 84, 42)
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
                game.tap(*event.pos)
            elif event.type == pygame.MOUSEMOTION:
                game.hover_arrow = game.arrow_at_pixel(*event.pos)
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

        game.update(dt)
        # Re-fetch the surface each frame so resizes / fullscreen are honoured.
        screen = pygame.display.get_surface()
        game.draw(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
