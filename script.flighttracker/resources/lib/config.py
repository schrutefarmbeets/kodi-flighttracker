"""Settings, as a plain object so the rest of the code never touches xbmcaddon."""

SOURCE_ADSBLOL = 0
SOURCE_ADSBFI = 1
SOURCE_LOCAL = 2

VIEW_BOARD = 0
VIEW_RADAR = 1
VIEW_MAP = 2

UNITS_AVIATION = 0
UNITS_METRIC = 1


class Config(object):
    """Snapshot of the addon settings."""

    def __init__(self, **kw):
        self.home_lat = 13.7280
        self.home_lon = 100.5820
        self.observer_alt_m = 110
        self.view_bearing = 110
        self.view_fov = 140
        self.only_visible = False
        self.orient_radar = True

        self.source = SOURCE_ADSBLOL
        self.local_url = "http://127.0.0.1:8080"
        self.radius_nm = 60
        self.refresh_sec = 8
        self.max_flights = 40

        self.airport_primary = "VTBS"
        # Empty on purpose. A second airport only belongs here if you can
        # actually see it from the window; otherwise its traffic takes board
        # slots away from the airport you are watching.
        self.airport_secondary = ""

        self.lookup_routes = True
        self.route_cache_days = 30

        self.min_alt_ft = 0
        self.max_alt_ft = 45000
        self.hide_ground = True

        # What the board is allowed to show, each independently.
        self.show_arrivals = True
        self.show_departures = True
        self.show_overflights = False

        # The board is the runway queue: this many aircraft, and only those
        # already this close to the runway, so everything on it is genuinely
        # landing or taking off rather than merely heading this way.
        self.board_rows = 3
        self.approach_range_nm = 15

        self.view_mode = VIEW_BOARD
        self.show_logos = True
        self.flap_animation = True
        self.units = UNITS_AVIATION
        self.radar_labels = True

        self.notify_enabled = False
        self.notify_dist_nm = 8
        self.notify_alt_ft = 12000
        self.notify_cooldown_sec = 120

        for key, value in kw.items():
            if not hasattr(self, key):
                raise AttributeError("unknown setting %r" % (key,))
            setattr(self, key, value)

    @property
    def my_airports(self):
        out = []
        for code in (self.airport_primary, self.airport_secondary):
            code = (code or "").strip().upper()
            if code:
                out.append(code)
        return out

    def location_is_set(self):
        return abs(self.home_lat) > 0.0001 or abs(self.home_lon) > 0.0001


def _to_float(text, fallback):
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return fallback


def from_addon(addon):
    """Build a Config from a live xbmcaddon.Addon instance."""
    cfg = Config()

    def s(key, default=""):
        try:
            return addon.getSetting(key) or default
        except Exception:
            return default

    def i(key, default):
        try:
            return int(addon.getSettingInt(key))
        except Exception:
            return default

    def b(key, default):
        try:
            return bool(addon.getSettingBool(key))
        except Exception:
            return default

    cfg.home_lat = _to_float(s("home_lat"), cfg.home_lat)
    cfg.home_lon = _to_float(s("home_lon"), cfg.home_lon)
    cfg.observer_alt_m = i("observer_alt_m", cfg.observer_alt_m)
    cfg.view_bearing = i("view_bearing", cfg.view_bearing)
    cfg.view_fov = i("view_fov", cfg.view_fov)
    cfg.only_visible = b("only_visible", cfg.only_visible)
    cfg.orient_radar = b("orient_radar", cfg.orient_radar)

    cfg.source = i("source", cfg.source)
    cfg.local_url = s("local_url", cfg.local_url)
    cfg.radius_nm = i("radius_nm", cfg.radius_nm)
    cfg.refresh_sec = i("refresh_sec", cfg.refresh_sec)
    cfg.max_flights = i("max_flights", cfg.max_flights)

    cfg.airport_primary = s("airport_primary", cfg.airport_primary)
    cfg.airport_secondary = s("airport_secondary", cfg.airport_secondary)

    cfg.lookup_routes = b("lookup_routes", cfg.lookup_routes)
    cfg.route_cache_days = i("route_cache_days", cfg.route_cache_days)

    cfg.min_alt_ft = i("min_alt_ft", cfg.min_alt_ft)
    cfg.max_alt_ft = i("max_alt_ft", cfg.max_alt_ft)
    cfg.hide_ground = b("hide_ground", cfg.hide_ground)

    cfg.show_arrivals = b("show_arrivals", cfg.show_arrivals)
    cfg.show_departures = b("show_departures", cfg.show_departures)
    cfg.show_overflights = b("show_overflights", cfg.show_overflights)
    cfg.board_rows = i("board_rows", cfg.board_rows)
    cfg.approach_range_nm = i("approach_range_nm", cfg.approach_range_nm)

    cfg.view_mode = i("view_mode", cfg.view_mode)
    cfg.show_logos = b("show_logos", cfg.show_logos)
    cfg.flap_animation = b("flap_animation", cfg.flap_animation)
    cfg.units = i("units", cfg.units)
    cfg.radar_labels = b("radar_labels", cfg.radar_labels)

    cfg.notify_enabled = b("notify_enabled", cfg.notify_enabled)
    cfg.notify_dist_nm = i("notify_dist_nm", cfg.notify_dist_nm)
    cfg.notify_alt_ft = i("notify_alt_ft", cfg.notify_alt_ft)
    cfg.notify_cooldown_sec = i("notify_cooldown_sec", cfg.notify_cooldown_sec)

    return cfg
