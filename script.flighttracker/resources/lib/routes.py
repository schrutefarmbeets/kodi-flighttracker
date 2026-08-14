"""Callsign -> airline and route lookups against adsbdb.com, with a disk cache.

A flight number's route barely changes, so a hit is cached for weeks and a miss
for a few days. In practice the airport you watch settles into a few hundred
callsigns and the lookups go almost completely quiet.

adsbdb can return the aircraft and the route together from one request, which is
the path taken whenever both are wanted. That call 404s if either half is
unknown, so a miss falls back to asking for the route on its own.
"""

import json
import os
import socket
import time

from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .airports import AirportBook

API_BASE = "https://api.adsbdb.com/v0"
USER_AGENT = "Kodi-FlightTracker/1.0"
TIMEOUT = 8
CACHE_VERSION = 1

MISS_TTL_DAYS = 3


def normalise_callsign(callsign):
    return (callsign or "").strip().upper()


def normalise_hex(mode_s):
    return (mode_s or "").strip().lower()


class Route(object):
    __slots__ = ("callsign", "callsign_iata", "airline", "airline_iata",
                 "origin_icao", "origin_iata", "origin_city", "origin_name", "origin_country",
                 "dest_icao", "dest_iata", "dest_city", "dest_name", "dest_country")

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name, ""))

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__slots__}

    @classmethod
    def from_dict(cls, data):
        return cls(**(data or {}))

    @property
    def pair(self):
        """Short "BKK - HKG" style label, using IATA where available."""
        a = self.origin_iata or self.origin_icao
        b = self.dest_iata or self.dest_icao
        if a and b:
            return "%s - %s" % (a, b)
        return a or b or ""


