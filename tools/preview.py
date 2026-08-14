"""Renders the addon window to an SVG, without Kodi.

Not a hand-drawn mockup: it parses the real skin XML for the fixed furniture,
runs the real gui.py against the stub bindings so every board row, radar blip
and map line is placed by the actual code, and fills it with a live poll. If
the layout is wrong here it is wrong on the telly too.

Run:  python tools/preview.py [--offline] [--view board|radar|map|all]
"""

import base64
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.join(os.path.dirname(HERE), "script.flighttracker")

os.environ["FLIGHTTRACKER_ADDON_ROOT"] = ADDON_ROOT
sys.path.insert(0, os.path.join(HERE, "kodistubs"))
sys.path.insert(0, ADDON_ROOT)

import xbmcaddon  # noqa: E402
import xbmcgui  # noqa: E402

from resources.lib import config, gui  # noqa: E402
from resources.lib.logos import LogoStore  # noqa: E402
from resources.lib.tracker import PollResult, Tracker  # noqa: E402

MEDIA = os.path.join(ADDON_ROOT, "resources", "media")
SKIN_XML = os.path.join(ADDON_ROOT, "resources", "skins", "Default", "1080i",
                        "script-flighttracker-main.xml")
PO_PATH = os.path.join(ADDON_ROOT, "resources", "language",
                       "resource.language.en_gb", "strings.po")

# Estuary's real sizes. Anything it does not define falls back to 30px.
FONT_PX = {"font10": 23, "font12": 25, "font13": 30, "font14": 33,
           "font27": 27, "font32": 32, "font37": 37, "font45": 45, "font60": 60}
DEFAULT_FONT_PX = 30
FONT_STACK = "'Noto Sans','DejaVu Sans','Segoe UI',Arial,sans-serif"

VIEW_NAMES = {"board": config.VIEW_BOARD, "radar": config.VIEW_RADAR,
              "map": config.VIEW_MAP}

_data_uri_cache = {}
_filters = {}


def strings():
    table = {}
    with open(PO_PATH, "r", encoding="utf-8") as handle:
        text = handle.read()
    for match in re.finditer(r'msgctxt "#(\d+)"\s*\nmsgid "((?:[^"\\]|\\.)*)"', text):
        table[int(match.group(1))] = match.group(2).replace('\\"', '"')
    return table


STRINGS = strings()


def font_px(name):
    return FONT_PX.get(name or "", DEFAULT_FONT_PX)


def data_uri(path):
    if path not in _data_uri_cache:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
        kind = "jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "png"
        _data_uri_cache[path] = "data:image/%s;base64,%s" % (kind, encoded)
    return _data_uri_cache[path]


def resolve_texture(raw):
    if not raw:
        return None
    raw = raw.strip()
    marker = "resources/media/"
    if marker in raw:
        return os.path.join(MEDIA, raw.split(marker, 1)[1])
    return raw if os.path.isabs(raw) and os.path.exists(raw) else None


def argb(value, fallback="FFFFFFFF"):
    text = (value or fallback).strip().lstrip("#")
    if text.startswith("0x"):
        text = text[2:]
    if len(text) == 6:
        text = "FF" + text
    if len(text) != 8:
        text = fallback
    return "#" + text[2:], int(text[0:2], 16) / 255.0


def tint_filter(colour_hex):
    if colour_hex in _filters:
        return _filters[colour_hex][0]
    name = "tint%d" % len(_filters)
    r = int(colour_hex[1:3], 16) / 255.0
    g = int(colour_hex[3:5], 16) / 255.0
    b = int(colour_hex[5:7], 16) / 255.0
    _filters[colour_hex] = (name,
                            '<filter id="%s" color-interpolation-filters="sRGB">'
                            '<feColorMatrix type="matrix" values="'
                            '%.4f 0 0 0 0  0 %.4f 0 0 0  0 0 %.4f 0 0  0 0 0 1 0"/>'
                            '</filter>' % (name, r, g, b))
    return _filters[colour_hex][0]


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def geometry(control):
    def value(tag, default=0):
        node = control.find(tag)
        try:
            return int((node.text or "").strip())
        except (AttributeError, ValueError):
            return default
    return value("left"), value("top"), value("width"), value("height")


