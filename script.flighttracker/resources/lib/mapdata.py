"""Vector geography for the map view, shipped with the addon.

Deliberately coarse: at the ranges this display works over, a few dozen points
give a perfectly readable coastline, and it costs nothing to carry and needs no
network. Coordinates are decimal degrees.

Only the upper Gulf of Thailand is included, since that is what this was built
to look at. Anything outside the radar range simply does not get drawn, so
running it elsewhere shows an empty map rather than a wrong one. To cover
another area, add polylines here in the same format.
"""

# The Bight of Bangkok, west shore round to the Pattaya side.
_UPPER_GULF = [
    (13.20, 99.94), (13.32, 99.97), (13.43, 100.00), (13.50, 100.06),
    (13.52, 100.18), (13.53, 100.28), (13.54, 100.40), (13.545, 100.50),
    (13.55, 100.58), (13.53, 100.68), (13.51, 100.78), (13.50, 100.88),
    (13.44, 100.94), (13.36, 100.98), (13.25, 101.02), (13.12, 101.05),
    (13.00, 100.98), (12.90, 100.90),
]

# The Chao Phraya, from the river mouth up through the city.
_CHAO_PHRAYA = [
    (13.55, 100.58), (13.60, 100.57), (13.65, 100.51), (13.70, 100.49),
    (13.72, 100.51), (13.74, 100.49), (13.78, 100.50), (13.82, 100.49),
    (13.87, 100.50), (13.92, 100.52),
]

# Runway centrelines, threshold to threshold. Suvarnabhumi's pair runs about
# 013 degrees true, Don Mueang's about 030.
_RUNWAYS = {
    "VTBS": [
        [(13.6680, 100.7429), (13.7030, 100.7512)],   # 01L/19R
        [(13.6718, 100.7582), (13.7042, 100.7659)],   # 01R/19L
    ],
    "VTBD": [
        [(13.8982, 100.5945), (13.9270, 100.6116)],   # 03L/21R
        [(13.8982, 100.6030), (13.9270, 100.6201)],   # 03R/21L
    ],
}


def coastline():
    """Polylines for land and water edges."""
    return [_UPPER_GULF, _CHAO_PHRAYA]


def runways(icao_codes=None):
    """Runway centrelines, optionally limited to particular airports."""
    if icao_codes is None:
        selected = _RUNWAYS.values()
    else:
        wanted = [code.strip().upper() for code in icao_codes if code]
        selected = [_RUNWAYS[code] for code in wanted if code in _RUNWAYS]
    lines = []
    for group in selected:
        lines.extend(group)
    return lines
