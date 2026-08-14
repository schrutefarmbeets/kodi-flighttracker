"""Exercises everything in the addon that does not need Kodi.

Run:  python tools/selftest.py [--offline]

Checks the geometry against hand-worked numbers, round-trips the route cache,
then does a real poll of the configured area and prints the list exactly as the
Kodi window would build it.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.join(os.path.dirname(HERE), "script.flighttracker")
sys.path.insert(0, ADDON_ROOT)

from resources.lib import config, geo  # noqa: E402
from resources.lib.airports import AirportBook  # noqa: E402
from resources.lib.model import Flight, Formatter  # noqa: E402
from resources.lib.routes import RouteStore  # noqa: E402
from resources.lib.tracker import Tracker  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(name, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def close_to(a, b, tolerance):
    return a is not None and abs(a - b) <= tolerance


# ---------------------------------------------------------------- geometry
def test_geo():
    print("\n[geo]")
    # Sukhumvit to Suvarnabhumi is about 15 nm on a bearing just south of east.
    home_lat, home_lon = 13.7280, 100.5820
    bkk_lat, bkk_lon = 13.6811, 100.7471
    distance = geo.haversine_nm(home_lat, home_lon, bkk_lat, bkk_lon)
    bearing = geo.bearing_deg(home_lat, home_lon, bkk_lat, bkk_lon)
    check("BKK is ~10 nm away", close_to(distance, 10.0, 1.5), "got %.2f nm" % distance)
    check("BKK is east-southeast", close_to(bearing, 106.0, 6.0), "got %.1f deg" % bearing)

    # A known right triangle: 10000 ft up, 10 nm out, ignoring curvature would
    # be atan(3048 / 18520) = 9.34 deg. Curvature pulls it down a little.
    elevation = geo.elevation_angle_deg(10.0, 10000.0, 110.0)
    check("elevation angle is sane", 8.0 < elevation < 9.4, "got %.2f deg" % elevation)

    # A cruising aircraft at the far edge of a 60 nm radar sits low: flat
    # geometry says 5.8 deg, and the curvature drop takes it to about 5.4.
    far = geo.elevation_angle_deg(60.0, 37000.0, 110.0)
    check("distant cruiser is low in the sky", 0.0 < far < 7.0, "got %.2f deg" % far)
    flat = geo.elevation_angle_deg(60.0, 37000.0, 110.0)
    check("curvature lowers it below flat geometry", flat < 5.79, "got %.2f deg" % flat)

    # Beyond the horizon for a low aircraft.
    hidden = geo.elevation_angle_deg(60.0, 2000.0, 110.0)
    check("low + far is below the horizon", hidden < 0, "got %.2f deg" % hidden)

    check("compass N", geo.compass_point(2) == "N", geo.compass_point(2))
    check("compass ESE", geo.compass_point(115) == "ESE", geo.compass_point(115))
    check("angular difference wraps", close_to(geo.angular_difference(350, 10), 20, 0.001))
    check("relative bearing goes left", close_to(geo.relative_bearing(90, 135), -45, 0.001))
    check("relative bearing goes right", close_to(geo.relative_bearing(180, 135), 45, 0.001))

    check("in view inside the cone", geo.is_in_view(135, 135, 140))
    check("out of view behind you", not geo.is_in_view(315, 135, 140))

    # Radar projection: due north at exactly the radar range lands at the top.
    north = geo.project_to_radar(home_lat + 1.0, home_lon, home_lat, home_lon, 60.0, 386, 0.0)
    check("due north plots straight up",
          north is not None and close_to(north[0], 0.0, 0.5) and north[1] < 0,
          str(north))

    # With the radar turned to the window, the view bearing must plot upwards.
    view = 135.0
    import math
    offset = 0.5
    lat2 = home_lat + offset * math.cos(math.radians(view))
    lon2 = home_lon + offset * math.sin(math.radians(view)) / math.cos(math.radians(home_lat))
    rotated = geo.project_to_radar(lat2, lon2, home_lat, home_lon, 60.0, 386, view)
    check("view bearing plots straight up when rotated",
          rotated is not None and close_to(rotated[0], 0.0, 3.0) and rotated[1] < 0,
          str(rotated))

    outside = geo.project_to_radar(home_lat + 5.0, home_lon, home_lat, home_lon, 60.0, 386, 0.0)
    check("far outside the radar is dropped", outside is None, str(outside))


# ---------------------------------------------------------------- parsing
def test_parsing():
    print("\n[parsing]")
    raw = {
        "hex": "885308", "flight": "THA132  ", "r": "HS-TXH", "t": "A320",
        "alt_baro": 21225, "gs": 364.2, "track": 348.6, "baro_rate": 768,
        "lat": 14.131989, "lon": 100.423894, "squawk": "4225",
    }
    flight = Flight.from_raw(raw)
    check("callsign is trimmed", flight.callsign == "THA132", repr(flight.callsign))
    check("altitude parsed", flight.alt_ft == 21225)
    check("not on ground", flight.on_ground is False)

    ground = Flight.from_raw(dict(raw, alt_baro="ground"))
    check("ground string handled", ground.on_ground and ground.alt_ft == 0)

    no_pos = Flight.from_raw({"hex": "abc", "flight": "X"})
    check("positionless aircraft dropped", no_pos is None)

    geom_only = Flight.from_raw(dict(raw, baro_rate=None, geom_rate=-900))
    check("falls back to geom_rate", geom_only.vs_fpm == -900, str(geom_only.vs_fpm))

    cfg = config.Config(home_lat=13.7280, home_lon=100.5820, view_bearing=135, view_fov=140)
    flight.compute_geometry(cfg)
    check("distance computed", flight.distance_nm > 0)
    check("phase is climbing", flight.phase == "climbing", flight.phase)

    fmt = Formatter(config.UNITS_AVIATION)
    check("altitude formatting", fmt.altitude(21225) == "21,225 ft", fmt.altitude(21225))
    check("vertical formatting", fmt.vertical(768) == "+768 fpm", fmt.vertical(768))
    check("vertical deadband is quiet", fmt.vertical(100) == "", fmt.vertical(100))
    check("ground formatting", fmt.altitude(0, True) == "ground")
    metric = Formatter(config.UNITS_METRIC)
    check("metric altitude", metric.altitude(10000) == "3,048 m", metric.altitude(10000))
    check("metric distance", metric.distance(10) == "18.5 km", metric.distance(10))


# ---------------------------------------------------------------- airports
def test_airports():
    print("\n[airports]")
    book = AirportBook()
    check("seed has Suvarnabhumi", book.position("VTBS") is not None)
    check("seed label is the city", book.label("VTBS") == "Bangkok", book.label("VTBS"))
    check("unknown airport is None", book.position("ZZZZ") is None)
    book.learn("ZZZZ", "ZZZ", "Test Field", "Testville", 1.0, 2.0)
    check("learned airport sticks", book.position("ZZZZ") == (1.0, 2.0))
    check("learned airports are exportable", "ZZZZ" in book.export_learned())


# ---------------------------------------------------------------- routes
def test_routes(offline):
    print("\n[routes]")
    path = os.path.join(tempfile.mkdtemp(prefix="fltest"), "routes.json")
    store = RouteStore(path, ttl_days=30)

    route, known = store.cached("THA132")
    check("cold cache is a miss", route is None and not known)

    if offline:
        print("  skip (offline): live adsbdb lookups")
        return

    route = store.fetch("THA132")
    check("THA132 resolved", route is not None)
    if route:
        check("airline named", "Thai" in (route.airline or ""), route.airline)
        check("origin is BKK", route.origin_iata == "BKK", route.origin_iata)
        check("destination present", bool(route.dest_iata), route.dest_iata)
        check("pair label built", " - " in route.pair, route.pair)
        check("airport coords learned", store.airports.position(route.origin_icao) is not None)

    store.save()
    check("cache file written", os.path.exists(path))

    reloaded = RouteStore(path, ttl_days=30)
    cached_route, known = reloaded.cached("THA132")
    check("route survives a reload", cached_route is not None and known)
    if cached_route:
        check("reloaded origin matches", cached_route.origin_iata == "BKK")
    check("learned airports survive a reload",
          reloaded.airports.position("VTBS") is not None)

    missing = store.fetch("ZZZZ999")
    check("unknown callsign returns nothing", missing is None)
    _, known_miss = store.cached("ZZZZ999")
    check("miss is remembered", known_miss)

    # The combined endpoint should answer both halves in a single request.
    fresh = RouteStore(os.path.join(tempfile.mkdtemp(prefix="fltest"), "routes.json"))
    before = fresh.requests
    pair_route, pair_info = fresh.fetch_pair("885308", "THA132")
    check("combined lookup cost one request", fresh.requests - before == 1,
          "spent %d" % (fresh.requests - before))
    check("combined lookup returned a route", pair_route is not None)
    check("combined lookup returned an airframe", bool(pair_info))
    if pair_info:
        check("airframe has a registration", bool(pair_info.get("registration")),
              str(pair_info))

    # An unknown airframe must still yield the route, via the fallback path.
    fallback = RouteStore(os.path.join(tempfile.mkdtemp(prefix="fltest"), "routes.json"))
    fb_route, fb_info = fallback.fetch_pair("ffffff", "THA132")
    check("unknown airframe still resolves the route", fb_route is not None)
    check("unknown airframe reports no airframe", fb_info is None)


# ---------------------------------------------------------------- live poll
def test_live_poll(offline):
    print("\n[live poll]")
    if offline:
        print("  skip (offline)")
        return

    cfg = config.Config(
        home_lat=13.7280, home_lon=100.5820, observer_alt_m=110,
        view_bearing=135, view_fov=140, radius_nm=60, max_flights=25,
        airport_primary="VTBS", airport_secondary="VTBD",
    )
    path = os.path.join(tempfile.mkdtemp(prefix="fltest"), "routes.json")
    tracker = Tracker(cfg, path, logger=lambda m: print("       log: %s" % m))
    result = tracker.poll()

    check("feed answered", result.error is None, str(result.error))
    check("aircraft returned", len(result.flights) > 0,
          "%d of %d seen" % (len(result.flights), result.total_seen))
    check("sorted by distance",
          all(result.flights[i].distance_nm <= result.flights[i + 1].distance_nm
              for i in range(len(result.flights) - 1)))
    check("radius respected",
          all(f.distance_nm <= cfg.radius_nm + 0.01 for f in result.flights))

    fmt = Formatter(cfg.units)
    routed = 0
    classified = 0
    print("\n  %-9s %-22s %-26s %9s %10s %7s %6s" %
          ("FLIGHT", "AIRLINE", "ROUTE", "DIST", "ALT", "BRG", "UP"))
    print("  " + "-" * 96)
    for flight in result.flights[:18]:
        if flight.route:
            routed += 1
        if flight.kind != "unknown":
            classified += 1
        route_text = "-"
        if flight.route:
            origin = flight.route.origin_city or flight.route.origin_iata or "?"
            dest = flight.route.dest_city or flight.route.dest_iata or "?"
            route_text = ("%s > %s" % (origin, dest))[:26]
        print("  %-9s %-22s %-26s %9s %10s %5d%s %5s%s" % (
            flight.display_callsign,
            (flight.airline_name or "-")[:22],
            route_text,
            fmt.distance(flight.distance_nm),
            fmt.altitude(flight.alt_ft, flight.on_ground),
            int(round(flight.bearing_deg)), geo.compass_point(flight.bearing_deg)[:1],
            int(round(flight.elevation_deg)),
            "*" if flight.in_view else " ",
        ))

    print("\n  %d of %d shown flights had a resolved route" % (routed, min(18, len(result.flights))))
    print("  %d were classified as arrival/departure/overflight" % classified)
    print("  kinds: " + ", ".join(sorted(set(f.kind for f in result.flights))))
    print("  in view of a %d deg window facing %d deg: %d"
          % (cfg.view_fov, cfg.view_bearing, sum(1 for f in result.flights if f.in_view)))

    check("at least one route resolved on a live poll", routed > 0)

    check("lookup budget respected on a cold cache",
          tracker.store.requests <= 10, "spent %d requests" % tracker.store.requests)

    # Second poll should be served largely from cache: it may spend the budget
    # again on aircraft the first poll had no room for, but never more.
    spent_before = tracker.store.requests
    again = tracker.poll()
    check("second poll works", again.error is None)
    check("second poll stays inside the budget",
          tracker.store.requests - spent_before <= 10,
          "spent %d" % (tracker.store.requests - spent_before))
    print("  routes known after two polls: %d of %d"
          % (sum(1 for f in again.flights if f.route), len(again.flights)))
    tracker.close()

    # Filters
    strict = config.Config(
        home_lat=cfg.home_lat, home_lon=cfg.home_lon, radius_nm=60,
        min_alt_ft=0, max_alt_ft=8000, airport_primary="VTBS", airport_secondary="VTBD")
    tracker.update_config(strict)
    low = tracker.poll()
    check("altitude ceiling respected",
          all(f.alt_ft is None or f.alt_ft <= 8000 for f in low.flights),
          "%d low aircraft" % len(low.flights))


def main():
    offline = "--offline" in sys.argv
    print("Flight Tracker self test%s" % (" (offline)" if offline else ""))
    test_geo()
    test_parsing()
    test_airports()
    test_routes(offline)
    test_live_poll(offline)

    print("\n%d checks, %d failures" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        for name in FAILURES:
            print("  FAILED: %s" % name)
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
