"""Optional background watcher.

Off by default. When enabled it pops a Kodi notification as a low aircraft
passes close to you, so you get the route of the plane you just heard go over
without leaving whatever you were watching.
"""

import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

if ADDON_PATH not in sys.path:
    sys.path.insert(0, ADDON_PATH)

from resources.lib import config  # noqa: E402
from resources.lib import geo  # noqa: E402
from resources.lib.model import Formatter, PHASE_CLIMB, PHASE_DESCEND  # noqa: E402
from resources.lib.tracker import Tracker  # noqa: E402

HOME_WINDOW = 10000
OPEN_FLAG = "flighttracker.window.open"

IDLE_INTERVAL = 60


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[flighttracker.service] %s" % message, level)


def cache_path():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    return os.path.join(PROFILE_PATH, "routes.json")


def window_is_open():
    return xbmcgui.Window(HOME_WINDOW).getProperty(OPEN_FLAG) == "1"


def describe(flight, fmt):
    heading = flight.display_number
    if flight.route:
        origin = flight.route.origin_city or flight.route.origin_iata
        dest = flight.route.dest_city or flight.route.dest_iata
        if origin and dest:
            heading = "%s   %s > %s" % (heading, origin, dest)

    bits = ["%s %s" % (fmt.distance(flight.distance_nm),
                       geo.compass_point(flight.bearing_deg))]
    bits.append(fmt.altitude(flight.alt_ft, flight.on_ground))
    if flight.phase == PHASE_CLIMB:
        bits.append("climbing")
    elif flight.phase == PHASE_DESCEND:
        bits.append("descending")
    if flight.elevation_deg is not None and flight.elevation_deg > 0:
        bits.append("%d deg up" % int(round(flight.elevation_deg)))
    return heading, "   ".join(bits)


def pick(cfg, flights, alerted, now):
    """Closest qualifying aircraft that has not been announced recently."""
    best = None
    for flight in flights:
        if flight.distance_nm is None or flight.distance_nm > cfg.notify_dist_nm:
            continue
        if flight.alt_ft is None or flight.alt_ft > cfg.notify_alt_ft:
            continue
        if flight.on_ground:
            continue
        if cfg.only_visible and not flight.in_view:
            continue
        key = flight.hex or flight.callsign
        if not key:
            continue
        if now - alerted.get(key, 0) < cfg.notify_cooldown_sec:
            continue
        if best is None or flight.distance_nm < best.distance_nm:
            best = flight
    return best


def run():
    monitor = xbmc.Monitor()
    tracker = None
    alerted = {}
    icon = os.path.join(ADDON_PATH, "resources", "media", "icon.png")

    while not monitor.abortRequested():
        interval = IDLE_INTERVAL
        try:
            cfg = config.from_addon(xbmcaddon.Addon())
        except Exception as exc:
            log("could not read settings: %s" % exc, xbmc.LOGWARNING)
            cfg = None

        if cfg and cfg.notify_enabled and cfg.location_is_set() and not window_is_open():
            if tracker is None:
                tracker = Tracker(cfg, cache_path(), logger=log)
            else:
                tracker.update_config(cfg)
            try:
                result = tracker.poll()
                now = time.time()
                if not result.error:
                    flight = pick(cfg, result.flights, alerted, now)
                    if flight is not None:
                        alerted[flight.hex or flight.callsign] = now
                        heading, message = describe(flight, Formatter(cfg.units))
                        xbmcgui.Dialog().notification(heading, message, icon, 6000)
                    # keep the cooldown table from growing without bound
                    for key in [k for k, t in alerted.items()
                                if now - t > max(cfg.notify_cooldown_sec * 4, 900)]:
                        alerted.pop(key, None)
            except Exception as exc:
                log("poll failed: %s" % exc, xbmc.LOGWARNING)
            interval = max(15, int(cfg.refresh_sec) * 2)

        if monitor.waitForAbort(interval):
            break

    if tracker is not None:
        tracker.close()


if __name__ == "__main__":
    run()