class RouteStore(object):
    def __init__(self, cache_path, ttl_days=30, logger=None):
        self.cache_path = cache_path
        self.ttl = max(1, int(ttl_days)) * 86400
        self.miss_ttl = MISS_TTL_DAYS * 86400
        self._routes = {}
        self._aircraft = {}
        self._dirty = False
        self._log = logger or (lambda msg: None)
        self.airports = AirportBook()
        self.requests = 0
        self._load()

    # ---------------------------------------------------------------- disk
    def _load(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (IOError, OSError, ValueError):
            return
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            return
        self._routes = data.get("routes") or {}
        self._aircraft = data.get("aircraft") or {}
        for icao, entry in (data.get("airports") or {}).items():
            try:
                self.airports.learn(icao, entry.get("iata"), entry.get("name"),
                                    entry.get("city"), entry.get("lat"), entry.get("lon"))
            except (TypeError, ValueError):
                continue

    def save(self):
        if not self._dirty:
            return
        payload = {
            "version": CACHE_VERSION,
            "routes": self._routes,
            "aircraft": self._aircraft,
            "airports": self.airports.export_learned(),
        }
        try:
            directory = os.path.dirname(self.cache_path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self.cache_path)
            self._dirty = False
        except (IOError, OSError) as exc:
            self._log("could not write route cache: %s" % exc)

    def prune(self):
        now = time.time()
        for bucket in (self._routes, self._aircraft):
            stale = [key for key, entry in bucket.items()
                     if now - entry.get("t", 0) > (self.ttl if entry.get("ok") else self.miss_ttl)]
            for key in stale:
                bucket.pop(key, None)
                self._dirty = True

    # ---------------------------------------------------------------- http
    def _get(self, url):
        self.requests += 1
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            resp = urlopen(req, timeout=TIMEOUT)
        except HTTPError as exc:
            if exc.code == 404:
                return None, "notfound"
            if exc.code == 429:
                return None, "ratelimited"
            return None, "http%s" % exc.code
        except (URLError, socket.timeout):
            return None, "unreachable"
        except Exception:  # pragma: no cover - defensive
            return None, "error"
        try:
            raw = resp.read()
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            return json.loads(raw.decode("utf-8", "replace")), None
        except ValueError:
            return None, "badjson"

    # ---------------------------------------------------------------- cache reads
    def cached(self, callsign):
        """Return (Route|None, known) where known means "do not ask again yet"."""
        key = normalise_callsign(callsign)
        if not key:
            return None, True
        return self._read(self._routes, key, Route.from_dict)

    def cached_aircraft(self, mode_s):
        key = normalise_hex(mode_s)
        if not key:
            return None, True
        return self._read(self._aircraft, key, lambda d: d or {})

    def _read(self, bucket, key, build):
        entry = bucket.get(key)
        if not entry:
            return None, False
        ttl = self.ttl if entry.get("ok") else self.miss_ttl
        if time.time() - entry.get("t", 0) > ttl:
            return None, False
        if not entry.get("ok"):
            return None, True
        return build(entry.get("d")), True

    # ---------------------------------------------------------------- cache writes
    def _remember_miss(self, bucket, key):
        bucket[key] = {"t": time.time(), "ok": False}
        self._dirty = True

    def _store_route(self, key, flightroute):
        airline = flightroute.get("airline") or {}
        origin = flightroute.get("origin") or {}
        dest = flightroute.get("destination") or {}

        route = Route(
            callsign=key,
            callsign_iata=flightroute.get("callsign_iata") or "",
            airline=airline.get("name") or "",
            airline_iata=airline.get("iata") or "",
            origin_icao=origin.get("icao_code") or "",
            origin_iata=origin.get("iata_code") or "",
            origin_city=origin.get("municipality") or "",
            origin_name=origin.get("name") or "",
            origin_country=origin.get("country_name") or "",
            dest_icao=dest.get("icao_code") or "",
            dest_iata=dest.get("iata_code") or "",
            dest_city=dest.get("municipality") or "",
            dest_name=dest.get("name") or "",
            dest_country=dest.get("country_name") or "",
        )
        for airport in (origin, dest):
            self.airports.learn(
                airport.get("icao_code"), airport.get("iata_code"),
                airport.get("name"), airport.get("municipality"),
                airport.get("latitude"), airport.get("longitude"))

        self._routes[key] = {"t": time.time(), "ok": True, "d": route.to_dict()}
        self._dirty = True
        return route

    def _store_aircraft(self, key, aircraft):
        data = {
            "type": aircraft.get("type") or "",
            "icao_type": aircraft.get("icao_type") or "",
            "manufacturer": aircraft.get("manufacturer") or "",
            "registration": aircraft.get("registration") or "",
            "owner": aircraft.get("registered_owner") or "",
            "owner_country": aircraft.get("registered_owner_country_name") or "",
        }
        self._aircraft[key] = {"t": time.time(), "ok": True, "d": data}
        self._dirty = True
        return data

    # ---------------------------------------------------------------- network
    def fetch(self, callsign):
        """Look up just the route for a callsign."""
        key = normalise_callsign(callsign)
        if not key:
            return None
        payload, error = self._get("%s/callsign/%s" % (API_BASE, quote(key)))
        if error == "notfound":
            self._remember_miss(self._routes, key)
            return None
        if error:
            return None  # transient: do not poison the cache
        try:
            return self._store_route(key, payload["response"]["flightroute"])
        except (KeyError, TypeError):
            self._remember_miss(self._routes, key)
            return None

    def fetch_aircraft(self, mode_s):
        """Look up just the airframe for a Mode-S hex."""
        key = normalise_hex(mode_s)
        if not key:
            return None
        payload, error = self._get("%s/aircraft/%s" % (API_BASE, quote(key)))
        if error == "notfound":
            self._remember_miss(self._aircraft, key)
            return None
        if error:
            return None
        try:
            return self._store_aircraft(key, payload["response"]["aircraft"])
        except (KeyError, TypeError):
            self._remember_miss(self._aircraft, key)
            return None

    def fetch_pair(self, mode_s, callsign):
        """Route and airframe in one request where the database has both.

        Returns (route, aircraft), either of which may be None. adsbdb answers
        404 when either half is missing, so that case retries the route on its
        own, which is the half worth spending a second request on.
        """
        key_hex = normalise_hex(mode_s)
        key_cs = normalise_callsign(callsign)
        if not key_hex or not key_cs:
            return (self.fetch(key_cs) if key_cs else None,
                    self.fetch_aircraft(key_hex) if key_hex else None)

        payload, error = self._get(
            "%s/aircraft/%s?callsign=%s" % (API_BASE, quote(key_hex), quote(key_cs)))

        if not error:
            response = (payload or {}).get("response") or {}
            aircraft = response.get("aircraft")
            flightroute = response.get("flightroute")
            route = self._store_route(key_cs, flightroute) if flightroute else None
            info = self._store_aircraft(key_hex, aircraft) if aircraft else None
            if route is not None or info is not None:
                return route, info

        if error == "unreachable":
            return None, None

        # Either half was missing. The route is the one worth another request.
        return self.fetch(key_cs), None
