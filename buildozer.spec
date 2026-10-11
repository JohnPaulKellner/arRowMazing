[app]
title = arRowMazing
package.name = arrowmazing
package.domain = org.arrowmazing

# Only app code is packaged into the APK (the whole source.dir is tarred into
# the APK's private data, so keep tooling out with exclude_dirs).
source.dir = .
source.exclude_dirs = .venv-build, p4a-recipes, bin, .github
source.include_exts = py,ttf,txt,md
version = 1.0

# pygame (built by p4a's pygame recipe against SDL2) + numpy (for sndarray).
requirements = pygame,numpy,pyjnius,android,setuptools,six

# SDL2 bootstrap
bootstrap = sdl2

orientation = all
fullscreen = 1

# Local recipe overrides: python3/hostpython3 3.13.16, pygame 2.6.1.
p4a.local_recipes = p4a-recipes

android.api = 34
android.minapi = 24
android.ndk_api = 24
android.ndk = 28c
# APK artifacts (not aab).
android.release_artifact = apk
android.debug_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
