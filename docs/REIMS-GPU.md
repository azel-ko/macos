# Iris Xe virtual GPU experiment

This lab uses the existing x86 macOS Sonoma 14.8.8 installation. It does not
install a second macOS release or replace the normal system QEMU.

## Target and pinned sources

- Host: Linux Mint, i5-13500H, Intel Iris Xe RPL-P (`8086:a7a0`).
- Host driver: Mesa Intel Vulkan 25.2.8; device API 1.4.318.
- Guest: the existing Sonoma installation, 8 GiB RAM and 4 vCPU.
- Experimental QEMU: 11.0.50, with Reims' PCI device and Vulkan backend.
- Source commits and Rust version: `conf/reims.lock`.
- Reims source: `vendor/reims-vgpu` (ignored).
- Tools, disk copies, logs and runtime: `vendor/reims-lab` (ignored).

Upstream projects:
[reims-vgpu](https://github.com/steelbrain/reims-vgpu) and
[metal2vulkan](https://github.com/steelbrain/metal2vulkan).
This is an Alpha experiment, not a claim of complete Metal compatibility.

## Local toolchain

`setup/reims-env.sh` selects the tools extracted into the lab. It also forces
the Intel Vulkan ICD so that a successful run cannot silently use lavapipe.
It does not change shell startup files, the system driver, or system QEMU.

The initial environment was prepared without root:

- Downloaded `rustup-init` from `static.rust-lang.org`, verified its official
  SHA-256, and installed Rust 1.99.0 with `--no-modify-path --profile minimal`.
  `RUSTUP_HOME` and `CARGO_HOME` point inside the lab.
- Downloaded Ubuntu packages with `apt-get download`, then extracted them with
  `dpkg-deb -x` into `vendor/reims-lab/tools/sysroot`:
  `llvm-18`, `llvm-18-runtime`, `llvm-18-linker-tools`, `libllvm18`,
  `spirv-tools`, `libvulkan-dev`, `libslirp-dev`, `libslirp0`, `libepoxy-dev`,
  `libxkbcommon-dev`, and `libwayland-dev`.
- Adjusted the extracted `.pc` prefixes to that local sysroot. Installed system
  GLib, GTK and Pixman development packages are reused.
- Initialized the QEMU submodule at the commit recorded in `conf/reims.lock`.

For a fresh source directory, fetch the pinned commit and its QEMU submodule
before building (do not run this over an existing checkout):

```bash
test ! -e vendor/reims-vgpu || exit 1
REIMS_COMMIT=$(python3 -c 'import json; print(json.load(open("conf/reims.lock"))["reims_vgpu"])')
git init vendor/reims-vgpu
git -C vendor/reims-vgpu remote add origin https://github.com/steelbrain/reims-vgpu.git
git -C vendor/reims-vgpu fetch --depth=1 origin "$REIMS_COMMIT"
git -C vendor/reims-vgpu switch --detach FETCH_HEAD
git -C vendor/reims-vgpu submodule update --init vendor/qemu
```

Rebuild the checked-out sources with bounded parallelism:

```bash
bash setup/70-build-reims.sh
```

The script refuses a different source commit. It applies the declared local
patch idempotently and refuses unrelated tracked source edits. The local patch
adds only a narrowing diagnostic for cached surface views; it is not the
stability fix. Do not change sources during a comparison run.

## Independent copy of the current VM

First shut down the normal guest cleanly. The preparer uses the same launch
lock as `40-boot-macos.sh` and does not bypass QEMU's disk locks:

```bash
python3 setup/71-prepare-reims.py
```

It converts the current guest-visible disk state into a standalone qcow2,
compares its contents against the original, checks the new image, and copies
the matching OpenCore and OVMF pair. The base becomes read-only. The original
disk and its internal snapshot are preserved. An existing destination is never
overwritten; an incomplete preparation also requires investigation before retry.

The independent base is `vendor/reims-lab/base`. Its manifest records source
disk information, the comparison result and firmware hashes.

## Boot and verify

```bash
bash setup/72-boot-reims.sh
```

Every launch creates a new writable disk overlay and private OVMF variables.
It retains the proven 4-core topology, CPU affinity and Q35 8.2 machine model.
Reims is attached on a secondary PCI bus with its UEFI GOP ROM.
The initial profile uses the copying path (`REIMS_VGPU_GUEST_IMPORT=off`).

The accelerated lab now uses a separate OpenCore profile generated from
`conf/reims-opencore.json`. It restores four memory-related booter settings
to the values in the pinned OSX-KVM source config:

| Setting | Prior local image | Accelerated lab |
|---|---|---|
| EnableWriteUnprotector | false | true |
| RebuildAppleMemoryMap | true | false |
| SyncRuntimePermissions | true | false |
| ProvideCustomSlide | true | false |

The profile builder reads the EFI partition from a checksum-validated GPT,
changes the structured plist, verifies its readback and the new qcow2, and
records hashes. Reusing a profile requires matching source, output and settings;
an edited or incompatible existing profile is refused. The base and normal
OpenCore images are preserved. `REIMS_BOOT_PROFILE=base` selects the prior
image for a diagnostic reproduction; `REIMS_OPENCORE_FILE` selects another
explicit independent profile.

For a control using the same experimental QEMU, CPU, RAM and disk base:

```bash
REIMS_GFX_DEVICE=vmware-svga bash setup/72-boot-reims.sh
```

For an eager-versus-lazy writeback comparison, change only:

```bash
REIMS_VGPU_LAZY_WRITEBACK=off bash setup/72-boot-reims.sh
```

- SSH: `ssh -p 2223 azel@127.0.0.1` (the normal VM uses 2222).
- Active run: `vendor/reims-lab/runtime/current`.
- QMP: `current/qmp.sock`; monitor: `current/monitor.sock`.
- The Reims window uses the real Vulkan GPU. `Ctrl+Alt+Esc` releases its
  keyboard capture. Closing the window ends this test VM.
- Guest changes remain in that run's overlay. A subsequent launch starts from
  the immutable base; it does not incorporate previous experimental changes.

Once SSH is available:

```bash
python3 setup/73-verify-reims.py
```

The verifier confirms the PID belongs to this test disk, uploads the authored
Objective-C probe, compiles it in the guest, and checks:

1. A Metal device exists. The probe records both the system default and all
   enumerated devices; if the default is absent, it explicitly selects the
   first enumerated device and keeps that limitation visible in the report.
2. A compute kernel returns all 64 expected integer values exactly.
3. A rendered triangle and its clear background have the expected RGBA bytes
   after a GPU blit and CPU readback.
4. This QEMU loaded `libvulkan_intel.so` and its capability log selects Iris Xe.

The report includes per-client DRM engine counter deltas where the kernel
exposes them. Shader execution has a 30-second completion deadline; host SSH
has an overall timeout. Results and stderr are retained in the run directory.
Passing this smoke test establishes this compute/render path, not browser,
video decoding or complete Metal conformance.

After logging into the desktop, test default device selection in the actual
GUI session:

```bash
python3 setup/74-verify-gui-metal.py
```

This launches a unique temporary agent in `gui/501`, creates a small AppKit
window to attach to WindowServer, and runs the same compute/render checks.
It requires the system default Metal device to be available, even though the
lower-level smoke probe can explicitly enumerate a device. A pre-login SSH
process returning nil is insufficient evidence of a default-device defect.

Run a local Safari workload with repeated WebGL pixel readbacks, animated
layers, browser telemetry and SSH/QMP health samples:

```bash
python3 setup/77-browser-stress.py --seconds 600
```

The page has no external dependencies. Its frame-callback rate is not displayed
FPS. The runner retains telemetry, final results and guest health in the run
directory. A fresh launch starts from the same immutable base; lab guest
changes are retained only in that launch's overlay.

For a crash, boot with `REIMS_SHUTDOWN_ACTION=pause`. QEMU then preserves RAM
after the guest requests a panic reboot. `REIMS_GDB=1` enables a private Unix
GDB socket in the run directory. The QMP helper verifies the selected PID's
exact disk field before control operations:

```bash
python3 setup/reims_qmp.py status
python3 setup/reims_qmp.py capture --stop
python3 setup/reims_qmp.py hmp 'info registers' --cpu 3
python3 setup/reims_qmp.py quit
```

Capture preserves all CPU registers and addresses explicitly named by the
panic. `capture --stop` deliberately leaves a running guest paused. Do not
resume a panic to collect more evidence.

## Baseline and current result

Before switching devices, the same authored probe compiled successfully and
returned `No Metal device` on the normal Sonoma VM. The guest's existing Swift
SDK has module compatibility errors, so the probe uses Objective-C and Clang
without modifying the guest developer installation.

The experimental build and UEFI ROM build succeeded. On 2026-10-10, run
`run-fmBpeClm` passed compute, render, blit and exact CPU readback on the
enumerated `Apple Paravirtual device`. Its QEMU process loaded
`libvulkan_intel.so`, selected Iris Xe, and recorded 47,952,320 ns of additional
render-engine activity during the initial compilation/probe interval. Five
immediate repetitions also passed before console login; two further probes
passed with console user `azel` after login. These are small correctness
probes, not a throughput benchmark.

A fresh boot (`run-kbsnaV9H`) independently passed the same verifier and five
additional pre-login repetitions. This confirms the small accelerated workload
across two fresh overlays; it does not change the post-login failures below.

Historical failures using the prior local OpenCore memory settings:

- Early SSH probes returned nil from `MTLCreateSystemDefaultDevice()`. Later
  GUI verification on the corrected profile attaches to WindowServer and
  obtains the default device without framework patches or interposition.
- The first GPU run (`run-bjQO1PKW`) panicked after login in `vm_page_lookup`
  while WeatherWidget was running. The eager-writeback comparison
  (`run-OuPowOxr`) also panicked on that path while ScreenTimeAgent was running.
  Disabling lazy writeback did not fix the problem; these task names do not
  establish either app as its cause.
- The probe-passing run (`run-fmBpeClm`) subsequently panicked after login
  with a kernel spinlock timeout while IMDPersistenceAgent was running.
  A passing smoke test therefore does not clear the stability failure.
- The same QEMU with `vmware-svga` (`run-rq69iGtg`) remained responsive for
  approximately six minutes with WeatherWidget running and no observed panic.
  This is useful control evidence, not proof of the bridge's root defect.

- An anonymous-RAM comparison (`run-CtxnW4Oz`) still panicked. A later
  memfd run (`run-qrm8KXtI`) panicked before console login at 51 seconds;
  the failure is therefore not limited to post-login applications. Captured
  guest CPU page tables contained an invalid leaf entry with reserved bits.
- Disabling optional cached surface views (`run-crUqCjJq`) preserved Metal
  compute/render correctness but still panicked at about 100 seconds. The
  `REIMS_VGPU_CACHED_VIEWS=off` patch remains diagnostic, not a claimed fix.
- Disabling WhateverGreen on a private OpenCore image (`run-TwygM0SY`) still
  panicked at about 93 seconds. An earlier attempt to disable every CPU page
  mapping stopped required completion-stamp writes and could not finish boot;
  that prototype was not retained as a product switch or counted as stability
  evidence.

The corrected four-setting OpenCore profile was tested on two fresh overlays
on 2026-10-10, with the same QEMU binary and source patch:

| Run | Safari workload | Browser reports | Observed panic | Post-load default GUI Metal |
|---|---|---|---|---|
| `run-JW4LHbNB` | 600.02 seconds | 298 | none | passed |
| `run-hhaCQbNz` | 600.69 seconds | 298 | none | passed |

Both runs reached the desktop and passed compute, render, blit and exact
readback with the system default device in a WindowServer-connected process.
The first browser probe checked WebGL pixels initially and then continuously
reported animation and health. The second repeated pixel readback on every
report; all pixels matched, with a maximum host report gap of about 2.02
seconds. Replaying its raw reports through the stricter browser evidence gate
also passed. Animation callback counts are not measured display frame rates.

This comparison supports the four-setting configuration set as a remedy for
the reproduced crashes on this machine; it does not isolate one individual
quirk or establish a fix for all upstream guest-memory panic classes.

IntelliJ IDEA 2026.2 launched and opened the authored probe, but its default
editor rendering showed extensive black areas and blue artifacts. A second
launch with a separate temporary VM-options file disabling Java2D Metal and
OpenGL showed the same corruption; `jcmd VM.system_properties` confirmed both
overrides took effect. This fails visual correctness and is not an IDE
usability pass or a working software-rendering workaround. Safari also showed an
initial paint artifact before repainting correctly. Full Metal conformance
was not run because of the guest Swift SDK compatibility problem. Multi-hour
stability, ordinary project indexing/editing, and hardware video decoding
remain unverified. These limits prevent claiming a fully usable daily desktop.

The launcher's teardown also has a regression test: editing its source while
a stub QEMU is blocked must still exit cleanly. Earlier editing during a live
debug run caused a shell parse error after a confirmed guest shutdown; this
was a harness failure, separate from the guest kernel panics. The final parsed
command block prevents Bash resuming at a stale source-file offset.

A sanitized, versioned result summary is in `docs/reims-validation.json`.
Local verification passed 36 Python tests, 34 serial Rust mapper tests and 15
Rust configuration tests, plus Bash syntax, Python compilation and Rust format
checks. Clippy completed with 28 existing warnings; none were on changed lines.

Logs, overlays, registry capture and probe output are retained under
`vendor/reims-lab/runtime`. They are ignored by Git. Guest binaries, RAM
captures, firmware, private disks and third-party disassembly are not published.

## Development direction

The path is macOS Metal -> built-in AppleParavirtGPU driver -> Reims QEMU PCI
device -> host Vulkan -> Mesa Intel -> Iris Xe. `metal2vulkan` translates AIR
shaders into SPIR-V; Reims owns command decoding, resource bindings, memory
lifetimes, synchronization and presentation. The translator alone cannot expose
a GPU to macOS.

The next milestones are:

1. Keep repeated-boot and sustained-load evidence tied to the exact OpenCore,
   source patch and QEMU hashes; extend the confirmed configuration's coverage.
2. Test ordinary application device selection in a real GUI session, preserving
   a strict default-device gate instead of hiding nil behind enumeration.
3. Extend browser/IDE workloads and multi-hour sessions, checking visual
   correctness, memory growth and input responsiveness.
4. Optimize measured costs such as shader compilation, staging copies and
   presentation. Re-enable optional direct guest-memory imports only after
   validating their lifetime and synchronization contracts.

VideoToolbox hardware video decoding is a separate compatibility milestone;
passing the Metal render/compute probe does not establish it.

## Return to the normal VM

Shut down the test guest first, then run:

```bash
bash setup/40-boot-macos.sh
```

This uses the original disk, original persistent firmware variables and system
QEMU. Experimental overlays are retained for diagnosis and are not merged.
