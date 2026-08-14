"""The Flight object: one aircraft, plus everything derived for the window view."""

from . import config, geo

KIND_ARRIVAL = "arrival"
KIND_DEPARTURE = "departure"
KIND_OVERFLIGHT = "overflight"
KIND_UNKNOWN = "unknown"

PHASE_CLIMB = "climbing"
PHASE_DESCEND = "descending"
PHASE_LEVEL = "level"

# Vertical rate below this is just turbulence, not a real climb or descent.
VS_DEADBAND_FPM = 250

# Within this range of one of your airports, a climb or descent is good enough
# evidence of a departure or an arrival when no route data is available.
TERMINAL_RANGE_NM = 45.0

KIND_COLOURS = {
    KIND_ARRIVAL: "FF6FD46F",
    KIND_DEPARTURE: "FFFFC24B",
    KIND_OVERFLIGHT: "FF7FB8FF",
    KIND_UNKNOWN: "FFBFC6D1",
}

# ADS-B emitter categories that are not airline traffic: A1 light, A2 small,
# A7 rotorcraft, and the whole B and C range (gliders, balloons, parachutists,
# UAVs, ground vehicles and obstructions).
EXCLUDED_CATEGORIES = frozenset((
    "A1", "A2", "A7",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
    "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7",
))

SLOT_ARRIVAL = "arrival"
SLOT_DEPARTURE = "departure"
SLOT_OVERFLIGHT = "overflight"

# Nouns, so the slot label never reads the same as the status beside it
# ("DEPARTURE / TAKING OFF" rather than "DEPARTING / DEPARTING").
SLOT_HEADINGS = {
    SLOT_ARRIVAL: "ARRIVAL",
    SLOT_DEPARTURE: "DEPARTURE",
    SLOT_OVERFLIGHT: "OVERFLIGHT",
}


def board_status(flight):
    """The word a departure board would show, in its own register.

    Driven by range to the runway rather than range to you, because that is
    what decides whether an aircraft is on final or still inbound.
    """
    distance = flight.airport_dist_nm
    altitude = flight.alt_ft or 0

    if flight.kind == KIND_ARRIVAL:
        if distance is not None:
            if distance <= 6 or altitude <= 2000:
                return "LANDING"
            if distance <= 20:
                return "ON FINAL"
            if distance <= 60:
                return "APPROACHING"
        return "INBOUND"

    if flight.kind == KIND_DEPARTURE:
        if distance is not None:
            if distance <= 8 and altitude <= 6000:
                return "TAKING OFF"
            if distance <= 30:
                return "CLIMBING OUT"
        return "OUTBOUND"

    if flight.elevation_deg is not None and flight.elevation_deg >= 55:
        return "OVERHEAD"
    return "PASSING"


