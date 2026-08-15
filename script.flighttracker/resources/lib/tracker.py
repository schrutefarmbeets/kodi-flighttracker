"""Ties the feed, the geometry and the route lookups into one poll() call."""

import time

from . import config, feeds
from .model import (Flight, KIND_ARRIVAL, KIND_DEPARTURE, KIND_OVERFLIGHT,
                    KIND_UNKNOWN, SLOT_ARRIVAL, SLOT_DEPARTURE, SLOT_OVERFLIGHT)
from .routes import RouteStore, normalise_callsign

# Lookups only happen for aircraft that survived filtering, nearest first, and
# are capped per cycle by actual HTTP requests rather than by aircraft, because
# one aircraft can cost a second request when the combined call misses. The disk
# cache makes this a non-event after the first few minutes of watching.
MAX_REQUESTS_PER_CYCLE = 10
# Airframe details are a nice-to-have, so only the closest few are worth a
# request of their own once the route is already known.
AIRCRAFT_ONLY_DEPTH = 6
LOOKUP_PAUSE = 0.05


class PollResult(object):
    def __init__(self, flights, error=None, total_seen=0, hidden=0):
        self.flights = flights
        self.error = error
        self.total_seen = total_seen
        self.hidden = hidden
        self.timestamp = time.time()


