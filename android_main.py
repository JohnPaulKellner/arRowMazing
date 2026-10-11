"""Android entrypoint (python-for-android / SDL2 bootstrap).

Installs a small compat layer over the ``pygame`` module that p4a builds for
Android (pygame 2.x built against SDL2 via the ``pygame`` recipe), then runs the
exact same pygame front-end (``game.py``) as on desktop:

  * desktop has a resizable window; on Android the surface is fixed, so instead
    of a VIDEORESIZE event we re-query ``display.Info()`` on an
    ORIENTATIONCHANGE event (and on the first frame);
  * touch input surfaces through pygame's SDL2 mouse emulation as
    MOUSEBUTTONDOWN/UP/MOTION; we also translate raw FINGERDOWN/FINGERUP/
    FINGERMOTION events into the same press/release/motion handlers as a
    fallback, converting SDL's normalised (0..1) finger coords to pixels;
  * ``pygame.display.get_desktop_sizes`` may be missing in the Android pygame
    build -- the shim falls back to the current video mode / a sane default.

Nothing here runs on desktop; on desktop ``main.py`` never imports this module.
"""

from __future__ import annotations

import pygame

import game as game_mod


def _compat_install():
    """Patch the small gaps between desktop pygame-ce and the p4a pygame build."""
    if not hasattr(pygame.display, "get_desktop_sizes"):
        def get_desktop_sizes():
            try:
                info = pygame.display.Info()
                return [(info.current_w, info.current_h)]
            except Exception:
                return [(1280, 900)]
        pygame.display.get_desktop_sizes = get_desktop_sizes

    if not hasattr(pygame, "MOUSEWHEEL"):
        pygame.MOUSEWHEEL = -1  # never matches; wheel zoom stays desktop-only
    if not hasattr(pygame, "VIDEORESIZE"):
        pygame.VIDEORESIZE = -2


def run():
    _compat_install()

    pygame.init()
    try:
        pygame.mixer.init(44100, -16, 2, 512)
    except Exception:
        pass

    game = game_mod.Game(seed=None, start_level=1)

    # Fullscreen, locked to the device screen.
    try:
        dw, dh = pygame.display.get_desktop_sizes()[0]
    except Exception:
        dw, dh = 1280, 900
    game.window_w, game.window_h = int(dw), int(dh)
    game.fullscreen = True
    pygame.display.set_mode((game.window_w, game.window_h), pygame.FULLSCREEN)
    pygame.display.set_caption("arRowMazing")
    game._layout()
    game._init_buttons()

    clock = pygame.time.Clock()
    finger_down = getattr(pygame, "FINGERDOWN", -3)
    finger_up = getattr(pygame, "FINGERUP", -4)
    finger_motion = getattr(pygame, "FINGERMOTION", -5)
    orientation = getattr(pygame, "ORIENTATIONCHANGE", -6)
    resize = getattr(pygame, "VIDEORESIZE", -7)

    while game.running:
        dt = clock.tick(game_mod.FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.running = False
            elif event.type == finger_down:
                game.on_press(event.x * game.window_w, event.y * game.window_h)
            elif event.type == finger_up:
                game.on_release(event.x * game.window_w, event.y * game.window_h)
            elif event.type == finger_motion:
                game.on_motion(event.x * game.window_w, event.y * game.window_h)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                game.on_press(*event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.on_release(*event.pos)
            elif event.type == pygame.MOUSEMOTION:
                game.on_motion(*event.pos)
            elif event.type in (resize, orientation):
                try:
                    info = pygame.display.Info()
                    game.window_w, game.window_h = info.current_w, info.current_h
                except Exception:
                    pass
                game._layout()
                game._init_buttons()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_h:
                    game.show_hint()
                elif event.key == pygame.K_r:
                    game.restart()
                elif event.key == pygame.K_m:
                    game.sound.enabled = not game.sound.enabled

        game.update(dt)
        screen = pygame.display.get_surface()
        game.draw(screen)
        pygame.display.flip()

    pygame.quit()
