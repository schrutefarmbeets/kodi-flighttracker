"""Airline logos by IATA code, cached on disk.

Two key-free CDNs, tried in order. A logo never changes, so once a file lands
in the cache it is used forever and the network is never touched again for that
airline.
"""

import hashlib
import os

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "Kodi-FlightTracker/1.0"
TIMEOUT = 8

WIDTH = 300
HEIGHT = 150

# Neither CDN 404s on an airline it does not have, so both need watching.
# avs.io goes first because its coverage is better and it is accurate for real
# IATA codes; daisycon has gaps and answers them with a placeholder graphic.
SOURCES = (
    "https://pics.avs.io/%(w)d/%(h)d/%(iata)s.png",
    "https://daisycon.io/images/airline/?width=%(w)d&height=%(h)d&iata=%(iata)s",
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_BYTES = 400

# One known daisycon placeholder. It is not the only one they serve, which is
# why the duplicate check below matters more than this list.
PLACEHOLDER_HASHES = {
    "28baf93d1ee0e1077358b20fce55f68d763763e15a7fd0c0c02409a99363ded5",
}


class LogoStore(object):
    def __init__(self, directory, logger=None):
        self.directory = directory
        self._log = logger or (lambda msg: None)
        self._missing = set()
        # digest -> the airline it was first seen for. Two different airlines
        # returning byte-identical images means it is a placeholder, whatever
        # it happens to look like.
        self._seen = {}
        try:
            if not os.path.isdir(directory):
                os.makedirs(directory)
        except OSError as exc:
            self._log("could not create logo cache: %s" % exc)

    def path_for(self, iata):
        return os.path.join(self.directory, "%s.png" % iata)

    @staticmethod
    def _clean(iata):
        code = (iata or "").strip().upper()
        if not code or len(code) > 3 or not code.isalnum():
            return ""
        return code

    def cached(self, iata):
        code = self._clean(iata)
        if not code:
            return None
        path = self.path_for(code)
        return path if os.path.exists(path) else None

    def get(self, iata, allow_fetch=True):
        """Local path to the logo, fetching it once if we have never seen it."""
        code = self._clean(iata)
        if not code:
            return None
        path = self.path_for(code)
        if os.path.exists(path):
            return path
        if not allow_fetch or code in self._missing:
            return None
        return self._fetch(code, path)

    def _fetch(self, code, path):
        for template in SOURCES:
            url = template % {"w": WIDTH, "h": HEIGHT, "iata": code}
            data = self._download(url)
            if data is None:
                continue

            digest = hashlib.sha256(data).hexdigest()
            owner = self._seen.get(digest)
            if owner is not None and owner != code:
                self._log("%s returned the same image as %s, treating as a placeholder"
                          % (code, owner))
                continue
            self._seen[digest] = code

            try:
                tmp = path + ".tmp"
                with open(tmp, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, path)
                return path
            except OSError as exc:
                self._log("could not write logo %s: %s" % (code, exc))
                return None
        self._missing.add(code)
        return None

    def _download(self, url):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/png"})
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

        if not data.startswith(PNG_MAGIC) or len(data) < MIN_BYTES:
            return None
        if hashlib.sha256(data).hexdigest() in PLACEHOLDER_HASHES:
            return None
        return data
