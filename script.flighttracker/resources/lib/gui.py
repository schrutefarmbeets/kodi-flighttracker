"""The Flight Tracker board.

Shows what is happening right now rather than a list to scan: the aircraft
currently on final approach, the one currently climbing out, and optionally one
passing over. Styled as a Solari split-flap board, which is also the house
style for the radar and map panels.

Row controls are created once and then updated in place, so a changing row can
flap over character by character instead of being torn down and rebuilt.
"""

import math
import os
import random
import threading
import time

import xbmc
import xbmcgui

from . import config, feeds, geo
from .model import (KIND_ARRIVAL, KIND_DEPARTURE, SLOT_HEADINGS, Formatter,
                    board_status)

XML_NAME = "script-flighttracker-main.xml"

TITLE_ID = 103
STATUS_ID = 104
RADAR_ID = 110
LEGEND_ID = 111
RANGE_ID = 112
MESSAGE_ID = 150
BTN_REFRESH = 200
BTN_VIEW = 201
BTN_SETTINGS = 202

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92

# Solari palette.
AMBER = "0xFFFFB000"
AMBER_BRIGHT = "0xFFFFD37A"
AMBER_DIM = "0xFFB07800"
AMBER_FAINT = "0xFF7A5400"
PLATE_INK = "0xFF2A2620"
WHITE = "0xFFFFFFFF"

BOARD_KIND_COLOURS = {
    KIND_ARRIVAL: "FFFFD37A",
    KIND_DEPARTURE: "FFFFB000",
}
BOARD_KIND_DEFAULT = "FF8A6000"

# Radar panel geometry, matching the image placed by the window XML.
RADAR_CX = 460
RADAR_CY = 540
RADAR_R = 386
BLIP = 36
RADAR_STEPS = (5, 10, 15, 20, 30, 40, 60, 80, 100, 150, 200, 250)
RANGE_HEADROOM = 1.08

ROW_GAP = 18

# Split-flap animation. Spaces are held still so the word keeps its shape while
# the letters settle from the left.
FLAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FLAP_STEPS = 9
FLAP_DURATION = 0.45

# Rough average glyph width as a fraction of font size, for fitting text.
GLYPH_RATIO = 0.56

FONT_PX = {"font10": 23, "font12": 25, "font13": 30, "font14": 33,
           "font27": 27, "font32": 32, "font37": 37, "font45": 45, "font60": 60}


def _hex(colour):
    return colour if colour.startswith("0x") else "0x" + colour


def board_region(view_mode):
    """Where the board sits, given whether a panel shares the screen."""
    if view_mode == config.VIEW_BOARD:
        return (60, 150, 1800, 840)
    return (896, 150, 964, 840)


def row_boxes(region, count):
    x, y, width, height = region
    if count <= 0:
        return []
    row_height = int((height - ROW_GAP * (count - 1)) / count)
    return [(x, y + index * (row_height + ROW_GAP), width, row_height)
            for index in range(count)]


def row_fonts(height, wide):
    big = wide and height >= 330
    return {
        "route": "font60" if big else "font45",
        "status": "font45" if big else "font32",
        "flight": "font32" if big else "font27",
        "slot": "font27" if big else "font12",
    }