def child_text(control, tag):
    node = control.find(tag)
    return (node.text or "").strip() if node is not None else ""


def text_element(x, y, width, height, label, font, colour, anchor="start"):
    if not label:
        return ""
    size = font_px(font)
    fill, opacity = argb(colour)
    if anchor == "end":
        tx = x + width
    elif anchor == "middle":
        tx = x + width / 2.0
    else:
        tx = x
    ty = y + size * 0.80
    return ('<text x="%.1f" y="%.1f" font-family="%s" font-size="%d" fill="%s" '
            'fill-opacity="%.3f" text-anchor="%s" xml:space="preserve">%s</text>'
            % (tx, ty, FONT_STACK, size, fill, opacity, anchor, esc(label)))


def image_element(x, y, width, height, path, diffuse, stretch=True):
    if not path or not os.path.exists(path):
        return ""
    if os.path.basename(path) == "white.png":
        fill, opacity = argb(diffuse)
        return ('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" fill-opacity="%.3f"/>'
                % (x, y, width, height, fill, opacity))
    attributes = ' preserveAspectRatio="%s"' % ("none" if stretch else "xMidYMid meet")
    if diffuse:
        fill, opacity = argb(diffuse)
        if fill.upper() != "#FFFFFF" or opacity < 0.999:
            attributes += ' filter="url(#%s)" opacity="%.3f"' % (tint_filter(fill), opacity)
    return ('<image x="%d" y="%d" width="%d" height="%d" href="%s"%s/>'
            % (x, y, width, height, data_uri(path), attributes))


def render_stub_controls(controls):
    """Draw whatever gui.py actually added to the window at runtime."""
    parts = []
    for control in controls:
        if not getattr(control, "visible", True):
            continue
        if isinstance(control, xbmcgui.ControlImage):
            parts.append(image_element(control.x, control.y, control.width, control.height,
                                       control.filename, control.colorDiffuse,
                                       stretch=(control.aspectRatio == 0)))
        elif isinstance(control, xbmcgui.ControlLabel):
            alignment = control.alignment or 0
            anchor = "middle" if alignment & 2 else ("end" if alignment & 1 else "start")
            parts.append(text_element(control.x, control.y, control.width, control.height,
                                      control.label, control.font, control.textColor, anchor))
    return parts


def render_button(control, label, focused):
    x, y, width, height = geometry(control)
    texture = control.find("texturefocus" if focused else "texturenofocus")
    diffuse = texture.get("colordiffuse") if texture is not None else "FF1E1B17"
    fill, opacity = argb(diffuse)
    colour = child_text(control, "focusedcolor" if focused else "textcolor")
    size = font_px(child_text(control, "font"))
    fill_text, text_opacity = argb(colour)
    return ['<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s" fill-opacity="%.3f"/>'
            % (x, y, width, height, fill, opacity),
            '<text x="%.1f" y="%.1f" font-family="%s" font-size="%d" fill="%s" '
            'fill-opacity="%.3f" text-anchor="middle" xml:space="preserve">%s</text>'
            % (x + width / 2.0, y + height / 2.0 + size * 0.35, FONT_STACK, size,
               fill_text, text_opacity, esc(label))]


