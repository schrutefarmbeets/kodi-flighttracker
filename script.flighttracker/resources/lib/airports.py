"""Coordinates for the reference airports used to tell arrivals from departures.

Only a seed list is shipped. Every route lookup returns the coordinates of its
own origin and destination, so the table fills itself in as you watch, and the
learned entries are written to the same cache file as the routes.
"""

# ICAO: (IATA, name, city, lat, lon)
SEED = {
    # Thailand
    "VTBS": ("BKK", "Suvarnabhumi", "Bangkok", 13.6811, 100.7471),
    "VTBD": ("DMK", "Don Mueang", "Bangkok", 13.9126, 100.6070),
    "VTBU": ("UTP", "U-Tapao Rayong-Pattaya", "Rayong", 12.6799, 101.0050),
    "VTSP": ("HKT", "Phuket", "Phuket", 8.1132, 98.3169),
    "VTSM": ("USM", "Samui", "Koh Samui", 9.5479, 100.0623),
    "VTSG": ("KBV", "Krabi", "Krabi", 8.0991, 98.9862),
    "VTSS": ("HDY", "Hat Yai", "Hat Yai", 6.9332, 100.3927),
    "VTCC": ("CNX", "Chiang Mai", "Chiang Mai", 18.7668, 98.9626),
    "VTCT": ("CEI", "Chiang Rai", "Chiang Rai", 19.9523, 99.8829),
    "VTUD": ("UTH", "Udon Thani", "Udon Thani", 17.3864, 102.7883),
    "VTUU": ("UBP", "Ubon Ratchathani", "Ubon Ratchathani", 15.2513, 104.8703),
    "VTUK": ("KKC", "Khon Kaen", "Khon Kaen", 16.4666, 102.7838),
    "VTSB": ("URT", "Surat Thani", "Surat Thani", 9.1326, 99.1358),
    "VTSF": ("NAW", "Narathiwat", "Narathiwat", 6.5199, 101.7434),
    "VTPP": ("PHS", "Phitsanulok", "Phitsanulok", 16.7829, 100.2792),
    "VTSC": ("NST", "Nakhon Si Thammarat", "Nakhon Si Thammarat", 8.5396, 99.9447),
    "VTST": ("TST", "Trang", "Trang", 7.5087, 99.6166),
    "VTSK": ("PAN", "Pattani", "Pattani", 6.7855, 101.1537),

    # Regional hubs that show up constantly in Bangkok traffic
    "WSSS": ("SIN", "Changi", "Singapore", 1.3502, 103.9944),
    "VHHH": ("HKG", "Hong Kong", "Hong Kong", 22.3089, 113.9145),
    "WMKK": ("KUL", "Kuala Lumpur", "Kuala Lumpur", 2.7456, 101.7099),
    "VVNB": ("HAN", "Noi Bai", "Hanoi", 21.2212, 105.8072),
    "VVTS": ("SGN", "Tan Son Nhat", "Ho Chi Minh City", 10.8188, 106.6520),
    "VDPP": ("PNH", "Phnom Penh", "Phnom Penh", 11.5466, 104.8441),
    "VLVT": ("VTE", "Wattay", "Vientiane", 17.9883, 102.5633),
    "VYYY": ("RGN", "Yangon", "Yangon", 16.9073, 96.1332),
    "VGHS": ("DAC", "Hazrat Shahjalal", "Dhaka", 23.8433, 90.3978),
    "VOMM": ("MAA", "Chennai", "Chennai", 12.9941, 80.1707),
    "VIDP": ("DEL", "Indira Gandhi", "Delhi", 28.5665, 77.1031),
    "VABB": ("BOM", "Chhatrapati Shivaji", "Mumbai", 19.0887, 72.8679),
    "VECC": ("CCU", "Netaji Subhas Chandra Bose", "Kolkata", 22.6547, 88.4467),
    "VOBL": ("BLR", "Kempegowda", "Bengaluru", 13.1979, 77.7063),
    "WIII": ("CGK", "Soekarno-Hatta", "Jakarta", -6.1256, 106.6559),
    "WADD": ("DPS", "Ngurah Rai", "Denpasar", -8.7482, 115.1672),
    "RPLL": ("MNL", "Ninoy Aquino", "Manila", 14.5086, 121.0195),
    "RCTP": ("TPE", "Taoyuan", "Taipei", 25.0777, 121.2328),
    "RJAA": ("NRT", "Narita", "Tokyo", 35.7647, 140.3863),
    "RJTT": ("HND", "Haneda", "Tokyo", 35.5533, 139.7811),
    "RJBB": ("KIX", "Kansai", "Osaka", 34.4347, 135.2441),
    "RKSI": ("ICN", "Incheon", "Seoul", 37.4691, 126.4505),
    "ZBAA": ("PEK", "Capital", "Beijing", 40.0801, 116.5846),
    "ZSPD": ("PVG", "Pudong", "Shanghai", 31.1443, 121.8083),
    "ZGGG": ("CAN", "Baiyun", "Guangzhou", 23.3924, 113.2988),
    "ZUUU": ("CTU", "Shuangliu", "Chengdu", 30.5785, 103.9471),
    "ZPPP": ("KMG", "Changshui", "Kunming", 25.1019, 102.9292),
    "OMDB": ("DXB", "Dubai", "Dubai", 25.2532, 55.3657),
    "OTHH": ("DOH", "Hamad", "Doha", 25.2731, 51.6081),
    "OMAA": ("AUH", "Zayed", "Abu Dhabi", 24.4330, 54.6511),
    "VRMM": ("MLE", "Velana", "Male", 4.1918, 73.5291),
    "VCBI": ("CMB", "Bandaranaike", "Colombo", 7.1808, 79.8841),
    "VNKT": ("KTM", "Tribhuvan", "Kathmandu", 27.6966, 85.3591),
    "YSSY": ("SYD", "Kingsford Smith", "Sydney", -33.9461, 151.1772),
    "YMML": ("MEL", "Melbourne", "Melbourne", -37.6733, 144.8433),
    "EGLL": ("LHR", "Heathrow", "London", 51.4700, -0.4543),
    "EDDF": ("FRA", "Frankfurt", "Frankfurt", 50.0379, 8.5622),
    "EHAM": ("AMS", "Schiphol", "Amsterdam", 52.3105, 4.7683),
    "LSZH": ("ZRH", "Zurich", "Zurich", 47.4647, 8.5492),
    "UUEE": ("SVO", "Sheremetyevo", "Moscow", 55.9726, 37.4146),
    "LTFM": ("IST", "Istanbul", "Istanbul", 41.2753, 28.7519),
}


