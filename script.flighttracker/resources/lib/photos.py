"""Photographs of the actual airframe, by registration, cached on disk.

Planespotters' public API, which needs no key but does need a contact URL in
the User-Agent: without one it answers with an error instead of photographs.
Every response names the photographer, and that name is kept and shown. It is
the price of the picture.

Lookups run on a background thread. The alternative is an HTTP request in the
middle of drawing a card, which stalls the whole board for as long as the
timeout when a new aircraft appears. Nothing waits for a photograph here: the
card draws without one and picks it up on a later poll.
"""

import json
import os
import threading

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# The contact URL is not decoration. Planespotters rejects a User-Agent without
# one, and it is how they reach whoever is making the requests.
USER_AGENT = ("Kodi-FlightTracker/1.0 "
              "(+https://github.com/schrutefarmbeets/kodi-flighttracker)")
API = "https://api.planespotters.net/pub/photos/reg/%s"
TIMEOUT = 10

JPEG_MAGIC = b"\xff\xd8\xff"
MIN_BYTES = 900

# The API tops out here. Stretched much past its own size the picture turns to
# mush, so the card is laid out around this rather than the other way round.
NATIVE_W = 420
NATIVE_H = 280


class PhotoStore(object):
    def __init__(self, directory, logger=None):
        self.directory = directory
        self._log = logger or (lambda msg: None)
        self._missing = set()
        self._inflight = set()
        self._lock = threading.Lock()
        try:
            if not os.path.isdir(directory):
                os.makedirs(directory)
        except OSError as exc:
            self._log("could not create photo cache: %s" % exc)

    @staticmethod
    def _clean(registration):
        code = (registration or "").strip().upper()
        if not code or len(code) > 12:
            return ""
        # Registrations are letters, digits and hyphens. Anything else is not
        # one, and has no business being pasted into a URL.
        if not all(char.isalnum() or char == "-" for char in code):
            return ""
        return code

    def path_for(self, registration):
        return os.path.join(self.directory, "%s.jpg" % registration)

    def _credit_path(self, registration):
        return os.path.join(self.directory, "%s.txt" % registration)

    def cached(self, registration):
        """The photograph if we already have it, without touching the network."""
        code = self._clean(registration)
        if not code:
            return None, ""
        path = self.path_for(code)
        if not os.path.exists(path):
            return None, ""
        credit = ""
        try:
            with open(self._credit_path(code), "r", encoding="utf-8") as handle:
                credit = handle.read().strip()
        except (OSError, UnicodeDecodeError):
            pass
        return path, credit

    def pending(self):
        """How many fetches are still in the air, for callers that can wait."""
        with self._lock:
            return len(self._inflight)

    def request(self, registration):
        """Start a fetch if this is the first time we have seen the aircraft."""
        code = self._clean(registration)
        if not code or code in self._missing:
            return
        if os.path.exists(self.path_for(code)):
            return
        with self._lock:
            if code in self._inflight:
                return
            self._inflight.add(code)
        thread = threading.Thread(target=self._fetch, args=(code,),
                                  name="flighttracker-photo")
        thread.daemon = True
        thread.start()

    # ---------------------------------------------------------------- network
    def _fetch(self, code):
        try:
            entry = self._lookup(code)
            if entry is None:
                self._missing.add(code)
                return
            url, credit = entry
            data = self._download(url, JPEG_MAGIC)
            if data is None:
                self._missing.add(code)
                return
            self._store(code, data, credit)
        except Exception as exc:  # pragma: no cover - defensive
            self._log("photo fetch failed for %s: %s" % (code, exc))
        finally:
            with self._lock:
                self._inflight.discard(code)

    def _lookup(self, code):
        raw = self._download(API % code, None)
        if raw is None:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        photos = payload.get("photos") or []
        if not photos:
            return None
        first = photos[0] or {}
        thumb = first.get("thumbnail_large") or first.get("thumbnail") or {}
        url = (thumb or {}).get("src")
        if not url:
            return None
        return url, (first.get("photographer") or "").strip()

    def _download(self, url, magic):
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            response = urlopen(request, timeout=TIMEOUT)
        except (HTTPError, URLError):
            return None
        except Exception:  # pragma: no cover - defensive
            return None
        try:
            data = response.read()
        except Exception:
            return None
        finally:
            try:
                response.close()
            except Exception:
                pass

        if magic is not None and (not data.startswith(magic) or len(data) < MIN_BYTES):
            return None
        return data

    def _store(self, code, data, credit):
        path = self.path_for(code)
        try:
            tmp = path + ".tmp"
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        except OSError as exc:
            self._log("could not write photo %s: %s" % (code, exc))
            return
        try:
            with open(self._credit_path(code), "w", encoding="utf-8") as handle:
                handle.write(credit)
        except OSError:
            pass
