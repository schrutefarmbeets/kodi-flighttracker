"""Flight Tracker entry point.

    RunScript(script.flighttracker)                 opens the window
    RunScript(script.flighttracker,detectlocation)  fills in an approximate position
"""

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

if ADDON_PATH not in sys.path:
    sys.path.insert(0, ADDON_PATH)

from resources.lib import config  # noqa: E402
from resources.lib import gui  # noqa: E402
from resources.lib.logos import LogoStore  # noqa: E402
from resources.lib.tracker import Tracker  # noqa: E402

HOME_WINDOW = 10000
OPEN_FLAG = "flighttracker.window.open"


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[flighttracker] %s" % message, level)


def media_dir():
    return os.path.join(ADDON_PATH, "resources", "media")


def cache_path():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    return os.path.join(PROFILE_PATH, "routes.json")


def logo_dir():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    return os.path.join(PROFILE_PATH, "logos")


def reload_config():
    return config.from_addon(xbmcaddon.Addon())


def open_window():
    cfg = reload_config()

    if not cfg.location_is_set():
        xbmcgui.Dialog().ok(
            ADDON.getLocalizedString(30100),
            ADDON.getLocalizedString(30108))
        ADDON.openSettings()
        cfg = reload_config()
        if not cfg.location_is_set():
            return

    home = xbmcgui.Window(HOME_WINDOW)
    home.setProperty(OPEN_FLAG, "1")

    tracker = Tracker(cfg, cache_path(), logger=log)
    logos = LogoStore(logo_dir(), logger=log)
    window = gui.FlightWindow(gui.XML_NAME, ADDON_PATH, "Default", "1080i")
    try:
        window.prepare(ADDON, cfg, tracker, media_dir(), reload_config, logo_store=logos)
        window.doModal()
    finally:
        home.clearProperty(OPEN_FLAG)
        tracker.close()
        del window


# ---------------------------------------------------------------- location helper
GEO_SERVICES = (
    ("https://ipwho.is/", ("latitude", "longitude"), ("city",)),
    ("https://ipapi.co/json/", ("latitude", "longitude"), ("city",)),
)


def detect_location():
    from urllib.request import Request, urlopen

    dialog = xbmcgui.Dialog()
    progress = xbmcgui.DialogProgressBG()
    progress.create(ADDON.getLocalizedString(30100),
                    ADDON.getLocalizedString(30112))

    found = None
    try:
        for url, coord_keys, city_keys in GEO_SERVICES:
            try:
                request = Request(url, headers={"User-Agent": "Kodi-FlightTracker/1.0"})
                response = urlopen(request, timeout=10)
                try:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
                finally:
                    response.close()
            except Exception as exc:
                log("geolocation via %s failed: %s" % (url, exc), xbmc.LOGWARNING)
                continue

            lat = payload.get(coord_keys[0])
            lon = payload.get(coord_keys[1])
            if lat is None or lon is None:
                continue
            city = ""
            for key in city_keys:
                if payload.get(key):
                    city = payload[key]
                    break
            found = (float(lat), float(lon), city)
            break
    finally:
        progress.close()

    if not found:
        dialog.notification(ADDON.getLocalizedString(30100),
                            ADDON.getLocalizedString(30111),
                            xbmcgui.NOTIFICATION_WARNING, 4000)
        return

    lat, lon, city = found
    ADDON.setSetting("home_lat", "%.4f" % lat)
    ADDON.setSetting("home_lon", "%.4f" % lon)
    dialog.notification(
        ADDON.getLocalizedString(30110),
        "%.4f, %.4f%s" % (lat, lon, " (%s)" % city if city else ""),
        xbmcgui.NOTIFICATION_INFO, 5000)


def main():
    argument = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if argument == "detectlocation":
        detect_location()
    else:
        open_window()


if __name__ == "__main__":
    main()
