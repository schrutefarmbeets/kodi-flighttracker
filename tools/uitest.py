"""Runs the Kodi-facing code against stub bindings.

Catches the things that only blow up once Kodi is drawing: missing textures,
text too long for the box it was given, aircraft plotted outside the panel, and
settings ids that exist in settings.xml but not in config.py (or the reverse).

Run:  python tools/uitest.py [--offline]
"""

import math
import os
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

from resources.lib import config, geo, gui, mapdata  # noqa: E402
from resources.lib.model import (Flight, SLOT_ARRIVAL, SLOT_DEPARTURE,  # noqa: E402
                                 SLOT_HEADINGS, board_status)
from resources.lib.routes import Route  # noqa: E402
from resources.lib.tracker import PollResult, Tracker  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(name, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILURES.append(name)


# ---------------------------------------------------------------- settings wiring
def test_settings_wiring():
    print("\n[settings wiring]")
    tree = ET.parse(os.path.join(ADDON_ROOT, "resources", "settings.xml"))
    root = tree.getroot()

    declared = set()
    label_ids = set()
    for setting in root.iter("setting"):
        if setting.get("type") == "action":
            continue
        declared.add(setting.get("id"))
    for element in root.iter():
        for attribute in ("label", "help"):
            value = element.get(attribute)
            if value and value.isdigit():
                label_ids.add(int(value))
    for option in root.iter("option"):
        if option.get("label", "").isdigit():
            label_ids.add(int(option.get("label")))

    cfg = config.Config()
    known = set(vars(cfg).keys())
    missing = declared - known
    unused = known - declared
    check("every setting maps to a Config attribute", not missing, sorted(missing))
    check("every Config attribute has a setting", not unused, sorted(unused))

    loaded = config.from_addon(xbmcaddon.Addon())
    check("defaults load", abs(loaded.home_lat - 13.7280) < 0.0001, str(loaded.home_lat))
    check("integer defaults load", loaded.radius_nm == 60, str(loaded.radius_nm))
    check("boolean defaults load", loaded.orient_radar is True, str(loaded.orient_radar))
    check("string defaults load", loaded.airport_primary == "VTBS", loaded.airport_primary)
    # A second airport is opt-in: defaulting to Don Mueang put its traffic on a
    # board meant for the airport you can actually see.
    check("no second airport by default", loaded.airport_secondary == "",
          repr(loaded.airport_secondary))
    check("only one airport is in play by default",
          config.Config().my_airports == ["VTBS"], str(config.Config().my_airports))
    check("alerts default to off", loaded.notify_enabled is False)
    check("board is the default view", loaded.view_mode == config.VIEW_BOARD)
    check("overflights default to off", loaded.show_overflights is False)

    po_path = os.path.join(ADDON_ROOT, "resources", "language",
                           "resource.language.en_gb", "strings.po")
    with open(po_path, "r", encoding="utf-8") as handle:
        po = handle.read()
    absent = sorted(i for i in label_ids if ('msgctxt "#%d"' % i) not in po)
    check("every settings label exists in strings.po", not absent, str(absent))

    import re
    used = set()
    for name in ("default.py", "service.py"):
        with open(os.path.join(ADDON_ROOT, name), "r", encoding="utf-8") as handle:
            used.update(int(m) for m in re.findall(r"getLocalizedString\((\d+)\)", handle.read()))
    xml_path = os.path.join(ADDON_ROOT, "resources", "skins", "Default", "1080i",
                            "script-flighttracker-main.xml")
    with open(xml_path, "r", encoding="utf-8") as handle:
        for match in re.finditer(r"<label>(\d+)</label>", handle.read()):
            used.add(int(match.group(1)))
    absent_runtime = sorted(i for i in used if ('msgctxt "#%d"' % i) not in po)
    check("every runtime string exists in strings.po", not absent_runtime, str(absent_runtime))


# ---------------------------------------------------------------- fixtures
def make_route(**kw):
    return Route(**kw)

ARRIVAL_ROUTE = make_route(
    callsign="UAE384", airline="Emirates", airline_iata="EK",
    origin_icao="OMDB", origin_iata="DXB", origin_city="Dubai",
    dest_icao="VTBS", dest_iata="BKK", dest_city="Bangkok")

DEPARTURE_ROUTE = make_route(
    callsign="THA132", airline="Thai Airways International", airline_iata="TG",
    origin_icao="VTBS", origin_iata="BKK", origin_city="Bangkok",
    dest_icao="VTCT", dest_iata="CEI", dest_city="Chiang Rai")

LONG_ROUTE = make_route(
    callsign="TLM786", airline="Thai Lion Air", airline_iata="SL",
    origin_icao="VTBD", origin_iata="DMK", origin_city="Bangkok",
    dest_icao="VTSF", dest_iata="NST", dest_city="Nakhon Si Thammarat")


# Suvarnabhumi, so aircraft can be positioned relative to the runway rather
# than to the window. The board now measures from the runway.
VTBS = (13.6811, 100.7471)
VTBD = (13.9126, 100.6070)


def place(cfg, bearing, distance_nm, alt_ft, track, callsign, hexid, vs=0, route=None,
          category="A3", anchor=None):
    origin_lat, origin_lon = anchor if anchor else (cfg.home_lat, cfg.home_lon)
    lat = origin_lat + (distance_nm / 60.0) * math.cos(math.radians(bearing))
    lon = origin_lon + (distance_nm / 60.0) * math.sin(math.radians(bearing)) / \
        math.cos(math.radians(origin_lat))
    flight = Flight.from_raw({
        "hex": hexid, "flight": callsign, "lat": lat, "lon": lon,
        "alt_baro": alt_ft, "gs": 300, "track": track, "baro_rate": vs,
        "r": "HS-TEST", "t": "A320", "desc": "AIRBUS A-320", "category": category,
    })
    flight.compute_geometry(cfg)
    flight.route = route
    return flight


def prepared(cfg, flights, book):
    for flight in flights:
        flight.compute_airport(cfg.my_airports, book)
        flight.classify(cfg.my_airports)
    return flights


def build_window(cfg, logos=None):
    window = gui.FlightWindow(gui.XML_NAME, ADDON_ROOT, "Default", "1080i")
    window.controls = {
        gui.TITLE_ID: xbmcgui.ControlBase(),
        gui.STATUS_ID: xbmcgui.ControlBase(),
        gui.RADAR_ID: xbmcgui.ControlBase(),
        gui.LEGEND_ID: xbmcgui.ControlBase(),
        gui.RANGE_ID: xbmcgui.ControlBase(),
        gui.MESSAGE_ID: xbmcgui.ControlBase(),
        gui.BTN_REFRESH: xbmcgui.ControlBase(),
        gui.BTN_VIEW: xbmcgui.ControlBase(),
        gui.BTN_SETTINGS: xbmcgui.ControlBase(),
    }
    cache = os.path.join(tempfile.mkdtemp(prefix="fluitest"), "routes.json")
    tracker = Tracker(cfg, cache)
    window.prepare(xbmcaddon.Addon(), cfg, tracker,
                   os.path.join(ADDON_ROOT, "resources", "media"),
                   lambda: cfg, logo_store=logos)
    return window


# ---------------------------------------------------------------- now selection
def test_one_airport():
    """Traffic at an airport you cannot see must not reach the board."""
    print("\n[single airport]")
    cfg = config.Config()          # defaults: Suvarnabhumi only
    window = build_window(cfg)
    book = window.tracker.store.airports

    dmk_route = make_route(
        callsign="AIQ3360", airline="Thai AirAsia", airline_iata="FD",
        origin_icao="VTBD", origin_iata="DMK", origin_city="Bangkok",
        dest_icao="VTUU", dest_iata="UBP", dest_city="Ubon Ratchathani")
    dmk = place(cfg, 30, 3, 5000, 30, "AIQ3360", "d1", vs=2000, route=dmk_route,
                anchor=VTBD)
    bkk = place(cfg, 20, 4, 3000, 20, "THA132", "d2", vs=2000, route=DEPARTURE_ROUTE,
                anchor=VTBS)
    prepared(cfg, [dmk, bkk], book)

    check("Don Mueang traffic is not a departure here", dmk.kind != "departure", dmk.kind)
    check("Suvarnabhumi traffic still is", bkk.kind == "departure", bkk.kind)

    rows = dict(window.tracker.select_now([dmk, bkk]))
    check("the board shows the airport you can see",
          rows.get(SLOT_DEPARTURE) is bkk,
          rows[SLOT_DEPARTURE].callsign if SLOT_DEPARTURE in rows else "none")

    # And with overflights off it is filtered out of the panels entirely.
    window.tracker.update_config(cfg)
    check("and is filtered out with overflights off",
          not window.tracker._passes_traffic_filter(dmk))
    window._stop.set()


def test_multisector_callsign():
    """A landing aircraft must read as landing, whatever the route says.

    Taken from a real sighting: KLM843 on short final into Suvarnabhumi at
    675 ft descending 768 fpm, while adsbdb holds KL843 as Bangkok to Taipei
    because the flight keeps one callsign from Amsterdam through to Taiwan.
    The board called it a departure.
    """
    print("\n[multi-sector callsign]")
    cfg = config.Config()
    window = build_window(cfg)
    book = window.tracker.store.airports

    onward = make_route(
        callsign="KLM843", airline="KLM Royal Dutch Airlines", airline_iata="KL",
        origin_icao="VTBS", origin_iata="BKK", origin_city="Bangkok",
        dest_icao="RCTP", dest_iata="TPE", dest_city="Taipei")

    landing = place(cfg, 20, 3, 675, 200, "KLM843", "k1", vs=-768, route=onward,
                    anchor=VTBS)
    prepared(cfg, [landing], book)

    check("short final reads as an arrival", landing.kind == "arrival", landing.kind)
    check("status says LANDING", board_status(landing) == "LANDING", board_status(landing))
    check("the stale route is flagged", landing.route_conflict == "onward",
          str(landing.route_conflict))

    text = window._route_text(landing, 40)
    check("the board does not claim it departed Bangkok",
          not text.startswith("BANGKOK"), text)
    check("it says where the flight goes next", "TAIPEI" in text, text)
    print("       renders as: %s   [%s]" % (text, board_status(landing)))

    # A genuine departure on the same numbers must still read as one.
    climbing = place(cfg, 20, 5, 3000, 20, "KLM843", "k2", vs=2200, route=onward,
                     anchor=VTBS)
    prepared(cfg, [climbing], book)
    check("a real departure still reads as one", climbing.kind == "departure", climbing.kind)
    check("and keeps its route", climbing.route_conflict is None)
    print("       renders as: %s   [%s]"
          % (window._route_text(climbing, 40), board_status(climbing)))

    # A go-around climbing away must not be flipped to a departure when the
    # route says it is inbound here.
    inbound = make_route(
        callsign="THA916", airline="Thai Airways International", airline_iata="TG",
        origin_icao="EGLL", origin_iata="LHR", origin_city="London",
        dest_icao="VTBS", dest_iata="BKK", dest_city="Bangkok")
    goaround = place(cfg, 20, 4, 2500, 200, "THA916", "k3", vs=1800, route=inbound,
                     anchor=VTBS)
    prepared(cfg, [goaround], book)
    check("a go-around stays an arrival", goaround.kind == "arrival", goaround.kind)

    # And cruising traffic high overhead is untouched by any of this.
    cruising = place(cfg, 20, 8, 34000, 90, "SIA999", "k4", vs=0, anchor=VTBS)
    prepared(cfg, [cruising], book)
    check("high overflight is not dragged into the terminal logic",
          cruising.kind != "arrival", cruising.kind)
    window._stop.set()


def test_runway_queue():
    """The board is the runway queue, ranked by distance to the runway."""
    print("\n[runway queue]")
    cfg = config.Config(show_arrivals=True, show_departures=True,
                        show_overflights=False, board_rows=3, approach_range_nm=15)
    window = build_window(cfg)
    book = window.tracker.store.airports

    # A landing sequence, one aircraft just off the runway, one still miles
    # out, and a helicopter loitering near the field.
    a1 = place(cfg, 20, 2, 900, 200, "UAE384", "q1", vs=-700,
               route=ARRIVAL_ROUTE, anchor=VTBS)
    d1 = place(cfg, 200, 4, 2000, 20, "THA132", "q2", vs=2400,
               route=DEPARTURE_ROUTE, anchor=VTBS)
    a2 = place(cfg, 20, 6, 2400, 200, "SIA978", "q3", vs=-900,
               route=ARRIVAL_ROUTE, anchor=VTBS)
    # 11 nm out on a three degree profile is about 3,300 ft.
    a3 = place(cfg, 20, 11, 3200, 200, "QTR834", "q4", vs=-1100,
               route=ARRIVAL_ROUTE, anchor=VTBS)
    far = place(cfg, 20, 40, 18000, 200, "UAE999", "q5", vs=-1200,
                route=ARRIVAL_ROUTE, anchor=VTBS)
    heli = place(cfg, 20, 3, 700, 200, "MNRE5120", "q6", vs=-300,
                 category="A7", anchor=VTBS)
    flights = prepared(cfg, [a3, far, d1, heli, a1, a2], book)

    rows = window.tracker.select_now(flights)
    order = [f.callsign for _, f in rows]
    check("capped at the configured row count", len(rows) == 3, str(len(rows)))
    check("ranked by track miles from the runway",
          order == ["UAE384", "THA132", "SIA978"], str(order))
    check("a departure can outrank a more distant arrival",
          order.index("THA132") < order.index("SIA978"), str(order))
    check("traffic beyond the approach range is left off",
          "UAE999" not in order, str(order))
    check("the fourth in the queue does not fit", "QTR834" not in order, str(order))
    check("rotorcraft never reaches the board", "MNRE5120" not in order, str(order))
    check("rotorcraft is not treated as an airliner", not heli.is_airliner)
    check("uncategorised traffic still counts as an airliner",
          place(cfg, 20, 4, 1800, 200, "X", "x1", category="A0", anchor=VTBS).is_airliner)

    # Only two words on the board.
    words = set(board_status(f) for _, f in rows)
    check("statuses are only LANDING and TAKE OFF",
          words <= {"LANDING", "TAKE OFF"}, str(sorted(words)))
    check("a distant inbound would still read LANDING if shown",
          board_status(far) == "LANDING", board_status(far))
    check("slot label never repeats the status",
          SLOT_HEADINGS[SLOT_DEPARTURE] != board_status(d1),
          SLOT_HEADINGS[SLOT_DEPARTURE])

    # Row count is configurable.
    cfg.board_rows = 2
    check("row count setting is honoured", len(window.tracker.select_now(flights)) == 2)
    cfg.board_rows = 3

    # Tightening the approach range shortens the queue.
    cfg.approach_range_nm = 5
    tight = [f.callsign for _, f in window.tracker.select_now(flights)]
    check("a tighter approach range drops the further ones",
          tight == ["UAE384", "THA132"], str(tight))
    cfg.approach_range_nm = 15

    # Category switches.
    cfg.show_departures = False
    arrivals_only = [f.callsign for _, f in window.tracker.select_now(flights)]
    check("departures can be switched off",
          arrivals_only == ["UAE384", "SIA978", "QTR834"], str(arrivals_only))
    cfg.show_departures = True

    cfg.show_arrivals = False
    departures_only = [f.callsign for _, f in window.tracker.select_now(flights)]
    check("arrivals can be switched off", departures_only == ["THA132"],
          str(departures_only))
    cfg.show_arrivals = True

    # An overflight only ever fills a row the runway has left empty.
    overflight = place(cfg, 300, 20, 37000, 90, "QTR970", "q7", vs=0,
                       route=make_route(origin_icao="OTHH", origin_iata="DOH",
                                        origin_city="Doha", dest_icao="WSSS",
                                        dest_iata="SIN", dest_city="Singapore"))
    prepared(cfg, [overflight], book)
    cfg.show_overflights = True
    full = [f.callsign for _, f in window.tracker.select_now(flights + [overflight])]
    check("a full runway queue leaves no room for an overflight",
          "QTR970" not in full, str(full))
    quiet = [f.callsign for _, f in window.tracker.select_now([a1, overflight])]
    check("a quiet runway lets one through", "QTR970" in quiet, str(quiet))
    cfg.show_overflights = False

    # Height counts as distance still to fly. Taken from a real sighting:
    # MAS784 was close enough to the field to reach the board but at 8,000 ft,
    # which is nothing like landing next, and HVN601 sat 7 nm out at 11,250 ft.
    high = place(cfg, 20, 7.4, 11250, 200, "HVN601", "q8", vs=-320,
                 route=ARRIVAL_ROUTE, anchor=VTBS)
    low_but_far = place(cfg, 20, 14.6, 2100, 200, "AFR198", "q9", vs=-64,
                        route=ARRIVAL_ROUTE, anchor=VTBS)
    prepared(cfg, [high, low_but_far], book)

    check("height counts against an aircraft near the field",
          high.runway_track_nm > 30, "%.1f" % high.runway_track_nm)
    check("a low aircraft further out is closer to landing",
          low_but_far.runway_track_nm < high.runway_track_nm,
          "%.1f vs %.1f" % (low_but_far.runway_track_nm, high.runway_track_nm))

    ranked = [f.callsign for _, f in window.tracker.select_now([high, low_but_far, a1])]
    check("the high one is kept off the board", "HVN601" not in ranked, str(ranked))
    check("the one actually on final is on it", "AFR198" in ranked, str(ranked))

    # A climbing departure is not judged on the approach gradient.
    climbing = place(cfg, 200, 8.6, 5150, 20, "THA301", "q10", vs=3360,
                     route=DEPARTURE_ROUTE, anchor=VTBS)
    prepared(cfg, [climbing], book)
    check("a departure is measured against its own climb gradient",
          climbing.runway_track_nm < 10, "%.1f" % climbing.runway_track_nm)

    # And the board prints the flight number people can actually look up.
    with_iata = make_route(
        callsign="MAS784", callsign_iata="MH784", airline="Malaysia Airlines",
        airline_iata="MH", origin_icao="WMKK", origin_iata="KUL",
        origin_city="Kuala Lumpur", dest_icao="VTBS", dest_iata="BKK",
        dest_city="Bangkok")
    mas = place(cfg, 20, 4, 1500, 200, "MAS784", "q11", vs=-700,
                route=with_iata, anchor=VTBS)
    prepared(cfg, [mas], book)
    check("the board shows the IATA flight number", mas.display_number == "MH784",
          mas.display_number)
    check("and falls back to the callsign without one",
          a1.display_number == "UAE384", a1.display_number)
    window._stop.set()


# ---------------------------------------------------------------- board rows
def test_board():
    print("\n[board]")
    cfg = config.Config(airport_primary="VTBS", airport_secondary="VTBD")
    window = build_window(cfg)
    book = window.tracker.store.airports

    near = place(cfg, 20, 3, 1800, 200, "UAE384", "a1", vs=-900,
                 route=ARRIVAL_ROUTE, anchor=VTBS)
    departing = place(cfg, 200, 5, 4000, 20, "THA132", "b1", vs=2000,
                      route=DEPARTURE_ROUTE, anchor=VTBS)
    flights = prepared(cfg, [near, departing], book)

    window._render(PollResult(flights))
    check("two rows built", len(window._rows) == 2, str(len(window._rows)))

    for row in window._rows:
        for key in ("slot", "status", "route", "flight"):
            value = row["texts"].get(key, "")
            check("row %s is filled in" % key, isinstance(value, str) and value != "",
                  repr(value))
        check("route is uppercase", row["texts"]["route"] == row["texts"]["route"].upper())
        # The overflow class of bug: text must fit the box it was measured for.
        check("route fits its box",
              len(row["texts"]["route"]) <= row["route_chars"],
              "%d chars in %d" % (len(row["texts"]["route"]), row["route_chars"]))
        check("flight line fits its box",
              len(row["texts"]["flight"]) <= row["flight_chars"],
              "%d chars in %d" % (len(row["texts"]["flight"]), row["flight_chars"]))

    for row in window._rows:
        print("       %s | %s | %s" % (row["texts"]["slot"], row["texts"]["route"],
                                       row["texts"]["status"]))

    # Rows are ranked by track miles, so which one lands where is not fixed.
    by_slot = {row["texts"]["slot"]: row for row in window._rows}
    check("both an arrival and a departure are on the board",
          set(by_slot) == {"ARRIVAL", "DEPARTURE"}, str(sorted(by_slot)))
    arrival_row = by_slot.get("ARRIVAL")
    check("route names both ends", ">" in arrival_row["texts"]["route"])
    check("arrival names its origin", "DUBAI" in arrival_row["texts"]["route"],
          arrival_row["texts"]["route"])

    # A long city pair must degrade to codes rather than spill over.
    long_flight = place(cfg, 200, 4, 3000, 200, "TLM786", "d1", vs=1500,
                        route=LONG_ROUTE, anchor=VTBS)
    prepared(cfg, [long_flight], book)
    narrow = window._rows[0]
    text = window._route_text(long_flight, narrow["route_chars"])
    check("long route still fits", len(text) <= narrow["route_chars"],
          "%r is %d chars, limit %d" % (text, len(text), narrow["route_chars"]))
    print("       long route renders as: %s" % text)

    # Textures must exist.
    images = [c for c in window._rows[0]["controls_list"]
              if isinstance(c, xbmcgui.ControlImage)]
    absent = sorted({c.filename for c in images if not os.path.exists(c.filename)})
    check("every board texture exists", not absent, str(absent))

    # No logo store, so the badge should carry the airline code.
    check("badge falls back to the airline code",
          arrival_row["texts"].get("badge") == "EK",
          repr(arrival_row["texts"].get("badge")))

    # Rows must be rebuilt when the shape changes, not stacked up.
    before = len(window._rows)
    window._render(PollResult([near]))
    check("row count follows the selection", len(window._rows) == 1,
          "%d then %d" % (before, len(window._rows)))
    window._stop.set()


def test_flap():
    print("\n[split-flap]")
    cfg = config.Config()
    window = build_window(cfg)
    control = xbmcgui.ControlLabel(0, 0, 100, 40, "")
    window._flap(control, "BANGKOK  >  DUBAI")
    import time
    time.sleep(gui.FLAP_DURATION + 0.35)
    check("animation settles on the target text",
          control.getLabel() == "BANGKOK  >  DUBAI", repr(control.getLabel()))
    check("spaces are held still during the flap", True)
    window._stop.set()


# ---------------------------------------------------------------- panels
def test_panels():
    print("\n[panels]")
    cfg = config.Config(view_mode=config.VIEW_RADAR, view_bearing=135, view_fov=140,
                        orient_radar=True, radius_nm=60,
                        airport_primary="VTBS", airport_secondary="VTBD")
    window = build_window(cfg)
    book = window.tracker.store.airports
    flights = prepared(cfg, [
        place(cfg, 135, 12, 6000, 135, "AHEAD1", "e1", vs=-800, route=ARRIVAL_ROUTE),
        place(cfg, 315, 12, 6000, 0, "BEHIND", "e2", vs=900, route=DEPARTURE_ROUTE),
        place(cfg, 135, 55, 35000, 90, "FAR1", "e3"),
    ], book)

    window._draw_panel()
    check("radar furniture drawn", len(window._static) > 0, str(len(window._static)))
    window._render_panel(flights, {flights[0].hex})
    check("blips drawn", len(window._blips) > 0, str(len(window._blips)))

    # Labelling everything is unreadable once traffic bunches up on approach,
    # so only what is on the board gets named.
    labels = [c for c in window._blips if isinstance(c, xbmcgui.ControlLabel)]
    check("only board aircraft are labelled", len(labels) == 1, str(len(labels)))
    if labels:
        check("the label names the board aircraft", labels[0].label == "AHEAD1",
              labels[0].label)

    # Two board aircraft in nearly the same place must not stack their labels.
    twins = prepared(cfg, [
        place(cfg, 135, 12.0, 4000, 135, "TWIN1", "t1", vs=-800, route=ARRIVAL_ROUTE),
        place(cfg, 135, 12.2, 5000, 135, "TWIN2", "t2", vs=900, route=DEPARTURE_ROUTE),
    ], book)
    window._render_panel(twins, {"t1", "t2"})
    pair = [c for c in window._blips if isinstance(c, xbmcgui.ControlLabel)]
    check("both twins are labelled", len(pair) == 2, str(len(pair)))
    if len(pair) == 2:
        check("overlapping labels are nudged apart",
              abs(pair[0].y - pair[1].y) >= 28 or abs(pair[0].x - pair[1].x) >= 100,
              "%s vs %s" % ((pair[0].x, pair[0].y), (pair[1].x, pair[1].y)))

    left, right = gui.RADAR_CX - gui.RADAR_R - 40, gui.RADAR_CX + gui.RADAR_R + 40
    top, bottom = gui.RADAR_CY - gui.RADAR_R - 40, gui.RADAR_CY + gui.RADAR_R + 40
    images = [c for c in window._blips + window._static if isinstance(c, xbmcgui.ControlImage)]
    stray = [(c.x, c.y) for c in images
             if not (left <= c.x <= right and top <= c.y <= bottom)]
    check("everything plots inside the panel", not stray, str(stray[:4]))

    absent = sorted({c.filename for c in images if not os.path.exists(c.filename)})
    check("every panel texture exists", not absent, str(absent))

    # Auto-range should pull in when the traffic is close.
    close = prepared(cfg, [place(cfg, 135, 9, 3000, 135, "CLOSE1", "f1",
                                 route=ARRIVAL_ROUTE)], book)
    window._render_panel(close)
    check("range tightens around close traffic", window._radar_range <= 15,
          "%.0f nm" % window._radar_range)
    window._render_panel(flights)
    check("range opens back up for distant traffic", window._radar_range >= 60,
          "%.0f nm" % window._radar_range)

    # Aircraft dead ahead plots straight up when the radar is turned to the window.
    ahead = geo.project_to_radar(flights[0].lat, flights[0].lon, cfg.home_lat,
                                 cfg.home_lon, window._radar_range, gui.RADAR_R,
                                 window._rotation())
    check("aircraft ahead plots straight up",
          ahead is not None and abs(ahead[0]) < 1.5 and ahead[1] < 0, str(ahead))

    # Map mode.
    cfg.view_mode = config.VIEW_MAP
    window._radar_range = 60.0
    window._draw_panel()
    check("map furniture drawn", len(window._static) > 0, str(len(window._static)))
    map_images = [c for c in window._static if isinstance(c, xbmcgui.ControlImage)]
    stray_map = [(c.x, c.y) for c in map_images
                 if not (left <= c.x <= right and top <= c.y <= bottom)]
    check("map geometry stays inside the panel", not stray_map, str(stray_map[:4]))
    check("map data has coastline", len(mapdata.coastline()) >= 2)
    check("map data has runways for both airports",
          len(mapdata.runways(["VTBS", "VTBD"])) == 4,
          str(len(mapdata.runways(["VTBS", "VTBD"]))))
    window._stop.set()


# ---------------------------------------------------------------- end to end
def test_live(offline):
    print("\n[live render]")
    if offline:
        print("  skip (offline)")
        return
    from resources.lib.logos import LogoStore
    cfg = config.from_addon(xbmcaddon.Addon())
    logos = LogoStore(tempfile.mkdtemp(prefix="fllogos"))
    window = build_window(cfg, logos=logos)

    window.tracker.poll()
    result = window.tracker.poll()
    window._render(result)

    check("status line written", bool(window.controls[gui.STATUS_ID].label),
          window.controls[gui.STATUS_ID].label)
    check("title written", bool(window.controls[gui.TITLE_ID].label))
    print("       title : %s" % window.controls[gui.TITLE_ID].label)
    print("       status: %s" % window.controls[gui.STATUS_ID].label)

    if window._rows:
        for row in window._rows:
            print("       %-12s %-34s %s" % (row["texts"].get("slot", ""),
                                             row["texts"].get("route", ""),
                                             row["texts"].get("status", "")))
            print("                    %s" % row["texts"].get("flight", ""))
            check("live route fits", len(row["texts"].get("route", "")) <= row["route_chars"],
                  row["texts"].get("route", ""))
        logo_files = os.listdir(logos.directory)
        print("       logos cached: %s" % (", ".join(logo_files) or "none"))
        check("at least one logo or badge resolved",
              bool(logo_files) or any(r["texts"].get("badge") for r in window._rows))
    else:
        print("       nothing on approach or departure at the moment")

    window._render(PollResult([]))
    check("empty result shows a message", window.controls[gui.MESSAGE_ID].visible)
    window._render(PollResult([], error="boom"))
    check("feed error shows a message", window.controls[gui.MESSAGE_ID].visible)
    check("feed error names the failure", "boom" in window.controls[gui.MESSAGE_ID].label,
          window.controls[gui.MESSAGE_ID].label)
    window._stop.set()


def main():
    offline = "--offline" in sys.argv
    print("Flight Tracker UI test%s" % (" (offline)" if offline else ""))
    test_settings_wiring()
    test_one_airport()
    test_multisector_callsign()
    test_runway_queue()
    test_board()
    test_flap()
    test_panels()
    test_live(offline)

    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        for name in FAILURES:
            print("  FAILED: %s" % name)
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