class AirportBook(object):
    """Seed table plus anything learned from route lookups."""

    def __init__(self, learned=None):
        self._learned = dict(learned or {})
        self._iata_index = None
        self._iata_stamp = -1

    def get(self, icao):
        if not icao:
            return None
        icao = icao.strip().upper()
        entry = self._learned.get(icao)
        if entry:
            return entry
        seed = SEED.get(icao)
        if seed:
            return {
                "icao": icao, "iata": seed[0], "name": seed[1],
                "city": seed[2], "lat": seed[3], "lon": seed[4],
            }
        return None

    def learn(self, icao, iata, name, city, lat, lon):
        if not icao:
            return
        icao = icao.strip().upper()
        if icao in SEED or icao in self._learned:
            return
        if lat is None or lon is None:
            return
        self._learned[icao] = {
            "icao": icao, "iata": iata or "", "name": name or icao,
            "city": city or "", "lat": float(lat), "lon": float(lon),
        }

    def by_iata(self, iata):
        """Look an airport up the other way round, by its two-or-three letter code.

        Some route sources answer in IATA codes alone, so the table has to be
        readable from that end too. Built on demand and thrown away when the
        learned set grows, which is rare enough not to matter.
        """
        code = (iata or "").strip().upper()
        if not code:
            return None
        index = getattr(self, "_iata_index", None)
        if index is None or self._iata_stamp != len(self._learned):
            index = {}
            for icao, seed in SEED.items():
                if seed[0]:
                    index[seed[0]] = {"icao": icao, "iata": seed[0], "name": seed[1],
                                      "city": seed[2], "lat": seed[3], "lon": seed[4]}
            for icao, entry in self._learned.items():
                if entry.get("iata"):
                    index[entry["iata"].upper()] = entry
            self._iata_index = index
            self._iata_stamp = len(self._learned)
        return index.get(code)

    def position(self, icao):
        entry = self.get(icao)
        if not entry:
            return None
        return entry["lat"], entry["lon"]

    def label(self, icao):
        """Short human label, preferring the city name over the airport name."""
        entry = self.get(icao)
        if not entry:
            return (icao or "").upper()
        return entry["city"] or entry["name"] or entry["icao"]

    def export_learned(self):
        return dict(self._learned)
