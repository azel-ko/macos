# IntelliJ rendering investigation

The isolated Beta candidate fixes the observed LightEdit painting failure
on this host and passes keyboard save and scrolling checks. It remains
opt-in: a sustained browser run lost the host GPU, so daily-use stability
is not established. Machine-readable evidence is in
[intellij-validation.json](intellij-validation.json).

The target is the local Intel i5-13500H / Iris Xe RPL-P (`8086:a7a0`),
Linux Mint X11 host and the existing macOS Sonoma 14.8.8 guest, with 8 GiB
RAM and four vCPUs. Original disks and the Alpha checkout are preserved;
each comparison writes a fresh overlay of the same read-only base.

## Reproduced control, 2026-10-12

`run-Qhr3AJO3`, on the pinned Alpha build, reproduced the IntelliJ IDEA
2026.2 LightEdit window with extensive black areas and blue specks. The
captured JVM properties and host frame remain in its ignored run directory.
Previous tests disabling Java2D Metal and OpenGL also failed visually.

The earlier final Alpha run, `run-gTADRHp0`, subsequently panicked at
4,179.26 seconds of guest uptime, with an IPI timeout in `pmap.c`. Its
device log also contains page-table-write guard observations. Those are
evidence to investigate, not an isolated causal proof. The two earlier
600-second passing browser runs remain valid for their bounded intervals;
the four OpenCore settings did not establish long-term stability.

## Independent Beta candidate

