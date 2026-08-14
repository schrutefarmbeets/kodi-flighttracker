"""Geometry for turning ADS-B positions into "look out of the window" numbers.

No Kodi imports here on purpose, so this module can be exercised with plain
Python from tools/selftest.py.
"""

import math

NM_PER_KM = 0.5399568034557235
KM_PER_NM = 1.852
M_PER_FT = 0.3048
FT_PER_M = 3.280839895013123
KMH_PER_KT = 1.852
MS_PER_FPM = 0.00508

EARTH_RADIUS_NM = 3440.065

# Standard refraction makes the earth behave as if it were about 4/3 its real
# size, which is the usual correction for line-of-sight problems like this one.
EFFECTIVE_EARTH_RADIUS_M = 6371008.8 * 4.0 / 3.0


def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial true bearing from point 1 to point 2, in degrees from north."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angular_difference(a, b):
    """Smallest absolute angle between two bearings, 0..180."""
    d = abs((a - b) % 360.0)
    return 360.0 - d if d > 180.0 else d


def elevation_angle_deg(distance_nm, alt_ft, observer_alt_m=0.0):
    """How high above the horizon the aircraft appears, in degrees.

    Includes the earth-curvature drop, which matters a lot at these ranges: a
    cruising aircraft 60 nm away sits far lower in the sky than flat geometry
    suggests, and can be below the horizon entirely.
    """
    ground_m = max(distance_nm, 0.0) * KM_PER_NM * 1000.0
    if ground_m < 1.0:
        return 90.0
    height_m = (alt_ft or 0.0) * M_PER_FT - (observer_alt_m or 0.0)
    drop_m = (ground_m ** 2) / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
    return math.degrees(math.atan2(height_m - drop_m, ground_m))


def relative_bearing(target_bearing, view_bearing):
    """Target bearing expressed relative to the way you are facing.

    Returns -180..180, where negative is to your left and positive to your right.
    """
    d = (target_bearing - view_bearing + 540.0) % 360.0 - 180.0
    return d


def is_in_view(target_bearing, view_bearing, fov_deg):
    if fov_deg >= 360:
        return True
    return angular_difference(target_bearing, view_bearing) <= (fov_deg / 2.0)


def compass_point(bearing):
    """16-point compass abbreviation for a bearing."""
    names = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return names[int((bearing % 360.0) / 22.5 + 0.5) % 16]


def project_to_radar(lat, lon, home_lat, home_lon, range_nm, radius_px, rotation_deg=0.0):
    """Map a lat/lon to x,y pixel offsets from the centre of the radar.

    Equirectangular around the home point, which is accurate enough over the
    couple of hundred miles a radar like this ever covers. Returns offsets in
    screen pixels where +x is right and +y is down, or None if the point falls
    outside the radar face.
    """
    if range_nm <= 0 or radius_px <= 0:
        return None
    mean_lat = math.radians((lat + home_lat) / 2.0)
    north_nm = (lat - home_lat) * 60.0
    east_nm = (lon - home_lon) * 60.0 * math.cos(mean_lat)

    if rotation_deg:
        r = math.radians(rotation_deg)
        cos_r = math.cos(r)
        sin_r = math.sin(r)
        rot_east = east_nm * cos_r - north_nm * sin_r
        rot_north = east_nm * sin_r + north_nm * cos_r
        east_nm, north_nm = rot_east, rot_north

    scale = float(radius_px) / float(range_nm)
    x = east_nm * scale
    y = -north_nm * scale
    if math.hypot(x, y) > radius_px:
        return None
    return x, y


def ring_radius_px(fraction, radius_px):
    return fraction * radius_px
