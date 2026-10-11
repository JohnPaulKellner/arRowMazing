#!/usr/bin/env python3
"""arRowMazing entrypoint.

Desktop: ``python main.py`` runs the pygame game directly (unchanged behaviour;
``--seed`` / ``--level`` flags are handled in ``game.main``).

Android: python-for-android's SDL2 bootstrap runs this same ``main.py`` from the
packaged private data dir. We detect Android and delegate to
``android_main.run()``, which installs a small pygame compat shim (touch input,
fullscreen, mixer init) and then runs the identical game loop.
"""

from __future__ import annotations

import os
import sys

IS_ANDROID = (os.environ.get("P4A_BOOTSTRAP") is not None
              or "android" in getattr(sys, "platform", ""))


def main():
    sys.argv[0] = "arRowMazing"
    if IS_ANDROID:
        import android_main
        android_main.run()
    else:
        import game
        game.main()


if __name__ == "__main__":
    main()