class FlightWindow(xbmcgui.WindowXML):
    """Built with prepare() so WindowXML's own constructor is left alone."""

    def prepare(self, addon, cfg, tracker, media_dir, reload_config, logo_store=None):
        self.addon = addon
        self.cfg = cfg
        self.tracker = tracker
        self.media = media_dir
        self.reload_config = reload_config
        self.logos = logo_store
        self.fmt = Formatter(cfg.units)
        self._monitor = xbmc.Monitor()
        self._stop = threading.Event()
        self._thread = None
        self._rows = []
        self._row_signature = None
        self._blips = []
        self._static = []
        self._reserved = []
        self._render_lock = threading.Lock()
        self._flap_generation = {}
        self._radar_range = float(cfg.radius_nm)

    # ---------------------------------------------------------------- lifecycle
    def onInit(self):
        self._sync_panel_visibility()
        self._sync_buttons()
        self._draw_panel()
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="flighttracker-poll")
            self._thread.daemon = True
            self._thread.start()

    def close(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(2.0)
        self._thread = None
        self._teardown_rows()
        self._drop(self._blips)
        self._drop(self._static)
        super(FlightWindow, self).close()

    def _drop(self, bucket):
        if bucket:
            try:
                self.removeControls(bucket)
            except Exception:
                pass
            del bucket[:]

    # ---------------------------------------------------------------- input
    def onAction(self, action):
        if action.getId() in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.close()

    def onClick(self, control_id):
        if control_id == BTN_REFRESH:
            self._kick()
        elif control_id == BTN_VIEW:
            self._cycle_view()
        elif control_id == BTN_SETTINGS:
            self._open_settings()

    def _kick(self):
        thread = threading.Thread(target=self._poll_once, name="flighttracker-kick")
        thread.daemon = True
        thread.start()

    def _poll_once(self):
        try:
            self._render(self.tracker.poll())
        except Exception as exc:
            xbmc.log("[flighttracker] manual refresh failed: %s" % exc, xbmc.LOGWARNING)

    def _cycle_view(self):
        self.cfg.view_mode = (self.cfg.view_mode + 1) % 3
        try:
            self.addon.setSettingInt("view_mode", self.cfg.view_mode)
        except Exception:
            pass
        self._apply_view_change()

    def _apply_view_change(self):
        self._sync_panel_visibility()
        self._sync_buttons()
        self._teardown_rows()
        self._draw_panel()
        self._kick()

    def _open_settings(self):
        self.addon.openSettings()
        try:
            self.cfg = self.reload_config()
        except Exception as exc:
            xbmc.log("[flighttracker] could not reload settings: %s" % exc, xbmc.LOGWARNING)
            return
        self.fmt = Formatter(self.cfg.units)
        self.tracker.update_config(self.cfg)
        self._radar_range = float(self.cfg.radius_nm)
        self._apply_view_change()

    # ---------------------------------------------------------------- polling
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._render(self.tracker.poll())
            except Exception as exc:
                xbmc.log("[flighttracker] poll failed: %s" % exc, xbmc.LOGERROR)
            if self._stop.wait(max(3, int(self.cfg.refresh_sec))):
                break
            if self._monitor.abortRequested():
                break

    # ---------------------------------------------------------------- rendering
    def _render(self, result):
        with self._render_lock:
            if self._stop.is_set():
                return
            selection = self.tracker.select_now(result.flights)
            self._render_header(result, selection)
            self._render_board(selection)
            if self.cfg.view_mode != config.VIEW_BOARD:
                on_board = set(f.hex for _, f in selection if f.hex)
                self._render_panel(result.flights, on_board)

    def _render_header(self, result, selection):
        cfg = self.cfg
        headings = []
        if cfg.show_arrivals:
            headings.append("ARRIVALS")
        if cfg.show_departures:
            headings.append("DEPARTURES")
        if cfg.show_overflights:
            headings.append("OVERFLIGHTS")
        self._set_label(TITLE_ID, " & ".join(headings) or "LIVE TRAFFIC")

        # The airport the board is for, by name. "Bangkok" would be ambiguous
        # and is not what a board at Suvarnabhumi would say.
        entry = self.tracker.store.airports.get(cfg.airport_primary)
        airport = (entry or {}).get("name") or cfg.airport_primary
        parts = []
        if airport:
            parts.append(airport.upper())
        if result.error:
            parts.append("FEED DOWN")
        else:
            parts.append("%d IN RANGE" % len(result.flights))
        parts.append(time.strftime("%H:%M:%S", time.localtime(result.timestamp)))
        self._set_label(STATUS_ID, "   ".join(parts))

        if result.error:
            self._set_label(MESSAGE_ID, "Cannot reach %s: %s"
                            % (feeds.source_name(cfg.source), result.error))
            self._set_visible(MESSAGE_ID, True)
        elif not selection:
            self._set_label(MESSAGE_ID, "Nothing on approach or departure right now")
            self._set_visible(MESSAGE_ID, True)
        else:
            self._set_visible(MESSAGE_ID, False)

    # ---------------------------------------------------------------- board
    def _render_board(self, selection):
        self._ensure_rows(len(selection))
        for index, (slot, flight) in enumerate(selection):
            if index < len(self._rows):
                self._update_row(self._rows[index], slot, flight)

    def _teardown_rows(self):
        for row in self._rows:
            self._drop(row["controls_list"])
        self._rows = []
        self._row_signature = None
        self._flap_generation = {}

    def _ensure_rows(self, count):
        signature = (self.cfg.view_mode, count, bool(self.cfg.show_logos))
        if signature == self._row_signature:
            return
        self._teardown_rows()
        if count <= 0:
            self._row_signature = signature
            return

        region = board_region(self.cfg.view_mode)
        wide = self.cfg.view_mode == config.VIEW_BOARD
        for box in row_boxes(region, count):
            self._rows.append(self._build_row(box, wide))
        self._row_signature = signature

    def _build_row(self, box, wide):
        x, y, width, height = box
        fonts = row_fonts(height, wide)
        controls = {}
        ordered = []

        panel = xbmcgui.ControlImage(x, y, width, height,
                                     os.path.join(self.media, "flap_panel.png"))
        ordered.append(panel)

        show_logo = bool(self.cfg.show_logos)
        text_x = x + 28
        if show_logo:
            plate_h = max(70, min(int(height * 0.46), 190))
            plate_w = int(plate_h * 320.0 / 170.0)
            plate_x = x + max(20, int(height * 0.09))
            plate_y = y + (height - plate_h) // 2

            plate = xbmcgui.ControlImage(plate_x, plate_y, plate_w, plate_h,
                                         os.path.join(self.media, "plate.png"))
            inset = int(plate_h * 0.14)
            logo = xbmcgui.ControlImage(plate_x + inset, plate_y + inset,
                                        plate_w - inset * 2, plate_h - inset * 2,
                                        os.path.join(self.media, "white.png"),
                                        aspectRatio=2)
            badge = xbmcgui.ControlLabel(plate_x, plate_y + plate_h // 2 - 26,
                                         plate_w, 52, "", font=fonts["status"],
                                         textColor=PLATE_INK, alignment=6)
            controls["plate"] = plate
            controls["logo"] = logo
            controls["badge"] = badge
            ordered.extend([plate, logo, badge])
            text_x = plate_x + plate_w + 34

        text_w = max(200, x + width - text_x - 28)
        status_w = int(text_w * 0.42)
        slot_w = text_w - status_w - 20

        # Stack the three lines from their actual font heights and centre the
        # block, rather than pinning them to fractions of the row. Fractions
        # leave the text top-heavy in a tall row and cramped in a short one.
        slot_px = FONT_PX.get(fonts["slot"], 27)
        status_px = FONT_PX.get(fonts["status"], 45)
        route_px = FONT_PX.get(fonts["route"], 45)
        flight_px = FONT_PX.get(fonts["flight"], 32)

        lead = max(14, int(height * 0.06))
        block = slot_px + lead + route_px + lead + flight_px
        slot_y = y + max(10, (height - block) // 2)
        route_y = slot_y + slot_px + lead
        flight_y = route_y + route_px + lead
        # Kodi draws labels from the top, so match baselines by hand.
        status_y = slot_y + int(0.8 * (slot_px - status_px))

        slot = xbmcgui.ControlLabel(text_x, slot_y, slot_w, slot_px + 10, "",
                                    font=fonts["slot"], textColor=AMBER_FAINT)
        status = xbmcgui.ControlLabel(text_x + slot_w + 20, status_y, status_w,
                                      status_px + 10, "", font=fonts["status"],
                                      textColor=AMBER_BRIGHT, alignment=1)
        route = xbmcgui.ControlLabel(text_x, route_y, text_w, route_px + 12, "",
                                     font=fonts["route"], textColor=AMBER)
        flight = xbmcgui.ControlLabel(text_x, flight_y, text_w, flight_px + 10, "",
                                      font=fonts["flight"], textColor=AMBER_DIM)

        controls.update({"slot": slot, "status": status, "route": route, "flight": flight})
        ordered.extend([slot, status, route, flight])

        try:
            self.addControls(ordered)
        except Exception as exc:
            xbmc.log("[flighttracker] could not build board row: %s" % exc, xbmc.LOGWARNING)

        return {
            "controls": controls,
            "controls_list": ordered,
            "texts": {},
            "route_chars": int(text_w / (FONT_PX.get(fonts["route"], 45) * GLYPH_RATIO)),
            "flight_chars": int(text_w / (FONT_PX.get(fonts["flight"], 32) * GLYPH_RATIO)),
        }

    def _update_row(self, row, slot, flight):
        values = {
            "slot": SLOT_HEADINGS.get(slot, ""),
            "status": board_status(flight),
            "route": self._route_text(flight, row["route_chars"]),
            "flight": self._flight_text(flight, row["flight_chars"]),
        }
        for key, value in values.items():
            control = row["controls"].get(key)
            if control is None or row["texts"].get(key) == value:
                continue
            first = key not in row["texts"]
            row["texts"][key] = value
            if first or not self.cfg.flap_animation:
                self._set_text(control, value)
            else:
                self._flap(control, value)
        self._update_logo(row, flight)

    @staticmethod
    def _city(name):
        """Trim a municipality down to something a board would print.

        The route database gives district-level names for some airports, such
        as "Kowloon City, Kowloon" for Hong Kong. Only the part before the
        comma is worth the width.
        """
        return (name or "").split(",")[0].strip()

    def _place_name(self, icao, city, iata):
        """What to call this end of the route.

        The shipped airport table wins where it has an entry, because the route
        database names some places in ways nobody says out loud: Koh Samui
        comes back as "Na Thon (Ko Samui Island)" and Hong Kong as "Kowloon
        City, Kowloon".
        """
        if icao:
            known = self.tracker.store.airports.label(icao)
            if known and known.upper() != icao.upper():
                return self._city(known)
        return self._city(city) or iata or icao or "?"

    def _route_text(self, flight, limit):
        route = flight.route
        if not route:
            return "ROUTE UNKNOWN"

        # A multi-sector flight number landing here: we know where it goes next
        # but not where it has come from, so say only what is true.
        if flight.route_conflict == "onward":
            onward = self._place_name(route.dest_icao, route.dest_city,
                                      route.dest_iata).upper()
            text = "CONTINUES TO %s" % onward
            return text if len(text) <= limit else onward

        origin = self._place_name(route.origin_icao, route.origin_city,
                                  route.origin_iata).upper()
        dest = self._place_name(route.dest_icao, route.dest_city,
                                route.dest_iata).upper()
        full = "%s  >  %s" % (origin, dest)
        if len(full) <= limit:
            return full
        # Fall back to the codes rather than truncating a city name to nonsense.
        codes = "%s  >  %s" % ((route.origin_iata or route.origin_icao or "?").upper(),
                               (route.dest_iata or route.dest_icao or "?").upper())
        return codes if len(codes) <= limit else full[:limit]

    def _flight_text(self, flight, limit):
        bits = [flight.display_callsign]
        info = flight.aircraft_info or {}
        kind = flight.type_desc or info.get("type") or flight.type_code
        if kind:
            bits.append(kind)
        if flight.registration:
            bits.append(flight.registration)
        text = "   ".join(bits).upper()
        if len(text) > limit and len(bits) > 2:
            text = "   ".join(bits[:2]).upper()
        return text[:limit] if len(text) > limit else text

    def _update_logo(self, row, flight):
        if not self.cfg.show_logos or "logo" not in row["controls"]:
            return
        iata = ""
        if flight.route and flight.route.airline_iata:
            iata = flight.route.airline_iata

        path = None
        if iata and self.logos is not None:
            try:
                path = self.logos.get(iata)
            except Exception:
                path = None

        logo = row["controls"]["logo"]
        badge = row["controls"]["badge"]
        if path:
            if row["texts"].get("logo") != path:
                row["texts"]["logo"] = path
                logo.setImage(path)
            logo.setVisible(True)
            badge.setVisible(False)
        else:
            logo.setVisible(False)
            fallback = iata or (flight.callsign or "")[:3]
            if row["texts"].get("badge") != fallback:
                row["texts"]["badge"] = fallback
                badge.setLabel(fallback)
            badge.setVisible(bool(fallback))

    # ---------------------------------------------------------------- flap
    def _set_text(self, control, value):
        try:
            control.setLabel(value)
        except Exception:
            pass

    def _flap(self, control, target):
        key = id(control)
        self._flap_generation[key] = self._flap_generation.get(key, 0) + 1
        generation = self._flap_generation[key]
        thread = threading.Thread(target=self._flap_run,
                                  args=(control, target, key, generation),
                                  name="flighttracker-flap")
        thread.daemon = True
        thread.start()

    def _flap_run(self, control, target, key, generation):
        text = target.upper()
        length = len(text)
        try:
            for step in range(FLAP_STEPS):
                if self._stop.is_set() or self._flap_generation.get(key) != generation:
                    return
                settled = int(round(length * (step + 1) / float(FLAP_STEPS)))
                tail = "".join(" " if char == " " else random.choice(FLAP_CHARS)
                               for char in text[settled:])
                control.setLabel(text[:settled] + tail)
                time.sleep(FLAP_DURATION / FLAP_STEPS)
            if self._flap_generation.get(key) == generation:
                control.setLabel(text)
        except Exception:
            pass

    # ---------------------------------------------------------------- panels
    def _sync_panel_visibility(self):
        split = self.cfg.view_mode != config.VIEW_BOARD
        # The range rings belong to the radar. Leaving them under the map makes
        # the map look like the radar with extra lines on it.
        self._set_visible(RADAR_ID, self.cfg.view_mode == config.VIEW_RADAR)
        for control_id in (LEGEND_ID, RANGE_ID):
            self._set_visible(control_id, split)

    def _sync_buttons(self):
        names = {config.VIEW_BOARD: "BOARD",
                 config.VIEW_RADAR: "RADAR",
                 config.VIEW_MAP: "MAP"}
        self._set_button(BTN_REFRESH, "REFRESH")
        self._set_button(BTN_VIEW, "VIEW: %s" % names.get(self.cfg.view_mode, "BOARD"))
        self._set_button(BTN_SETTINGS, "SETTINGS")

    def _draw_panel(self):
        self._drop(self._static)
        if self.cfg.view_mode == config.VIEW_BOARD:
            return
        if self.cfg.view_mode == config.VIEW_MAP:
            self._draw_map_furniture()
        else:
            self._draw_radar_furniture()
        self._set_legend()

    def _render_panel(self, flights, on_board=None):
        wanted = self._choose_range(flights)
        if abs(wanted - self._radar_range) > 0.01:
            self._radar_range = wanted
            self._draw_panel()
        self._draw_blips(flights, on_board or set())

    def _choose_range(self, flights):
        cap = float(self.cfg.radius_nm)
        if not flights:
            return cap
        furthest = max(f.distance_nm for f in flights) * RANGE_HEADROOM
        for step in RADAR_STEPS:
            if step >= furthest:
                return min(float(step), cap)
        return cap

    def _rotation(self):
        return float(self.cfg.view_bearing) if self.cfg.orient_radar else 0.0

    def _offset_for_bearing(self, bearing, radius):
        angle = math.radians(bearing - self._rotation())
        return radius * math.sin(angle), -radius * math.cos(angle)

    def _project(self, lat, lon):
        return geo.project_to_radar(lat, lon, self.cfg.home_lat, self.cfg.home_lon,
                                    self._radar_range, RADAR_R, self._rotation())

    def _draw_radar_furniture(self):
        controls = [xbmcgui.ControlImage(
            RADAR_CX - 16, RADAR_CY - 16, 32, 32,
            os.path.join(self.media, "home.png"), colorDiffuse=AMBER_BRIGHT)]

        for bearing, letter in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            dx, dy = self._offset_for_bearing(bearing, RADAR_R * 0.94)
            controls.append(xbmcgui.ControlLabel(
                int(RADAR_CX + dx) - 30, int(RADAR_CY + dy) - 18, 60, 36, letter,
                font="font27", textColor=AMBER_DIM, alignment=6))

        for fraction in (0.25, 0.5, 0.75, 1.0):
            radius = RADAR_R * fraction
            controls.append(xbmcgui.ControlLabel(
                RADAR_CX + 8, int(RADAR_CY - radius) - 4, 150, 28,
                self.fmt.distance(self._radar_range * fraction),
                font="font10", textColor=AMBER_FAINT))

        controls.extend(self._view_cone_controls())
        controls.extend(self._airport_markers())
        self._add_static(controls)

    def _draw_map_furniture(self):
        from . import mapdata
        controls = []
        white = os.path.join(self.media, "white.png")

        # Cool grey for geography so it reads as land and water rather than as
        # more traffic, leaving amber to mean aircraft.
        for polyline in mapdata.coastline():
            controls.extend(self._draw_polyline(polyline, white, "0xAA5A6E7E", 4))
        for polyline in mapdata.runways(self.cfg.my_airports):
            controls.extend(self._draw_polyline(polyline, white, AMBER_BRIGHT, 6))

        controls.append(xbmcgui.ControlImage(
            RADAR_CX - 16, RADAR_CY - 16, 32, 32,
            os.path.join(self.media, "home.png"), colorDiffuse=AMBER_BRIGHT))
        controls.extend(self._view_cone_controls())
        controls.extend(self._airport_markers())
        self._add_static(controls)

    def _draw_polyline(self, points, texture, colour, thickness):
        """Plots a lat/lon path as a run of small squares.

        Kodi has no line primitive, and a handful of squares per segment is far
        cheaper than shipping a pre-rendered map for every possible location.
        """
        controls = []
        previous = None
        for lat, lon in points:
            current = self._project(lat, lon)
            if previous is not None and current is not None:
                controls.extend(self._dotted_segment(previous, current, texture,
                                                     colour, thickness))
            previous = current
        return controls

    def _dotted_segment(self, start, end, texture, colour, thickness):
        controls = []
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1:
            return controls
        steps = max(1, int(length / max(2, thickness - 1)))
        for index in range(steps + 1):
            t = index / float(steps)
            x = int(RADAR_CX + start[0] + dx * t) - thickness // 2
            y = int(RADAR_CY + start[1] + dy * t) - thickness // 2
            controls.append(xbmcgui.ControlImage(x, y, thickness, thickness,
                                                 texture, colorDiffuse=colour))
        return controls

    def _airport_markers(self):
        controls = []
        # Remembered so aircraft callsigns do not land on top of them.
        self._reserved = []
        for icao in self.cfg.my_airports:
            position = self.tracker.store.airports.position(icao)
            if not position:
                continue
            projected = self._project(position[0], position[1])
            if not projected:
                continue
            dx, dy = projected
            controls.append(xbmcgui.ControlImage(
                int(RADAR_CX + dx) - 10, int(RADAR_CY + dy) - 10, 20, 20,
                os.path.join(self.media, "airport.png"), colorDiffuse=AMBER_BRIGHT))
            # The airport name, not the city: Suvarnabhumi and Don Mueang are
            # both "Bangkok", which is no use as a map label.
            entry = self.tracker.store.airports.get(icao)
            name = ((entry or {}).get("name") or icao).upper()
            label_x = int(RADAR_CX + dx) + 14
            label_y = int(RADAR_CY + dy) - 14
            controls.append(xbmcgui.ControlLabel(
                label_x, label_y, 200, 28, name, font="font12", textColor=AMBER_DIM))
            self._reserved.append((label_x, label_y, 14 + 12 * len(name)))
        return controls

    def _view_cone_controls(self):
        controls = []
        if self.cfg.view_fov >= 360:
            return controls
        texture = os.path.join(self.media, "white.png")
        half = self.cfg.view_fov / 2.0
        for edge in (self.cfg.view_bearing - half, self.cfg.view_bearing + half):
            for step in range(4, 21):
                dx, dy = self._offset_for_bearing(edge, RADAR_R * (step / 20.0))
                controls.append(xbmcgui.ControlImage(
                    int(RADAR_CX + dx) - 2, int(RADAR_CY + dy) - 2, 4, 4,
                    texture, colorDiffuse="0x55FFB000"))
        return controls

    def _add_static(self, controls):
        try:
            self.addControls(controls)
            self._static = controls
        except Exception as exc:
            xbmc.log("[flighttracker] could not draw panel: %s" % exc, xbmc.LOGWARNING)

    def _draw_blips(self, flights, on_board=frozenset()):
        """Plot the traffic, picking out whatever is on the board.

        Labelling every aircraft turns into unreadable mush the moment a few
        bunch up on approach, and it is not the question being asked anyway.
        Only the aircraft on the board get a callsign and full brightness; the
        rest are dim context, so the eye goes straight to the one that is
        landing.
        """
        self._drop(self._blips)
        rotation = self._rotation()
        controls = []
        labels = []
        for flight in flights:
            projected = self._project(flight.lat, flight.lon)
            if not projected:
                continue
            dx, dy = projected
            x = int(RADAR_CX + dx)
            y = int(RADAR_CY + dy)
            featured = bool(flight.hex) and flight.hex in on_board

            colour = BOARD_KIND_COLOURS.get(flight.kind, BOARD_KIND_DEFAULT)
            if featured:
                colour = "FF" + colour[2:]
            elif flight.in_view:
                colour = "99" + colour[2:]
            else:
                colour = "55" + colour[2:]

            if flight.track_deg is None:
                texture = os.path.join(self.media, "dot.png")
                size = 20 if featured else 14
            else:
                bucket = (int(round(((flight.track_deg - rotation) % 360.0) / 15.0)) * 15) % 360
                texture = os.path.join(self.media, "plane_%03d.png" % bucket)
                size = BLIP + 12 if featured else BLIP - 8

            controls.append(xbmcgui.ControlImage(
                x - size // 2, y - size // 2, size, size, texture,
                colorDiffuse=_hex(colour)))

            if featured and self.cfg.radar_labels and flight.callsign:
                # Added last so a label is never hidden under another blip.
                labels.append((x + size // 2 + 6, y - 14, flight.callsign, colour))
        controls.extend(self._place_labels(labels, getattr(self, "_reserved", [])))

        if not controls:
            return
        try:
            self.addControls(controls)
            self._blips = controls
        except Exception as exc:
            xbmc.log("[flighttracker] could not draw aircraft: %s" % exc, xbmc.LOGWARNING)

    @staticmethod
    def _place_labels(requested, reserved=()):
        """Stop board labels landing on top of each other, or on an airport name.

        An arrival on short final and a departure climbing out are often within
        a mile or two of the same runway, which puts their callsigns in the
        same place. Nudge each one clear of whatever is already there.
        """
        placed = list(reserved)
        controls = []
        for x, y, text, colour in requested:
            width = 14 + 12 * len(text)
            for _ in range(6):
                clash = any(not (x + width < px or px + pw < x or
                                 y + 28 < py or py + 28 < y)
                            for px, py, pw in placed)
                if not clash:
                    break
                y += 32
            placed.append((x, y, width))
            controls.append(xbmcgui.ControlLabel(
                x, y, 220, 28, text, font="font12", textColor=_hex(colour)))
        return controls

    # ---------------------------------------------------------------- helpers
    def _set_legend(self):
        if self.cfg.orient_radar:
            self._set_label(LEGEND_ID, "TURNED TO YOUR WINDOW - STRAIGHT AHEAD IS UP")
        else:
            self._set_label(LEGEND_ID, "NORTH UP")
        second = "RANGE %s   -   BRIGHT AIRCRAFT ARE ON THE BOARD" % \
            self.fmt.distance(self._radar_range)
        if self.cfg.only_visible:
            second += "   -   ONLY WHAT YOUR WINDOW CAN SEE"
        self._set_label(RANGE_ID, second)

    def _set_label(self, control_id, text):
        try:
            self.getControl(control_id).setLabel(text)
        except Exception:
            pass

    def _set_button(self, control_id, text):
        try:
            self.getControl(control_id).setLabel(text)
        except Exception:
            pass

    def _set_visible(self, control_id, visible):
        try:
            self.getControl(control_id).setVisible(bool(visible))
        except Exception:
            pass
