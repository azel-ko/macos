#!/usr/bin/env bash
# Keep the Beta toolchain and build separate from the legacy Alpha checkout.
source "$(dirname "${BASH_SOURCE[0]}")/reims-env.sh"
export REIMS_PROJECT_ROOT
export REIMS_BETA_SOURCE="$REIMS_PROJECT_ROOT/vendor/reims-vgpu-beta"
export REIMS_BETA_CACHE="${REIMS_BETA_CACHE:-$HOME/.cache/macos-reims-beta}"
export CARGO_TARGET_DIR="$REIMS_BETA_CACHE/target"
# The local stable alias is checked against conf/reims-beta.lock before builds.
export RUSTUP_TOOLCHAIN="${REIMS_RUST_TOOLCHAIN:-stable}"
export PATH="$REIMS_LAB_ROOT/tools/sysroot-beta/usr/lib/llvm-18/bin:$REIMS_LAB_ROOT/tools/sysroot-beta/usr/bin:$PATH"
export LD_LIBRARY_PATH="$REIMS_LAB_ROOT/tools/sysroot-beta/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="$REIMS_LAB_ROOT/tools/sysroot-beta/usr/lib/x86_64-linux-gnu/pkgconfig:$PKG_CONFIG_PATH"
export CFLAGS="-I$REIMS_LAB_ROOT/tools/sysroot-beta/usr/include $CFLAGS"
export LDFLAGS="-L$REIMS_LAB_ROOT/tools/sysroot-beta/usr/lib/x86_64-linux-gnu $LDFLAGS"
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
export CMAKE_TOOLCHAIN_FILE="$REIMS_PROJECT_ROOT/conf/reims-beta-x11.cmake"
