"""The Flight Tracker board.

Shows what is happening right now rather than a list to scan: the aircraft
currently on final approach, the one currently climbing out, and optionally one
passing over.

Each one is a card in the manner of an airline app's dark mode: a near-black
panel on black, the route as two big airport codes either side of a hairline,
and colour spent only on the status pill. The pill takes its colour from the
same table as the radar blips, so a card and its aircraft can be matched by eye.

Row controls are created once and then updated in place, so a changing route can
flap over character by character instead of being torn down and rebuilt.
"""

import math
import os
import random
import threading
import time

import xbmc
import xbmcgui

from . import airlines, config, feeds, geo, photos
from .model import (KIND_ARRIVAL, KIND_DEPARTURE, SLOT_ARRIVAL, SLOT_DEPARTURE,
                    SLOT_OVERFLIGHT, Formatter, board_status)

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

# Near-black card on black, the way an airline app does its dark mode: colour is
# spent on the status pill and nowhere else, so the eye lands on the one word
# that says what is happening.
TEXT = "0xFFFFFFFF"
TEXT_SOFT = "0xFFB0B0B5"
TEXT_MUTED = "0xFF9A9AA0"
TEXT_FAINT = "0xFF6A6A72"
CARD = "0xFF18181B"
HAIRLINE = "0xFF4A4A4F"
PLATE_INK = "0xFF2A2620"
WHITE = "0xFFFFFFFF"

# Pill fill and the ink that sits on it, per slot. The same three colours the
# radar already uses for its blips, so a card and its aircraft agree.
PILL_COLOURS = {
    SLOT_ARRIVAL: ("0xFF6FD46F", "0xFF173404"),
    SLOT_DEPARTURE: ("0xFFFFC24B", "0xFF412402"),
    SLOT_OVERFLIGHT: ("0xFF7FB8FF", "0xFF042C53"),
}
PILL_DEFAULT = ("0xFF9A9AA0", "0xFF1A1A1E")

BOARD_KIND_COLOURS = {
    KIND_ARRIVAL: "FF6FD46F",
    KIND_DEPARTURE: "FFFFC24B",
}
BOARD_KIND_DEFAULT = "FF7FB8FF"

CARD_RADIUS = 18
PILL_RADIUS = 11

# The photograph sits in a well a shade lighter than the card, with a margin
# all round. Kodi cannot clip an image to a rounded corner, so the margin is
# what does the work: the well's corners stay visible around a square picture,
# and the whole thing reads as mounted rather than pasted on. The well is drawn
# whether or not there is a photograph, so the card never changes shape.
PHOTO_WELL = "0xFF232327"
PHOTO_RADIUS = 12
PHOTO_INSET = 10

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


SPLIT_GAP = 40
SPLIT_LABEL_H = 46
# Sized around the photograph, which cannot be bigger than the 420x280 the API
# serves, plus the route above it and the numbers below. Shorter than the space
# available on purpose: stretched to fill the screen a card is mostly its own
# empty middle, and air inside a card reads as a mistake where the same air
# around it reads as layout.
SPLIT_CARD_H = 680