def _num(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Flight(object):
    __slots__ = (
        "hex", "callsign", "registration", "type_code", "type_desc", "squawk", "category",
        "lat", "lon", "alt_ft", "on_ground", "gs_kt", "track_deg", "vs_fpm", "seen",
        "distance_nm", "bearing_deg", "elevation_deg", "relative_bearing", "in_view",
        "route", "aircraft_info", "kind", "phase", "airport_icao", "airport_dist_nm", "eta_min",
    )

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, None)
        self.on_ground = False
        self.in_view = False
        self.kind = KIND_UNKNOWN
        self.phase = PHASE_LEVEL

    # ---------------------------------------------------------------- parsing
    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            return None
        lat = _num(raw.get("lat"))
        lon = _num(raw.get("lon"))
        if lat is None or lon is None:
            return None

        f = cls()
        f.hex = (raw.get("hex") or "").strip().lower()
        f.callsign = (raw.get("flight") or "").strip().upper()
        f.registration = (raw.get("r") or "").strip().upper()
        f.type_code = (raw.get("t") or "").strip().upper()
        f.type_desc = (raw.get("desc") or "").strip()
        f.squawk = (raw.get("squawk") or "").strip()
        f.category = (raw.get("category") or "").strip().upper()
        f.lat = lat
        f.lon = lon

        alt = raw.get("alt_baro")
        if isinstance(alt, str) and alt.strip().lower() == "ground":
            f.on_ground = True
            f.alt_ft = 0.0
        else:
            f.alt_ft = _num(alt)
            if f.alt_ft is None:
                f.alt_ft = _num(raw.get("alt_geom"))
            f.on_ground = bool(f.alt_ft is not None and f.alt_ft <= 0)

        f.gs_kt = _num(raw.get("gs"))
        track = _num(raw.get("track"))
        if track is None:
            track = _num(raw.get("true_heading"))
        if track is None:
            track = _num(raw.get("mag_heading"))
        f.track_deg = track

        vs = _num(raw.get("baro_rate"))
        if vs is None:
            vs = _num(raw.get("geom_rate"))
        f.vs_fpm = vs

        f.seen = _num(raw.get("seen"))
        return f

    # ---------------------------------------------------------------- derived
    def compute_geometry(self, cfg):
        self.distance_nm = geo.haversine_nm(cfg.home_lat, cfg.home_lon, self.lat, self.lon)
        self.bearing_deg = geo.bearing_deg(cfg.home_lat, cfg.home_lon, self.lat, self.lon)
        self.elevation_deg = geo.elevation_angle_deg(
            self.distance_nm, self.alt_ft or 0.0, cfg.observer_alt_m)
        self.relative_bearing = geo.relative_bearing(self.bearing_deg, cfg.view_bearing)
        self.in_view = (
            geo.is_in_view(self.bearing_deg, cfg.view_bearing, cfg.view_fov)
            and self.elevation_deg > 0.3
        )

        if self.vs_fpm is None:
            self.phase = PHASE_LEVEL
        elif self.vs_fpm > VS_DEADBAND_FPM:
            self.phase = PHASE_CLIMB
        elif self.vs_fpm < -VS_DEADBAND_FPM:
            self.phase = PHASE_DESCEND
        else:
            self.phase = PHASE_LEVEL

    def compute_airport(self, my_airports, book):
        """Distance to whichever of your reference airports is nearest."""
        best = None
        for icao in my_airports:
            pos = book.position(icao)
            if not pos:
                continue
            d = geo.haversine_nm(self.lat, self.lon, pos[0], pos[1])
            if best is None or d < best[1]:
                best = (icao, d)
        if best:
            self.airport_icao, self.airport_dist_nm = best
        else:
            self.airport_icao, self.airport_dist_nm = None, None

    def classify(self, my_airports):
        route = self.route
        if route:
            dest = (route.dest_icao or "").upper()
            origin = (route.origin_icao or "").upper()
            if dest and dest in my_airports:
                self.kind = KIND_ARRIVAL
            elif origin and origin in my_airports:
                self.kind = KIND_DEPARTURE
            elif dest or origin:
                self.kind = KIND_OVERFLIGHT
            else:
                self.kind = KIND_UNKNOWN
        elif self.airport_dist_nm is not None and self.airport_dist_nm < TERMINAL_RANGE_NM:
            # No route data, but close to your airport and clearly going up or down.
            if self.phase == PHASE_DESCEND:
                self.kind = KIND_ARRIVAL
            elif self.phase == PHASE_CLIMB:
                self.kind = KIND_DEPARTURE
            else:
                self.kind = KIND_UNKNOWN
        else:
            self.kind = KIND_UNKNOWN

        if (self.kind == KIND_ARRIVAL and self.airport_dist_nm is not None
                and self.gs_kt and self.gs_kt > 60):
            self.eta_min = (self.airport_dist_nm / self.gs_kt) * 60.0
        else:
            self.eta_min = None

    # ---------------------------------------------------------------- labels
    @property
    def display_callsign(self):
        return self.callsign or self.registration or (self.hex or "").upper() or "?"

    @property
    def airline_name(self):
        if self.route and self.route.airline:
            return self.route.airline
        if self.aircraft_info and self.aircraft_info.get("owner"):
            return self.aircraft_info["owner"]
        return ""

    @property
    def aircraft_label(self):
        if self.type_desc:
            base = self.type_desc
        elif self.aircraft_info and self.aircraft_info.get("type"):
            base = self.aircraft_info["type"]
        elif self.type_code:
            base = self.type_code
        else:
            base = ""
        if self.registration and base:
            return "%s (%s)" % (base, self.registration)
        return base or self.registration or ""

    @property
    def colour(self):
        return KIND_COLOURS.get(self.kind, KIND_COLOURS[KIND_UNKNOWN])

    @property
    def is_airliner(self):
        """Whether this belongs on an arrivals board.

        Without it the board gets captured by whatever happens to be low and
        descending near the airport: police helicopters, survey aircraft and
        light singles all look exactly like an arrival to the geometry. A0 is
        "no category given", which plenty of real airliners report, so it has
        to count as a yes.
        """
        return self.category not in EXCLUDED_CATEGORIES


class Formatter(object):
    """Unit-aware number formatting, chosen once from the settings."""

    def __init__(self, units=config.UNITS_AVIATION):
        self.metric = (units == config.UNITS_METRIC)

    def distance(self, nm):
        if nm is None:
            return "-"
        if self.metric:
            km = nm * geo.KM_PER_NM
            return "%.1f km" % km if km < 100 else "%.0f km" % km
        return "%.1f nm" % nm if nm < 100 else "%.0f nm" % nm

    def altitude(self, ft, on_ground=False):
        if on_ground:
            return "ground"
        if ft is None:
            return "-"
        if self.metric:
            return "{:,} m".format(int(round(ft * geo.M_PER_FT)))
        return "{:,} ft".format(int(round(ft)))

    def speed(self, kt):
        if kt is None:
            return "-"
        if self.metric:
            return "%d km/h" % int(round(kt * geo.KMH_PER_KT))
        return "%d kt" % int(round(kt))

    def vertical(self, fpm):
        if fpm is None:
            return ""
        if abs(fpm) < VS_DEADBAND_FPM:
            return ""
        arrow = "+" if fpm > 0 else "-"
        if self.metric:
            return "%s%.1f m/s" % (arrow, abs(fpm) * geo.MS_PER_FPM)
        return "{}{:,} fpm".format(arrow, int(round(abs(fpm))))

    def elevation(self, deg):
        if deg is None:
            return "-"
        if deg < 0:
            return "below horizon"
        return "%d deg up" % int(round(deg))

    def eta(self, minutes):
        if minutes is None:
            return ""
        if minutes < 1:
            return "landing now"
        return "%d min out" % int(round(minutes))