The upstream rewrite is now published on
[master](https://github.com/steelbrain/reims-vgpu/tree/9b2c5452de94a474cba28d80d7f99d9d7b19ffe3).
`conf/reims-beta.lock` pins the library, its matching QEMU, metal2vulkan,
and the Rust compiler actually used here. This is a complete upstream
implementation comparison, not an isolated fix to a single Alpha defect.

The source directory is `vendor/reims-vgpu-beta`. On a fresh clone, fetch
that exact commit and initialize `vendor/qemu` at its gitlink. Clone the
translator independently into `vendor/metal2vulkan-beta` at its pinned
commit too. `patches/reims-beta-runtime.patch` connects both library
dependencies to that same local checkout. Its declared patch is
`patches/reims-beta-intel-depth.patch`; the builder checks both source
commits and exact patches, and the launch manifest hashes both patches.
The dependency route is consistent, so the driver and translator share
the same Rust API types. The Alpha device, ROM and checkout are preserved.

For a new lab, populate the separate source directories before building
(do not reuse these commands to reset an existing edited checkout):

```bash
git clone --no-checkout https://github.com/steelbrain/reims-vgpu.git vendor/reims-vgpu-beta
git -C vendor/reims-vgpu-beta switch --detach 9b2c5452de94a474cba28d80d7f99d9d7b19ffe3
git -C vendor/reims-vgpu-beta submodule update --init vendor/qemu
git clone --no-checkout https://github.com/steelbrain/metal2vulkan.git vendor/metal2vulkan-beta
git -C vendor/metal2vulkan-beta switch --detach 13b279df1bf87893d389f955a90c55b6ff3d0f9b
```

Prepare the read-only base and original OpenCore profile as described in
[the lab guide](REIMS-GPU.md) before launching. Then:

```bash
bash setup/80-build-reims-beta.sh
REIMS_STACK=beta bash setup/72-boot-reims.sh
```

The builder checks source pins, the exact declared patch and Rust version.
The launcher verifies a build manifest containing source pins, patch hash,
QEMU path/hash and ROM path/hash before creating a run. Beta uses
`apple-gfx-pci`, the matching `ReimsVgpu.rom`, shared memfd RAM and a
1920x1080 display. Alpha-only memory switches are removed for Beta.
`REIMS_STACK=legacy` retains the Alpha control. Neither merges overlays.

Build requirements include the earlier local toolchain plus clang/lld,
CMake and SDL's X11 development dependencies. This host extracts Ubuntu
packages into `vendor/reims-lab/tools/sysroot-beta`; the builder relocates
their pkg-config prefixes and resolves development-library links against
installed runtime libraries without writing system directories. Normal
system-installed development packages can also satisfy these tools.
`REIMS_RUST_TOOLCHAIN` may select an installed Rust 1.99.0 toolchain;
the actual compiler version must match the pin.

`conf/reims-beta-x11.cmake` builds SDL's X11 backend and static library.
Ubuntu 24.04's Wayland headers lack `WL_KEYBOARD_KEY_STATE_REPEATED`, used
by the newer SDL release. This lab does not validate Wayland. CMake reads
the toolchain on a fresh configure; a pre-existing SDL configure made
without it needs its generated CMake state preserved aside and configured
again. Guest GPU semantics are not changed by this host-window selection.
The patches also use Rust 1.99's `Atomic::try_update` name and remove two
needless closure borrows reported by that compiler's Clippy; these do not
change the guest rendering policy.
QEMU's container test detection is disabled. Configure arguments, include
and link paths, and the library's pkg-config content form a configuration
fingerprint; changes trigger reconfiguration before linking.

## Measured Intel depth-copy path

The unmodified Beta (`run-S3LIsJaD`) aborted during desktop startup with
`MultisampledBufferCopy`: a 54x54, four-sample `Depth32Float` upload.
Its existing sample-interleave implementation could create the intermediate
images, but refused the final fragment-depth move on the unmeasured driver.
A new owner GPU test independently reproduced that exact refusal before
the change; it does not depend on a guest shader or a Metal compiler.

The diagnostic run copied 32 authored raw float bit patterns into a
four-sample depth texture and read every sample back. Normal finite unit
depths were retained; negative zero, negative values, subnormals and NaNs
returned +0, while values above one and positive infinity returned one.
The final regression checks all 32 expected results and the per-sample
layout, rather than checking only successful command completion.

The existing depth-draw path is selected only for driver
`INTEL_OPEN_SOURCE_MESA`, PCI `8086:a7a0`, driver version `0x06402008`
(Mesa 25.2.8). Other GPU IDs or releases do not inherit this record.
The runtime announces `metal2vulkan-degrade-drawn-depth-copy` with the
observed changes. This is a bounded, announced compatibility path, not
bit-exact Metal conformance for arbitrary depth data.

```bash
# Stop both VMs first; this takes their launch locks and runs GPU tests serially.
bash setup/83-test-intel-depth.sh
```

The upstream general fragment-depth lane could not execute with the local
LLVM 18 assembler because its newer IR uses `captures(none)`. Its result
is not counted as a pass. The targeted owner test exercises the actual
buffer-to-MSAA-depth route through the crate's own interleave/draw modules.

## Repeatable checks

After desktop login:

```bash
python3 setup/73-verify-reims.py
python3 setup/74-verify-gui-metal.py
python3 setup/78-verify-java2d.py
python3 setup/79-verify-intellij.py
python3 setup/77-browser-stress.py --seconds 600
python3 -m unittest discover -s tests -v
```

The Metal verifier checks exact compute and render/readback results and
the running process's Intel Vulkan library plus DRM render-node PCI ID.
It reads Beta diagnostics from that run's QEMU log, never a stale Alpha log.

The Java2D fixture runs on IntelliJ's installed JBR, with Metal requested;
its graphics configuration must identify the Metal pipeline.
Six known palette centers are checked in a host-owned frame, accounting
for aspect-fit letterboxing, and keyboard input must reach its text area.
The fixture's paint callback count is not a display FPS measurement.

On first launch, choose Continue Using LightEdit in its introduction dialog
before running the input check. The check refuses to type through a dialog.
It opens a unique authored 500-line file, waits for its `fileOpened` log,
checks the front application via AppKit, reads only that process's window
geometry through CoreGraphics, and clicks inside the single editor window.
It explicitly requests `-e` through the documented macOS
[command-line launcher](https://www.jetbrains.com/help/idea/working-with-the-ide-features-from-command-line.html).
Without that flag, an already restored project can treat the file as a
project path; an observed retry stopped at a subscription dialog instead
of opening its fixture. The test does not activate or change subscriptions,
and refuses to type while other editor windows or dialogs are present.
It accepts the file-open event or LightEdit's first-tab event, never the
before-open event; unrelated startup logging cannot push the event out of
a 100-line polling window. It sends mouse-wheel scrolls, replaces only
that fixture's content and saves it. SSH readback
must equal the typed marker. Host captures still require visual review:
the automatic input gate alone cannot prove the editor is drawn correctly.
This covers LightEdit; project indexing, builds, plugins and debugging
need separate workloads.

All raw frames, guest outputs, private disks and build products stay in
ignored directories. Only authored test code and sanitized result summaries
belong in Git.

`setup/84-gpu-diagnostics.py --run <run-directory>` extracts validation IDs,
device-loss counts and kernel GPU HANG entries explicitly naming that run's
QEMU PID. It bounds dead-process queries by the retained QEMU/serial output
times (plus 60 seconds for deferred kernel reporting), limiting attribution
to that interval rather than later host activity. It records unavailable
journal access explicitly; it does not label missing evidence as a pass.
Run the tool while the VM is alive to retain its PID for clean-exit analysis;
QEMU removes its pidfile on clean exit. Without a pidfile or this run's
earlier diagnostic record, the journal result is explicitly unavailable.
The launcher also holds the normal VM's launch lock during a lab run,
preventing the two launchers from overlapping GPU work.

## Observed limits

`run-GfjP3AnY` passed the Metal, Java2D and LightEdit input/save checks.
The local Safari stress then failed after 469.75 seconds (last browser
telemetry at 421.27 seconds); it did not complete its requested 600 seconds.
The host kernel recorded an i915 `GPU HANG` for that QEMU PID, with ecode
`12:1:859ffffb`. QEMU subsequently aborted with Vulkan device lost. No
guest XNU panic was recorded in that run. The failed test is retained;
it is not replaced by a shorter passing interval.

The memory owner retains imported guest-page aliases until GPU work
completes. Host-pointer import is required by this Beta runtime's NoCopy
contract; disabling an Alpha memory flag does not give Beta a copying
fallback. The failure's cause has not been isolated to imports, translation,
synchronization or the host driver. No speculative workaround changes those
contracts here.

The second fresh Beta run, `run-YwDEaswt`, again passed Metal and Java2D.
Its LightEdit frames showed the first visible line move from 1 to 48 after
mouse-wheel input, then a clean saved marker. The IDE JVM explicitly
reported `sun.java2d.metal=true` and JBR `25.0.3+9-b508.16`.

This diagnostic run additionally loaded Khronos validation layer 1.3.275
(confirmed in QEMU's process mappings), while the device API is 1.4.318.
This older layer cannot establish conformance to newer Vulkan contracts;
its overhead also changes timing. Enabling it is documented by the
[Vulkan Loader](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderInterfaceArchitecture.md#table-of-debug-environment-variables).
With the extracted layer installed, the diagnostic launch is:

```bash
VK_LAYER_PATH="$PWD/vendor/reims-lab/tools/sysroot-beta/usr/share/vulkan/explicit_layer.d" \
VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation \
REIMS_STACK=beta bash setup/72-boot-reims.sh
python3 setup/84-gpu-diagnostics.py
```

The pinned Beta's `answer::relay_to` discards callback messages whose IDs
do not begin with `metal2vulkan-`, including driver/layer validation
messages. A loaded validation library and no VUID in QEMU's log therefore
do not prove clean API usage. The diagnostic summary explicitly marks
layer-message capture unverified. A follow-up diagnostic run must route
the layer's own messages to a verified sink before using VUID absence as
evidence; this run is a workload comparison with the layer loaded.

That run completed the requested Safari workload in 600.41 seconds with
298 telemetry reports. All required WebGL pixels, continuous activity and
guest health gates passed; no host GPU HANG was found in the measured
interval. Java2D's Metal palette/input check also passed after the workload.
The post-load LightEdit retry was blocked by a restored project's expired
subscription dialog, so it is not counted as a post-load IDE pass.

After correcting the launcher to request LightEdit explicitly, a third
fresh overlay (`run-0RBftFdT`) using the final binary without a validation
layer passed the editor input/save check, showed lines 1 and 48 correctly
before/after scrolling, and passed Java2D's palette/input check. The browser
stress was not repeated in that third run. This confirms the final test
entry point without treating the earlier non-validation GPU hang as fixed.

The local project suite passes 52 tests. The three targeted owner regressions
pass with warnings treated as errors; 22 supported color-copy combinations
ran and 10 unsupported eight-sample combinations were reported explicitly.
Rustfmt and the affected runtime library's release Clippy check passed.
The whole upstream workspace CI matrix was not run.

The guest retains `sleep=0`, `displaysleep=10`, `disksleep=10`.
`pmset displaysleepnow` returned success, but SSH samples still observed
IODisplayWrangler at power state 4. This did not verify a sleep/wake cycle
and does not explain the earlier hang. No persistent power setting was
changed. To inspect that boundary without assuming the request took effect:

```bash
ssh -p 2223 azel@127.0.0.1 'pmset -g custom; pmset -g assertions'
ssh -p 2223 azel@127.0.0.1 'pmset displaysleepnow'
ssh -p 2223 azel@127.0.0.1 'ioreg -r -n IODisplayWrangler -d 1'
```

Project indexing/build/debug workloads, video decoding, displayed FPS and
multi-hour stability remain unverified. A release candidate needs repeated
sustained runs without device loss or a kernel GPU hang before becoming the
default.