def split_boxes():
    """The two columns of the board view: one arrival, one departure."""
    x, y, width, height = 60, 150, 1800, 840
    column = (width - SPLIT_GAP) // 2
    block = SPLIT_LABEL_H + SPLIT_CARD_H
    top = y + max(0, (height - block) // 2)
    return [(x, top, column, block),
            (x + column + SPLIT_GAP, top, column, block)]


def row_boxes(region, count):
    x, y, width, height = region
    if count <= 0:
        return []
    row_height = int((height - ROW_GAP * (count - 1)) / count)
    return [(x, y + index * (row_height + ROW_GAP), width, row_height)
            for index in range(count)]


def row_fonts(height, wide):
    big = wide and height >= 300
    return {
        "code": "font60" if big else "font45",
        "city": "font27" if big else "font10",
        "pill": "font27" if big else "font10",
        "meta": "font27" if big else "font10",
        "label": "font10",
        "value": "font32" if big else "font27",
    }


# Handover. The obvious trigger, altitude reaching zero, never fires: the
# hide_ground and min_alt_ft filters and the approach range all drop an
# aircraft before it touches down, and rooftop coverage of the last few hundred
# feet is patchy anyway. What actually happens is that the aircraft stops being
# in the feed, so that is what a slot watches for, with a grace period so an
# ordinary dropout does not flip the card.
HOLD_GRACE_SEC = 25.0
HOLD_DONE_SEC = 12.0
HOLD_MAX_SEC = 420.0
RETIRE_SEC = 600.0

STATE_LIVE = "live"
STATE_DONE = "done"

SLOT_TITLES = {SLOT_ARRIVAL: "LANDING", SLOT_DEPARTURE: "TAKE OFF"}
DONE_WORDS = {SLOT_ARRIVAL: "LANDED", SLOT_DEPARTURE: "AIRBORNE"}
EMPTY_WORDS = {SLOT_ARRIVAL: "Nothing on approach",
               SLOT_DEPARTURE: "Nothing rolling"}


class SlotHolder(object):
    """One side of the board: holds an aircraft until it is finished.

    Keeping the aircraft rather than re-reading the head of the queue every
    poll is the whole point. It means the card follows one flight all the way
    down, holds a word for a moment when it lands, and only then flaps over to
    the next.
    """

    def __init__(self, slot):
        self.slot = slot
        self.flight = None
        self.state = STATE_LIVE
        self._hex = None
        self._seen = 0.0
        self._latched = 0.0
        self._done_at = 0.0
        self._retired = {}

    def status(self):
        if self.flight is None:
            return ""
        if self.state == STATE_DONE:
            return DONE_WORDS.get(self.slot, "DONE")
        return board_status(self.flight)

    def update(self, queue, now):
        self._prune(now)

        if self._hex is not None:
            current = None
            for flight in queue:
                if flight.hex == self._hex:
                    current = flight
                    break

            if current is not None:
                self.flight = current
                self._seen = now
                if current.on_ground:
                    self._finish(now)
                elif now - self._latched > HOLD_MAX_SEC:
                    # A go-around, or something that turned back. Whatever it
                    # is doing, it is no longer the next movement.
                    self._release(now)
            elif self.state == STATE_LIVE and now - self._seen > HOLD_GRACE_SEC:
                self._finish(now)

        if self.state == STATE_DONE and now - self._done_at >= HOLD_DONE_SEC:
            self._release(now)

        if self._hex is None:
            self._take(queue, now)
            # Something already on the ground as it takes the slot has
            # finished before it started; say so rather than calling it a
            # landing for the next twelve seconds.
            if self.flight is not None and self.flight.on_ground:
                self._finish(now)
        return self.flight

    def _finish(self, now):
        if self.state != STATE_DONE:
            self.state = STATE_DONE
            self._done_at = now

    def _release(self, now):
        if self._hex is not None:
            self._retired[self._hex] = now
        self._hex = None
        self.flight = None
        self.state = STATE_LIVE

    def _take(self, queue, now):
        for flight in queue:
            if flight.hex in self._retired:
                continue
            self._hex = flight.hex
            self.flight = flight
            self.state = STATE_LIVE
            self._seen = now
            self._latched = now
            return
        self.flight = None

    def waiting(self, queue):
        """What is behind the aircraft on screen, for the line under the card."""
        rest = [f for f in queue
                if f.hex != self._hex and f.hex not in self._retired]
        return rest

    def _prune(self, now):
        for key in [k for k, t in self._retired.items() if now - t > RETIRE_SEC]:
            del self._retired[key]


class FlightWindow(xbmcgui.WindowXML):
    """Built with prepare() so WindowXML's own constructor is left alone."""

    def prepare(self, addon, cfg, tracker, media_dir, reload_config, logo_store=None,
                photo_store=None):
        self.addon = addon
        self.cfg = cfg
        self.tracker = tracker
        self.media = media_dir
        self.reload_config = reload_config
        self.logos = logo_store
        self.photos = photo_store
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
        self._holders = {SLOT_ARRIVAL: SlotHolder(SLOT_ARRIVAL),
                         SLOT_DEPARTURE: SlotHolder(SLOT_DEPARTURE)}

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
    def _split_view(self):
        return self.cfg.view_mode == config.VIEW_BOARD

    def _render(self, result):
        with self._render_lock:
            if self._stop.is_set():
                return
            if self._split_view():
                selection = self._render_split(result)
            else:
                selection = self.tracker.select_now(result.flights)
                self._render_board(selection)
            self._render_header(result, selection)
            if not self._split_view():
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

    # ---------------------------------------------------------------- split
    @staticmethod
    def _now():
        """Overridable so the handover can be tested without waiting for it."""
        return time.time()

    def _render_split(self, result):
        """One arrival and one departure, each held until it has finished."""
        queues = self.tracker.select_slots(result.flights)
        now = self._now()
        self._ensure_split_rows()

        selection = []
        for index, slot in enumerate((SLOT_ARRIVAL, SLOT_DEPARTURE)):
            if index >= len(self._rows):
                break
            row = self._rows[index]
            queue = queues.get(slot, [])
            holder = self._holders[slot]
            flight = holder.update(queue, now)
            if flight is None:
                self._blank_row(row, slot)
                continue
            self._update_row(row, slot, flight, status=holder.status())
            self._set_queue_line(row, slot, holder.waiting(queue))
            selection.append((slot, flight))
        return selection

    def _ensure_split_rows(self):
        signature = ("split", bool(self.cfg.show_logos))
        if signature == self._row_signature:
            return
        self._teardown_rows()

        for index, box in enumerate(split_boxes()):
            bx, by, bw, bh = box
            slot = SLOT_ARRIVAL if index == 0 else SLOT_DEPARTURE
            row = self._build_row((bx, by + SPLIT_LABEL_H, bw, bh - SPLIT_LABEL_H),
                                  True)
            # The column heading takes the slot's own colour, so the two sides
            # are told apart before a word of either card is read.
            heading = xbmcgui.ControlLabel(
                bx + 30, by, bw - 60, SPLIT_LABEL_H - 8,
                SLOT_TITLES.get(slot, ""), font="font27",
                textColor=PILL_COLOURS.get(slot, PILL_DEFAULT)[0])
            try:
                self.addControls([heading])
                row["controls_list"].append(heading)
            except Exception as exc:
                xbmc.log("[flighttracker] could not add column heading: %s" % exc,
                         xbmc.LOGWARNING)
            self._rows.append(row)
        self._row_signature = signature

    def _blank_row(self, row, slot):
        """A side with nothing on it. A real board would show blank flaps."""
        values = {"pill": "", "meta": "", "origin_city": "", "dest_city": "",
                  "origin_code": "", "dest_code": "", "places": "",
                  "alt_label": "Altitude",
                  "speed_label": "Speed", "dist_label": "Distance",
                  "alt": "-", "speed": "-", "dist": "-",
                  "queue": EMPTY_WORDS.get(slot, "")}
        for key, value in values.items():
            control = row["controls"].get(key)
            if control is None or row["texts"].get(key) == value:
                continue
            row["texts"][key] = value
            self._set_text(control, value)
        # The pill sinks into the card rather than sitting there as an empty
        # lozenge of colour.
        self._set_pill(row, CARD, CARD)
        for key in ("logo", "badge", "plate", "photo", "credit"):
            self._show(row["controls"].get(key), False)
        for control in row["controls"].get("rule", []):
            self._show(control, False)
        self._show(row["controls"].get("photo_note"), True)

    def _set_queue_line(self, row, slot, waiting):
        control = row["controls"].get("queue")
        if control is None:
            return
        if not waiting:
            text = "Nothing else in the queue"
        else:
            following = waiting[0]
            text = "Next  -  %s%s" % (following.display_number,
                                      self._queue_place(following, slot))
            if len(waiting) > 1:
                text += "   -   %d more" % (len(waiting) - 1)
        if row["texts"].get("queue") != text:
            row["texts"]["queue"] = text
            self._set_text(control, text)

    def _queue_place(self, flight, slot):
        origin_city, origin_code, dest_city, dest_code = self._route_parts(flight)
        if slot == SLOT_ARRIVAL:
            name = origin_city or (origin_code if origin_code != "--" else "")
            return "  from %s" % name if name else ""
        name = dest_city or (dest_code if dest_code != "--" else "")
        return "  to %s" % name if name else ""

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

    def _rounded_rect(self, x, y, width, height, radius, colour):
        """A filled rounded rectangle, which Kodi has no primitive for.

        Stretching one rounded PNG to an arbitrary box turns the corners into
        ellipses, so the shape is assembled instead: four fixed-size corner
        tiles at their native aspect, and three plain fills between them.
        """
        r = max(2, min(int(radius), int(min(width, height) // 2)))
        white = os.path.join(self.media, "white.png")

        def tile(px, py, name):
            return xbmcgui.ControlImage(int(px), int(py), r, r,
                                        os.path.join(self.media, name),
                                        colorDiffuse=colour)

        def fill(px, py, pw, ph):
            return xbmcgui.ControlImage(int(px), int(py), int(pw), int(ph),
                                        white, colorDiffuse=colour)

        return [
            tile(x, y, "corner_tl.png"),
            tile(x + width - r, y, "corner_tr.png"),
            tile(x, y + height - r, "corner_bl.png"),
            tile(x + width - r, y + height - r, "corner_br.png"),
            fill(x + r, y, width - 2 * r, r),
            fill(x + r, y + height - r, width - 2 * r, r),
            fill(x, y + r, width, height - 2 * r),
        ]

    def _build_row(self, box, wide):
        """One card: pill and airline chip on top, route in the middle, numbers below."""
        x, y, width, height = box
        fonts = row_fonts(height, wide)
        controls = {}
        ordered = list(self._rounded_rect(x, y, width, height, CARD_RADIUS, CARD))

        pill_px = FONT_PX.get(fonts["pill"], 27)
        city_px = FONT_PX.get(fonts["city"], 23)
        code_px = FONT_PX.get(fonts["code"], 45)
        meta_px = FONT_PX.get(fonts["meta"], 23)
        label_px = FONT_PX.get(fonts["label"], 23)
        value_px = FONT_PX.get(fonts["value"], 27)

        pad = 30 if wide else 24
        ix = x + pad
        iw = width - pad * 2

        # ------------------------------------------------------------ shape
        # The app stacks its card because it lives on a phone. A board row is
        # short and wide, so the same parts are laid along the width instead,
        # and only a tall card gets the stack. When neither fits, the city
        # names are what goes: the codes carry at a distance and the cities do
        # not.
        head_h = pill_px + 34
        pill_h = pill_px + 16
        pill_w = int(8 * pill_px * GLYPH_RATIO) + 40
        chip_w = int(head_h * 320.0 / 170.0) if self.cfg.show_logos else 0
        head_w = chip_w + (18 if chip_w else 0) + pill_w
        stat_col = max(150, int(value_px * 6.4))
        stats_w = stat_col * 3

        stacked = height >= 340
        spread = (not stacked
                  and iw - head_w - stats_w - 80 >= code_px * 8)
        # A tall card puts the codes on their own as the headline and spells the
        # airports out in fine print lower down. A short one has no room for a
        # second line, so the city goes above the code where it can be read
        # against it.
        show_cities = spread

        if spread:
            centre_y = y + height // 2
            top_y = centre_y - head_h // 2
            meta_y = y + pad
            queue_y = None
            places_y = None
            label_y = centre_y - (label_px + value_px + 2) // 2
            value_y = label_y + label_px + 2
            stats_x = ix + iw - stats_w
            region_left = ix + head_w + 40
            region_right = stats_x - 40
            mid_top = y + pad
            mid_bottom = y + height - pad
        else:
            top_y = y + pad
            meta_y = top_y + (head_h - meta_px) // 2
            value_y = y + height - pad - value_px - 4
            label_y = value_y - label_px + 2
            stats_x, stat_col = ix, iw // 3
            region_left, region_right = ix, ix + iw
            mid_top = top_y + head_h
            # Only a tall card has room to say what is behind this flight, or
            # to spell the two airports out.
            queue_y = label_y - label_px - 16 if stacked else None
            places_y = queue_y - label_px - 10 if stacked else None
            mid_bottom = places_y if stacked else label_y
            if stacked:
                # The route is anchored under the head rather than floated in
                # the middle, because the photograph goes below it.
                mid_top += 18

        # ------------------------------------------------------------ top line
        # The chip is sized to make the airline readable rather than to match
        # the pill; the pill is centred against it.
        pill_y = top_y + (head_h - pill_h) // 2
        pill_x = ix
        if self.cfg.show_logos:
            plate = xbmcgui.ControlImage(ix, top_y, chip_w, head_h,
                                         os.path.join(self.media, "plate.png"))
            inset = max(4, int(head_h * 0.16))
            logo = xbmcgui.ControlImage(ix + inset, top_y + inset,
                                        chip_w - inset * 2, head_h - inset * 2,
                                        os.path.join(self.media, "white.png"),
                                        aspectRatio=2)
            badge = xbmcgui.ControlLabel(ix, top_y + (head_h - pill_px) // 2,
                                         chip_w, pill_px + 8, "", font=fonts["pill"],
                                         textColor=PLATE_INK, alignment=6)
            controls.update({"plate": plate, "logo": logo, "badge": badge})
            ordered.extend([plate, logo, badge])
            pill_x = ix + chip_w + 18

        # The pill is a fixed width, sized for the longest status ("TAKE OFF"),
        # so it never has to be torn down and rebuilt when the word changes.
        pill_bg = self._rounded_rect(pill_x, pill_y, pill_w, pill_h, PILL_RADIUS,
                                     PILL_DEFAULT[0])
        pill_text = xbmcgui.ControlLabel(pill_x, pill_y + (pill_h - pill_px) // 2,
                                         pill_w, pill_px + 8, "", font=fonts["pill"],
                                         textColor=PILL_DEFAULT[1], alignment=6)
        controls["pill_bg"] = pill_bg
        controls["pill"] = pill_text
        ordered.extend(pill_bg)
        ordered.append(pill_text)

        # ------------------------------------------------------------ numbers
        for index, key in enumerate(("alt", "speed", "dist")):
            # The last column is right-aligned so the three of them span their
            # block edge to edge rather than huddling in the left two thirds.
            align = 1 if index == 2 else 0
            cx = stats_x + stat_col * index
            caption = xbmcgui.ControlLabel(cx, label_y, stat_col, label_px + 6, "",
                                           font=fonts["label"], textColor=TEXT_MUTED,
                                           alignment=align)
            value = xbmcgui.ControlLabel(cx, value_y, stat_col, value_px + 8, "",
                                         font=fonts["value"], textColor=TEXT,
                                         alignment=align)
            controls["%s_label" % key] = caption
            controls[key] = value
            ordered.extend([caption, value])

        if queue_y is not None:
            queue = xbmcgui.ControlLabel(ix, queue_y, iw, label_px + 6, "",
                                         font=fonts["label"], textColor=TEXT_FAINT)
            controls["queue"] = queue
            ordered.append(queue)

        # ------------------------------------------------------------ route
        # Bounded and centred in whatever the rest of the card left over. Given
        # the full 1800px the two codes end up half a screen apart, joined by a
        # hairline so long it reads as a rule rather than as a flight.
        room = max(0, region_right - region_left)
        cluster_w = min(room, code_px * 16)
        cluster_x = region_left + (room - cluster_w) // 2
        half = max(1, cluster_w // 2)

        block = ((city_px + 12 if show_cities else 0) + code_px
                 + (meta_px + 10 if spread else 0))
        if stacked:
            city_y = mid_top
        else:
            city_y = mid_top + max(6, (mid_bottom - mid_top - block) // 2)
        code_y = city_y + (city_px + 12 if show_cities else 0)

        if show_cities:
            origin_city = xbmcgui.ControlLabel(cluster_x, city_y, half, city_px + 8,
                                               "", font=fonts["city"],
                                               textColor=TEXT_SOFT)
            dest_city = xbmcgui.ControlLabel(cluster_x + half, city_y, half,
                                             city_px + 8, "", font=fonts["city"],
                                             textColor=TEXT_SOFT, alignment=1)
            controls.update({"origin_city": origin_city, "dest_city": dest_city})
            ordered.extend([origin_city, dest_city])

        origin_code = xbmcgui.ControlLabel(cluster_x, code_y, half, code_px + 12, "",
                                           font=fonts["code"], textColor=TEXT)
        dest_code = xbmcgui.ControlLabel(cluster_x + half, code_y, half, code_px + 12,
                                         "", font=fonts["code"], textColor=TEXT,
                                         alignment=1)
        controls.update({"origin_code": origin_code, "dest_code": dest_code})
        ordered.extend([origin_code, dest_code])

        # The flight number sits under the route, where the app puts it. Pinned
        # to the top corner instead it drags the eye away from a card whose
        # every other part is centred.
        if spread:
            meta = xbmcgui.ControlLabel(cluster_x, code_y + code_px + 10,
                                        cluster_w, meta_px + 8, "",
                                        font=fonts["meta"], textColor=TEXT_MUTED,
                                        alignment=2)
        else:
            meta = xbmcgui.ControlLabel(ix, meta_y, iw, meta_px + 8, "",
                                        font=fonts["meta"], textColor=TEXT_MUTED,
                                        alignment=1)
        controls["meta"] = meta
        ordered.append(meta)

        # ------------------------------------------------------------ photo
        # The API tops out at 420x280, so the box is sized from that and never
        # above it. Blown up to fill a card the picture is mush. The space is
        # reserved whether or not there is a photograph to put in it: letting
        # the card reflow makes the whole thing jump every time it hands over.
        if places_y is not None:
            places = xbmcgui.ControlLabel(ix, places_y, iw, label_px + 6, "",
                                          font=fonts["label"], textColor=TEXT_MUTED,
                                          alignment=2)
            controls["places"] = places
            ordered.append(places)

        if stacked and self.photos is not None:
            frame_top = code_y + code_px + 22
            avail_h = (places_y - 12) - frame_top - label_px - 6
            frame_h = min(photos.NATIVE_H + PHOTO_INSET * 2, max(0, avail_h))
            photo_h = frame_h - PHOTO_INSET * 2
            photo_w = int(photo_h * float(photos.NATIVE_W) / photos.NATIVE_H)
            frame_w = photo_w + PHOTO_INSET * 2
            if frame_w > iw:
                frame_w = iw
                photo_w = frame_w - PHOTO_INSET * 2
                photo_h = int(photo_w * float(photos.NATIVE_H) / photos.NATIVE_W)
                frame_h = photo_h + PHOTO_INSET * 2

            if photo_h > 60:
                frame_x = ix + (iw - frame_w) // 2
                ordered.extend(self._rounded_rect(frame_x, frame_top, frame_w,
                                                  frame_h, PHOTO_RADIUS, PHOTO_WELL))
                # Sits under the picture and shows through when there is none.
                note = xbmcgui.ControlLabel(
                    frame_x, frame_top + (frame_h - label_px) // 2, frame_w,
                    label_px + 6, "No photo available", font=fonts["label"],
                    textColor=TEXT_FAINT, alignment=6)
                shot = xbmcgui.ControlImage(frame_x + PHOTO_INSET,
                                            frame_top + PHOTO_INSET,
                                            photo_w, photo_h,
                                            os.path.join(self.media, "white.png"),
                                            aspectRatio=2)
                credit = xbmcgui.ControlLabel(frame_x, frame_top + frame_h + 6,
                                              frame_w, label_px + 4, "",
                                              font=fonts["label"],
                                              textColor=TEXT_FAINT, alignment=1)
                controls["photo_note"] = note
                controls["photo"] = shot
                controls["credit"] = credit
                ordered.extend([note, shot, credit])

        # The hairline with an aircraft on it, between the two codes. Three
        # characters is what a code almost always is, so the gap is reserved
        # from that rather than measured per flight.
        reserve = int(3 * code_px * GLYPH_RATIO) + 24
        line_left = cluster_x + reserve
        line_right = cluster_x + cluster_w - reserve
        glyph = max(18, int(code_px * 0.52))
        line_y = code_y + int(code_px * 0.52)
        centre = (line_left + line_right) // 2
        glyph_x = centre - glyph // 2
        white = os.path.join(self.media, "white.png")
        if line_right - line_left > glyph + 40:
            # Kept together so an empty slot can hide the lot: a rule with an
            # aircraft on it and no codes either side looks like a fault.
            rule = [
                xbmcgui.ControlImage(line_left, line_y, glyph_x - line_left - 14, 2,
                                     white, colorDiffuse=HAIRLINE),
                xbmcgui.ControlImage(glyph_x + glyph + 14, line_y,
                                     line_right - glyph_x - glyph - 14, 2, white,
                                     colorDiffuse=HAIRLINE),
                xbmcgui.ControlImage(glyph_x, line_y - glyph // 2, glyph, glyph,
                                     os.path.join(self.media, "plane_090.png"),
                                     colorDiffuse=TEXT),
            ]
            controls["rule"] = rule
            ordered.extend(rule)

        try:
            self.addControls(ordered)
        except Exception as exc:
            xbmc.log("[flighttracker] could not build board row: %s" % exc, xbmc.LOGWARNING)

        return {
            "controls": controls,
            "controls_list": ordered,
            "texts": {},
            "city_chars": int(half / (city_px * GLYPH_RATIO)),
            "places_chars": int(iw / (label_px * GLYPH_RATIO)),
            "meta_chars": int(iw / (meta_px * GLYPH_RATIO)),
        }

    # Only the route flaps. The numbers below it move on nearly every poll, and
    # a card with three counters permanently mid-flap is noise, not character.
    FLAP_KEYS = frozenset(("origin_city", "dest_city", "origin_code", "dest_code"))

    def _update_row(self, row, slot, flight, status=None):
        origin_city, origin_code, dest_city, dest_code = self._route_parts(flight)
        limit = row["city_chars"]
        values = {
            "pill": status or board_status(flight),
            "meta": self._flight_text(flight, row["meta_chars"]),
            "origin_city": self._city(origin_city)[:limit],
            "dest_city": self._city(dest_city)[:limit],
            "origin_code": origin_code,
            "dest_code": dest_code,
            "places": self._airport_line(flight)[:row["places_chars"]],
            "alt_label": "Altitude",
            "speed_label": "Speed",
            "dist_label": "Distance",
            "alt": self.fmt.altitude(flight.alt_ft, flight.on_ground),
            "speed": self.fmt.speed(flight.gs_kt),
            "dist": self.fmt.distance(flight.distance_nm),
        }
        for key, value in values.items():
            control = row["controls"].get(key)
            if control is None or row["texts"].get(key) == value:
                continue
            first = key not in row["texts"]
            row["texts"][key] = value
            if first or not self.cfg.flap_animation or key not in self.FLAP_KEYS:
                self._set_text(control, value)
            else:
                self._flap(control, value)
        self._set_pill(row, *PILL_COLOURS.get(slot, PILL_DEFAULT))
        for key in ("logo", "badge", "plate"):
            self._show(row["controls"].get(key), True)
        for control in row["controls"].get("rule", []):
            self._show(control, True)
        self._update_logo(row, flight)
        self._update_photo(row, flight)

    def _update_photo(self, row, flight):
        """The photograph of this exact airframe, if we have it yet.

        Nothing is waited for. If it is not on disk the request goes out and
        the card carries on without it; the next poll picks it up.
        """
        shot = row["controls"].get("photo")
        if shot is None or self.photos is None:
            return
        registration = flight.registration or ""
        path, photographer = ("", "")
        if registration:
            try:
                path, photographer = self.photos.cached(registration)
            except Exception:
                path, photographer = (None, "")
            if not path:
                try:
                    self.photos.request(registration)
                except Exception:
                    pass

        credit = row["controls"].get("credit")
        note = row["controls"].get("photo_note")
        if path:
            if row["texts"].get("photo") != path:
                row["texts"]["photo"] = path
                shot.setImage(path)
            shot.setVisible(True)
            # Planespotters give the picture away and ask for the name. Shown
            # whether or not there is room to be graceful about it.
            text = photographer or "Planespotters"
            if row["texts"].get("credit") != text:
                row["texts"]["credit"] = text
                self._set_text(credit, text)
            self._show(credit, True)
            self._show(note, False)
        else:
            shot.setVisible(False)
            self._show(credit, False)
            self._show(note, True)

    @staticmethod
    def _show(control, visible):
        if control is not None:
            try:
                control.setVisible(bool(visible))
            except Exception:
                pass

    def _set_pill(self, row, fill, ink):
        if row["texts"].get("pill_fill") == fill:
            return
        row["texts"]["pill_fill"] = fill
        for control in row["controls"].get("pill_bg", []):
            try:
                control.setColorDiffuse(fill)
            except Exception:
                pass
        # The ink has to change with the fill, and a label's colour can only be
        # set by writing the label again.
        label = row["controls"].get("pill")
        if label is not None:
            try:
                label.setLabel(row["texts"].get("pill", ""), textColor=ink)
            except Exception:
                pass

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

    def _named(self, icao, name, city):
        """An airport written out: the field's own name, and the city if that
        is not already in it. "Suvarnabhumi, Bangkok", but just "Krabi"."""
        entry = self.tracker.store.airports.get(icao)
        if entry:
            name = entry.get("name") or name
            city = entry.get("city") or city
        name = (name or "").strip()
        town = self._city(city)
        if not name:
            return town
        if town and town.lower() not in name.lower():
            return "%s, %s" % (name, town)
        return name

    def _airport_line(self, flight):
        """Both airports spelled out, for the fine print under the codes."""
        route = flight.route
        if not route:
            entry = self.tracker.store.airports.get(flight.airport_icao)
            if not entry:
                return ""
            return self._named(flight.airport_icao, entry.get("name"),
                               entry.get("city"))

        right = self._named(route.dest_icao, route.dest_name, route.dest_city)
        if flight.route_conflict == "onward":
            return "Continuing to %s" % right if right else ""
        left = self._named(route.origin_icao, route.origin_name, route.origin_city)
        if left and right:
            return "%s   >   %s" % (left, right)
        return left or right

    def _known_end(self, flight):
        """The end of the route we can name without the route database."""
        entry = self.tracker.store.airports.get(flight.airport_icao)
        if not entry:
            return ("", "--")
        city = self._city(entry.get("city") or entry.get("name") or "")
        return city, (entry.get("iata") or entry.get("icao") or "--").upper()

    def _route_parts(self, flight):
        """Each end of the route as (city, code), for the two ends of the card.

        Cities keep their own capitalisation. The codes are what carries at a
        distance, and the city underneath is there for the ones nobody can place
        from three letters.
        """
        route = flight.route
        if not route:
            # No route in the database, but we do know which of your airports
            # it is using and which way it is going, so half the card is still
            # true. Better than two rows of dashes.
            city, code = self._known_end(flight)
            if flight.kind == KIND_DEPARTURE:
                return (city, code, "", "--")
            if flight.kind == KIND_ARRIVAL:
                return ("", "--", city, code)
            return ("", "--", "", "--")

        dest_city = self._place_name(route.dest_icao, route.dest_city,
                                     route.dest_iata)
        dest_code = (route.dest_iata or route.dest_icao or "--").upper()

        # A multi-sector flight number landing here: we know where it goes next
        # but not where it has come from, so leave that end blank rather than
        # print somewhere it has not been.
        if flight.route_conflict == "onward":
            return ("", "--", dest_city, dest_code)

        origin_city = self._place_name(route.origin_icao, route.origin_city,
                                       route.origin_iata)
        origin_code = (route.origin_iata or route.origin_icao or "--").upper()
        return origin_city, origin_code, dest_city, dest_code

    def _flight_text(self, flight, limit):
        bits = [flight.display_number]
        info = flight.aircraft_info or {}
        kind = flight.type_desc or info.get("type") or flight.type_code
        if kind:
            bits.append(kind)
        if flight.registration:
            bits.append(flight.registration)
        text = "  -  ".join(bits).upper()
        if len(text) > limit and len(bits) > 2:
            text = "  -  ".join(bits[:2]).upper()
        return text[:limit] if len(text) > limit else text

    def _update_logo(self, row, flight):
        if not self.cfg.show_logos or "logo" not in row["controls"]:
            return
        iata = ""
        if flight.route and flight.route.airline_iata:
            iata = flight.route.airline_iata
        if not iata:
            # No route, but the callsign still names the airline. Without this
            # every carrier the route database does not carry loses its logo
            # as well as its route.
            iata = airlines.iata_for(flight.callsign)

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
        # The target keeps its own case: city names are no longer shouted, so
        # settling to an upper-cased copy of them would be wrong.
        text = target
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
            os.path.join(self.media, "home.png"), colorDiffuse=TEXT)]

        for bearing, letter in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            dx, dy = self._offset_for_bearing(bearing, RADAR_R * 0.94)
            controls.append(xbmcgui.ControlLabel(
                int(RADAR_CX + dx) - 30, int(RADAR_CY + dy) - 18, 60, 36, letter,
                font="font27", textColor=TEXT_SOFT, alignment=6))

        for fraction in (0.25, 0.5, 0.75, 1.0):
            radius = RADAR_R * fraction
            controls.append(xbmcgui.ControlLabel(
                RADAR_CX + 8, int(RADAR_CY - radius) - 4, 150, 28,
                self.fmt.distance(self._radar_range * fraction),
                font="font10", textColor=TEXT_FAINT))

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
            controls.extend(self._draw_polyline(polyline, white, TEXT, 6))

        controls.append(xbmcgui.ControlImage(
            RADAR_CX - 16, RADAR_CY - 16, 32, 32,
            os.path.join(self.media, "home.png"), colorDiffuse=TEXT))
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
                os.path.join(self.media, "airport.png"), colorDiffuse=TEXT))
            # The airport name, not the city: Suvarnabhumi and Don Mueang are
            # both "Bangkok", which is no use as a map label.
            entry = self.tracker.store.airports.get(icao)
            name = ((entry or {}).get("name") or icao).upper()
            label_x = int(RADAR_CX + dx) + 14
            label_y = int(RADAR_CY + dy) - 14
            controls.append(xbmcgui.ControlLabel(
                label_x, label_y, 200, 28, name, font="font12", textColor=TEXT_SOFT))
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
                    texture, colorDiffuse="0x557FB8FF"))
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
                # The same number the board prints, or a row and its blip
                # cannot be matched up. Added last so a label is never hidden
                # under another blip.
                labels.append((x + size // 2 + 6, y - 14, flight.display_number, colour))
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
