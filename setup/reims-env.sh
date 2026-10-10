#!/usr/bin/env bash
# Source this file to use the isolated, unprivileged Reims toolchain.
REIMS_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REIMS_LAB_ROOT="$REIMS_PROJECT_ROOT/vendor/reims-lab"
export RUSTUP_HOME="$REIMS_LAB_ROOT/tools/rustup"
export CARGO_HOME="$REIMS_LAB_ROOT/tools/cargo"
export PATH="$CARGO_HOME/bin:$REIMS_LAB_ROOT/tools/sysroot/usr/lib/llvm-18/bin:$REIMS_LAB_ROOT/tools/sysroot/usr/bin:$PATH"
export PKG_CONFIG_PATH="$REIMS_LAB_ROOT/tools/sysroot/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export LD_LIBRARY_PATH="$REIMS_LAB_ROOT/tools/sysroot/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CFLAGS="-I$REIMS_LAB_ROOT/tools/sysroot/usr/include${CFLAGS:+ $CFLAGS}"
export LDFLAGS="-L$REIMS_LAB_ROOT/tools/sysroot/usr/lib/x86_64-linux-gnu${LDFLAGS:+ $LDFLAGS}"
export METAL2VULKAN_LLVM_DIS="$REIMS_LAB_ROOT/tools/sysroot/usr/lib/llvm-18/bin/llvm-dis"
export METAL2VULKAN_SPIRV_VAL="$REIMS_LAB_ROOT/tools/sysroot/usr/bin/spirv-val"
# Select the actual Intel GPU; do not silently validate on lavapipe/llvmpipe.
export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/intel_icd.json
export VK_ICD_FILENAMES="$VK_DRIVER_FILES"
export REIMS_VGPU_BACKEND=vulkan
# Bound compilation while the normal 8 GiB guest is still running.
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
