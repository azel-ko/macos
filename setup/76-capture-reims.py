#!/usr/bin/env python3
"""Capture only the host-owned Reims window belonging to the identified VM."""
from datetime import datetime
from pathlib import Path
import subprocess
import time

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11

from reims_qmp import ROOT, identified_run
from reims_visual import display_window


def capture():
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    pid = (run / "qemu.pid").read_text().strip()
    rows = subprocess.check_output(["wmctrl", "-lp"], text=True).splitlines()
    xid = display_window(rows, pid)
    # X11 readback of a hidden/occluded window is not reliable. Raise only the
    # identified test VM before taking evidence, never an unrelated window.
    subprocess.run(["wmctrl", "-ia", xid], check=True)
    time.sleep(.25)
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("An X11 display is required")
    window = GdkX11.X11Window.foreign_new_for_display(display, int(xid, 16))
    pixels = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
    if pixels is None:
        raise RuntimeError("Unable to capture the Reims window")
    target = run / (datetime.now().strftime("window-%Y%m%d-%H%M%S") + ".png")
    pixels.savev(str(target), "png", [], [])
    print(target)
    return target


if __name__ == "__main__":
    capture()
