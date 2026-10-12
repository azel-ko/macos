# This lab runs on Mint X11. Ubuntu 24.04's Wayland headers predate SDL 3.4's
# repeated-key enum; do not compile an unused Wayland backend against them.
set(SDL_WAYLAND OFF CACHE BOOL "The local lab uses X11" FORCE)
set(SDL_X11 ON CACHE BOOL "Build the X11 window backend" FORCE)
set(SDL_SHARED OFF CACHE BOOL "QEMU links the static SDL bundled by dist" FORCE)
