"""Check authored color samples in a host-owned, aspect-fitted guest frame."""
import re


def ide_file_opened(log, filename):
    name = re.escape(filename)
    return bool(re.search(r"\bfileOpened " + name + r"(?:\s|$)", log)
                or re.search(r"\bOpened new tab for /Users/azel/" + name + r"(?:\s|$)", log))


def display_window(rows, pid):
    matches = []
    for row in rows:
        fields = row.split(None, 4)
        if len(fields) == 5 and fields[2] == str(pid) and re.fullmatch(
                r"Reims vGPU(?: \(port \d+\))?(?: \u2014 input captured \(press [^\n]+ to release\))?", fields[4]):
            matches.append(fields[0])
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one Reims host window for the selected PID")
    return matches[0]


def editor_target(report):
    width, height = report["screen"]
    windows = [w["bounds"] for w in report["windows"]
               if w["bounds"]["Width"] >= 120 and w["bounds"]["Height"] >= 80]
    if len(windows) != 1:
        raise RuntimeError("Close IntelliJ dialogs (including the first LightEdit introduction) before testing input")
    frame = windows[0]
    if frame["Width"] < 500 or frame["Height"] < 300:
        raise RuntimeError("Expected the authored file's editor window")
    x, y = frame["X"] + frame["Width"] * .5, frame["Y"] + frame["Height"] * .4
    if not 0 <= x < width or not 0 <= y < height:
        raise RuntimeError("Editor target is outside the primary display")
    return round(x / width * 32767), round(y / height * 32767)


def palette_evidence(image, report, tolerance=24):
    width, height = report["screen"]
    if width <= 0 or height <= 0 or len(report["samples"]) != 6:
        raise ValueError("Expected a screen size and six authored color samples")
    scale = min(image.width / width, image.height / height)
    left = (image.width - width * scale) / 2
    top = (image.height - height * scale) / 2
    rgb = image.convert("RGB")
    samples = []
    expected = [(255,0,0), (0,255,0), (0,0,255), (0,255,255), (255,0,255), (255,255,0)]
    for item, color in zip(report["samples"], expected):
        if tuple(item["rgb"]) != color:
            raise ValueError("Report does not describe the authored six-color fixture")
        if not 0 <= item["x"] < width or not 0 <= item["y"] < height:
            raise ValueError("Color sample lies outside the guest screen")
        x, y = round(left + item["x"] * scale), round(top + item["y"] * scale)
        actual = rgb.getpixel((min(x, image.width - 1), min(y, image.height - 1)))
        passed = all(abs(a - b) <= tolerance for a, b in zip(actual, item["rgb"]))
        samples.append({"host_xy": [x, y], "expected": item["rgb"], "actual": list(actual), "pass": passed})
    return {"pass": all(item["pass"] for item in samples), "samples": samples}