def build(view_mode, offline=False, tracker=None, logos=None):
    cfg = config.from_addon(xbmcaddon.Addon())
    cfg.view_mode = view_mode

    window = gui.FlightWindow(gui.XML_NAME, ADDON_ROOT, "Default", "1080i")
    window.controls = {cid: xbmcgui.ControlBase() for cid in (
        gui.TITLE_ID, gui.STATUS_ID, gui.RADAR_ID, gui.LEGEND_ID, gui.RANGE_ID,
        gui.MESSAGE_ID, gui.BTN_REFRESH, gui.BTN_VIEW, gui.BTN_SETTINGS)}

    if tracker is None:
        cache = os.path.join(tempfile.mkdtemp(prefix="ftpreview"), "routes.json")
        tracker = Tracker(cfg, cache)
    else:
        tracker.update_config(cfg)
    window.prepare(xbmcaddon.Addon(), cfg, tracker, MEDIA, lambda: cfg, logo_store=logos)

    window._sync_panel_visibility()
    window._sync_buttons()
    window._draw_panel()

    if offline:
        result = PollResult([])
    else:
        result = tracker.poll()
    window._render(result)
    window._stop.set()

    runtime = {str(cid): window.controls[cid].label for cid in window.controls}
    visible = {str(cid): window.controls[cid].visible for cid in window.controls}

    body = []
    for control in ET.parse(SKIN_XML).getroot().find("controls").findall("control"):
        kind = control.get("type")
        control_id = control.get("id")
        if control_id in visible and not visible[control_id]:
            continue

        if kind == "image":
            x, y, width, height = geometry(control)
            texture = control.find("texture")
            path = resolve_texture(texture.text if texture is not None else None)
            diffuse = texture.get("colordiffuse") if texture is not None else None
            body.append(image_element(x, y, width, height, path, diffuse))
        elif kind == "label":
            x, y, width, height = geometry(control)
            raw = child_text(control, "label")
            label = runtime.get(control_id) or (
                STRINGS.get(int(raw), raw) if raw.isdigit() else raw)
            align = child_text(control, "align")
            anchor = "middle" if align == "center" else ("end" if align == "right" else "start")
            body.append(text_element(x, y, width, height, label,
                                     child_text(control, "font"),
                                     child_text(control, "textcolor"), anchor))
        elif kind == "button":
            raw = child_text(control, "label")
            label = runtime.get(control_id) or (
                STRINGS.get(int(raw), raw) if raw.isdigit() else raw)
            body.extend(render_button(control, label, control_id == "200"))

    for row in window._rows:
        body.extend(render_stub_controls(row["controls_list"]))
    body.extend(render_stub_controls(window._static))
    body.extend(render_stub_controls(window._blips))

    defs = "".join(entry[1] for entry in _filters.values())
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" '
           'width="1920" height="1080"><defs>%s</defs>%s</svg>'
           % (defs, "".join(part for part in body if part)))
    return svg, window, tracker


def write(path, svg):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)


def main():
    offline = "--offline" in sys.argv
    wanted = "all"
    if "--view" in sys.argv:
        wanted = sys.argv[sys.argv.index("--view") + 1]
    views = list(VIEW_NAMES) if wanted == "all" else [wanted]

    out_dir = os.path.join(os.path.dirname(HERE), "dist")
    logos = LogoStore(os.path.join(out_dir, "logocache"))
    tracker = None
    pages = []

    for name in views:
        svg, window, tracker = build(VIEW_NAMES[name], offline, tracker, logos)
        path = os.path.join(out_dir, "preview-%s.svg" % name)
        write(path, svg)
        pages.append((name, svg))
        print("\n[%s]  %s" % (name.upper(), path))
        print("  %s | %s" % (window.controls[gui.TITLE_ID].label,
                             window.controls[gui.STATUS_ID].label))
        for row in window._rows:
            print("  %-13s %-34s %s" % (row["texts"].get("slot", ""),
                                        row["texts"].get("route", ""),
                                        row["texts"].get("status", "")))
            print("  %-13s %s" % ("", row["texts"].get("flight", "")))
        if not window._rows:
            print("  (nothing on approach or departure right now)")

    html = os.path.join(out_dir, "preview.html")
    with open(html, "w", encoding="utf-8") as handle:
        handle.write("<!doctype html><meta charset='utf-8'>"
                     "<title>Flight Tracker preview</title>"
                     "<style>html,body{margin:0;background:#000}"
                     "svg{display:block;width:100vw;height:auto;margin-bottom:8px}"
                     "</style>" + "".join(svg for _, svg in pages))
    print("\nwrote %s" % html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