class Tracker(object):
    def __init__(self, cfg, cache_path, logger=None):
        self.cfg = cfg
        self.log = logger or (lambda msg: None)
        self.store = RouteStore(cache_path, cfg.route_cache_days, logger)
        self.store.prune()

    def update_config(self, cfg):
        self.cfg = cfg

    # ---------------------------------------------------------------- polling
    def poll(self):
        cfg = self.cfg
        try:
            raw_list = feeds.fetch(cfg)
        except feeds.FeedError as exc:
            self.log("feed error: %s" % exc)
            return PollResult([], error=str(exc))

        flights = []
        for raw in raw_list:
            flight = Flight.from_raw(raw)
            if flight is not None:
                flights.append(flight)
        total_seen = len(flights)

        for flight in flights:
            flight.compute_geometry(cfg)

        kept = [f for f in flights if self._passes_basic_filters(f)]
        kept.sort(key=lambda f: f.distance_nm)
        kept = kept[:max(1, int(cfg.max_flights))]

        if cfg.lookup_routes:
            self._attach_routes(kept)
        else:
            self._fill_from_cache(kept)

        my_airports = cfg.my_airports
        for flight in kept:
            flight.compute_airport(my_airports, self.store.airports)
            flight.classify(my_airports)

        kept = [f for f in kept if self._passes_traffic_filter(f)]

        self._sort(kept)
        self.store.save()

        hidden = total_seen - len(kept)
        return PollResult(kept, total_seen=total_seen, hidden=max(0, hidden))

    # ---------------------------------------------------------------- filters
    def _passes_basic_filters(self, flight):
        cfg = self.cfg
        if flight.distance_nm > cfg.radius_nm:
            return False
        if cfg.hide_ground and flight.on_ground:
            return False
        alt = flight.alt_ft
        if alt is not None:
            if alt < cfg.min_alt_ft:
                return False
            if alt > cfg.max_alt_ft:
                return False
        if cfg.only_visible and not flight.in_view:
            return False
        return True

    def _passes_traffic_filter(self, flight):
        cfg = self.cfg
        # Nothing enabled would mean an empty screen, which is never what
        # someone wants; treat that as "show me everything".
        if not (cfg.show_arrivals or cfg.show_departures or cfg.show_overflights):
            return True
        if flight.kind == KIND_ARRIVAL:
            return cfg.show_arrivals
        if flight.kind == KIND_DEPARTURE:
            return cfg.show_departures
        # Anything that is not using one of your airports is an overflight,
        # including aircraft whose route could not be resolved.
        return cfg.show_overflights

    def _sort(self, flights):
        flights.sort(key=lambda f: f.distance_nm)

    # ---------------------------------------------------------------- now
    def select_now(self, flights):
        """The runway queue: what is landing or taking off at this moment.

        One list ranked by track miles from the runway, so an airliner that has
        just rotated can sit above one still on approach, while one that is
        close to the field but far too high to be landing does not displace
        either. Anything beyond the approach range is left off entirely rather
        than shown with some softer wording, which keeps every row on the board
        genuinely a landing or a take-off.
        """
        cfg = self.cfg
        limit = max(1, int(cfg.board_rows))
        reach = float(cfg.approach_range_nm)

        queue = []
        for flight in flights:
            if not flight.is_airliner:
                continue
            if flight.kind == KIND_ARRIVAL and cfg.show_arrivals:
                slot = SLOT_ARRIVAL
            elif flight.kind == KIND_DEPARTURE and cfg.show_departures:
                slot = SLOT_DEPARTURE
            else:
                continue
            track = flight.runway_track_nm
            if track is None or track > reach:
                continue
            queue.append((track, slot, flight))

        queue.sort(key=lambda item: item[0])
        rows = [(slot, flight) for _, slot, flight in queue[:limit]]

        # Overflights are not runway traffic, so they only ever fill a row the
        # airport itself has left empty.
        if cfg.show_overflights and len(rows) < limit:
            pick = self._nearest_to_home(flights, (KIND_OVERFLIGHT, KIND_UNKNOWN))
            if pick is not None:
                rows.append((SLOT_OVERFLIGHT, pick))
        return rows

    def select_slots(self, flights):
        """The same runway queue, split in two and left unranked against itself.

        The board view holds one arrival and one departure side by side, so
        each side needs its own ordering. Nearest the runway first, which is
        the order they will actually land or leave in.
        """
        cfg = self.cfg
        reach = float(cfg.approach_range_nm)
        queues = {SLOT_ARRIVAL: [], SLOT_DEPARTURE: []}

        for flight in flights:
            if not flight.is_airliner or not flight.hex:
                continue
            if flight.kind == KIND_ARRIVAL and cfg.show_arrivals:
                slot = SLOT_ARRIVAL
            elif flight.kind == KIND_DEPARTURE and cfg.show_departures:
                slot = SLOT_DEPARTURE
            else:
                continue
            track = flight.runway_track_nm
            if track is None or track > reach:
                continue
            queues[slot].append((track, flight))

        return dict((slot, [flight for _, flight in sorted(bucket, key=lambda i: i[0])])
                    for slot, bucket in queues.items())

    @staticmethod
    def _nearest_to_home(flights, kinds):
        best = None
        for flight in flights:
            if flight.kind not in kinds or not flight.is_airliner:
                continue
            if best is None or flight.distance_nm < best.distance_nm:
                best = flight
        return best

    # ---------------------------------------------------------------- lookups
    def _fill_from_cache(self, flights):
        """Attach whatever is already known, and report what is still missing."""
        pending = []
        for index, flight in enumerate(flights):
            callsign = normalise_callsign(flight.callsign)
            route, route_known = (None, True)
            if callsign:
                route, route_known = self.store.cached(callsign)
            flight.route = route

            info, info_known = self.store.cached_aircraft(flight.hex)
            flight.aircraft_info = info

            need_route = bool(callsign) and route is None and not route_known
            need_info = bool(flight.hex) and info is None and not info_known
            if need_route or need_info:
                pending.append((index, flight, need_route, need_info))
        return pending

    def _attach_routes(self, flights):
        pending = self._fill_from_cache(flights)
        spent_at_start = self.store.requests

        for index, flight, need_route, need_info in pending:
            remaining = MAX_REQUESTS_PER_CYCLE - (self.store.requests - spent_at_start)
            if remaining <= 0:
                break

            # A combined lookup can cost a second request when it misses, so it
            # is only started with room for both. With one request left the
            # route wins, being the half worth having.
            if need_route and need_info and remaining >= 2:
                route, info = self.store.fetch_pair(flight.hex, flight.callsign)
                if route is not None:
                    flight.route = route
                if info is not None:
                    flight.aircraft_info = info
            elif need_route:
                flight.route = self.store.fetch(flight.callsign)
            elif need_info:
                if index >= AIRCRAFT_ONLY_DEPTH:
                    continue
                flight.aircraft_info = self.store.fetch_aircraft(flight.hex)

            time.sleep(LOOKUP_PAUSE)

    # ---------------------------------------------------------------- shutdown
    def close(self):
        try:
            self.store.save()
        except Exception:
            pass
