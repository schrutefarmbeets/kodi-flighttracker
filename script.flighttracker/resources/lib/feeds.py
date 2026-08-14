"""ADS-B position feeds.

All three supported sources speak the readsb/tar1090 JSON dialect, so they only
differ in the URL and in which key holds the aircraft array.
"""

import gzip
import json
import socket

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config

USER_AGENT = "Kodi-FlightTracker/1.0"
TIMEOUT = 12

ADSBLOL_MAX_RADIUS_NM = 250
ADSBFI_MAX_RADIUS_NM = 250


class FeedError(Exception):
    pass


def _get_json(url, timeout=TIMEOUT):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    })
    try:
        resp = urlopen(req, timeout=timeout)
    except HTTPError as exc:
        raise FeedError("HTTP %s from %s" % (exc.code, url))
    except URLError as exc:
        raise FeedError("%s (%s)" % (exc.reason, url))
    except socket.timeout:
        raise FeedError("timed out contacting %s" % url)
    except Exception as exc:  # pragma: no cover - defensive
        raise FeedError("%s (%s)" % (exc, url))

    try:
        raw = resp.read()
        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
    finally:
        try:
            resp.close()
        except Exception:
            pass

    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise FeedError("bad JSON from %s: %s" % (url, exc))


def _aircraft_array(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("ac", "aircraft"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalise_base(url):
    return (url or "").strip().rstrip("/")


def fetch(cfg):
    """Return the raw aircraft dicts visible to the configured source."""
    lat = float(cfg.home_lat)
    lon = float(cfg.home_lon)

    if cfg.source == config.SOURCE_ADSBFI:
        radius = max(1, min(int(cfg.radius_nm), ADSBFI_MAX_RADIUS_NM))
        url = "https://opendata.adsb.fi/api/v2/lat/%.5f/lon/%.5f/dist/%d" % (lat, lon, radius)
        return _aircraft_array(_get_json(url))

    if cfg.source == config.SOURCE_LOCAL:
        base = _normalise_base(cfg.local_url)
        if not base:
            raise FeedError("no local receiver URL configured")
        last_error = None
        for path in ("/data/aircraft.json", "/tar1090/data/aircraft.json", "/dump1090-fa/data/aircraft.json"):
            try:
                return _aircraft_array(_get_json(base + path, timeout=6))
            except FeedError as exc:
                last_error = exc
        raise last_error or FeedError("local receiver did not answer")

    radius = max(1, min(int(cfg.radius_nm), ADSBLOL_MAX_RADIUS_NM))
    url = "https://api.adsb.lol/v2/point/%.5f/%.5f/%d" % (lat, lon, radius)
    return _aircraft_array(_get_json(url))


def source_name(source):
    return {
        config.SOURCE_ADSBLOL: "adsb.lol",
        config.SOURCE_ADSBFI: "adsb.fi",
        config.SOURCE_LOCAL: "local receiver",
    }.get(source, "unknown")
