"""Stub xbmcaddon backed by the real resources/settings.xml defaults."""

import os
import xml.etree.ElementTree as ET

ADDON_ROOT = os.environ.get("FLIGHTTRACKER_ADDON_ROOT", "")


def _load_defaults():
    values = {}
    path = os.path.join(ADDON_ROOT, "resources", "settings.xml")
    if not os.path.exists(path):
        return values
    tree = ET.parse(path)
    for setting in tree.getroot().iter("setting"):
        key = setting.get("id")
        kind = setting.get("type")
        default = setting.find("default")
        if key is None or default is None:
            continue
        text = (default.text or "").strip()
        if kind == "boolean":
            values[key] = text.lower() == "true"
        elif kind == "integer":
            values[key] = int(text or 0)
        else:
            values[key] = text
    return values


class Addon(object):
    _VALUES = None

    def __init__(self, id=None):
        if Addon._VALUES is None:
            Addon._VALUES = _load_defaults()
        self.id = id or "script.flighttracker"

    # -- info
    def getAddonInfo(self, key):
        return {
            "id": self.id,
            "name": "Flight Tracker",
            "path": ADDON_ROOT,
            "profile": os.path.join(ADDON_ROOT, ".testprofile"),
            "version": "1.0.0",
        }.get(key, "")

    def getLocalizedString(self, string_id):
        return "string:%d" % string_id

    # -- settings
    def getSetting(self, key):
        value = Addon._VALUES.get(key, "")
        return value if isinstance(value, str) else str(value)

    def getSettingInt(self, key):
        return int(Addon._VALUES.get(key, 0))

    def getSettingBool(self, key):
        return bool(Addon._VALUES.get(key, False))

    def setSetting(self, key, value):
        Addon._VALUES[key] = value

    def setSettingBool(self, key, value):
        Addon._VALUES[key] = bool(value)

    def setSettingInt(self, key, value):
        Addon._VALUES[key] = int(value)

    def openSettings(self):
        pass
