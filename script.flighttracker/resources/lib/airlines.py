"""Airline codes, for when the route lookup comes back empty.

A callsign carries the airline's three-letter ICAO code in front of the flight
number: TVJ344 is Thai Vietjet. The logo CDN is keyed on the two-letter IATA
code instead, and answers TVJ with a 404 and VZ with a logo, so without this
table an airline whose routes the database does not carry loses its logo too.
Thai Vietjet is exactly that case at Bangkok.

Only mappings worth being sure about belong here. A wrong one puts another
airline's logo on the card, which is worse than the plain code it replaces.
"""

ICAO_TO_IATA = {
    # Thailand
    "THA": "TG", "TVJ": "VZ", "AIQ": "FD", "TLM": "SL", "BKP": "PG",
    "NOK": "DD", "THD": "WE", "TAX": "XJ",

    # South-east Asia
    "SIA": "SQ", "TGW": "TR", "MAS": "MH", "AXM": "AK", "XAX": "D7",
    "MXD": "OD", "GIA": "GA", "LNI": "JT", "CTV": "QG", "BTK": "ID",
    "CEB": "5J", "PAL": "PR", "HVN": "VN", "VJC": "VJ", "BAV": "QH",
    "KHV": "K6", "LAO": "QV", "RBA": "BI", "MMA": "8M", "UBA": "UB",

    # East Asia
    "CPA": "CX", "HDA": "KA", "HKE": "UO", "CAL": "CI", "EVA": "BR",
    "CES": "MU", "CSN": "CZ", "CCA": "CA", "CXA": "MF", "CSZ": "ZH",
    "CHH": "HU", "CQH": "9C", "JAL": "JL", "ANA": "NH", "APJ": "MM",
    "KAL": "KE", "AAR": "OZ", "TWB": "TW",

    # South Asia
    "IGO": "6E", "AIC": "AI", "SEJ": "SG", "ALK": "UL", "BBC": "BG",
    "RNA": "RA", "DRK": "KB",

    # Middle East
    "UAE": "EK", "QTR": "QR", "ETD": "EY", "OMA": "WY", "GFA": "GF",
    "KAC": "KU", "SVA": "SV", "MSR": "MS", "THY": "TK", "ABY": "G9",
    "FDB": "FZ",

    # Europe
    "BAW": "BA", "DLH": "LH", "AFR": "AF", "KLM": "KL", "SWR": "LX",
    "AUA": "OS", "FIN": "AY", "SAS": "SK", "VIR": "VS", "AFL": "SU",
    "SBI": "S7", "UZB": "HY", "KZR": "KC",

    # Elsewhere
    "QFA": "QF", "ANZ": "NZ", "VOZ": "VA", "UAL": "UA", "DAL": "DL",
    "AAL": "AA", "ETH": "ET",

    # Freight, which is a good half of what moves at night
    "GTI": "5Y", "FDX": "FX", "UPS": "5X", "CLX": "CV", "ABW": "RU",
}


def iata_for(callsign):
    """The airline's IATA code, worked out from the callsign prefix."""
    code = (callsign or "").strip().upper()
    if len(code) < 3:
        return ""
    prefix = code[:3]
    if not prefix.isalpha():
        return ""
    return ICAO_TO_IATA.get(prefix, "")
