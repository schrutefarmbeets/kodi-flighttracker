"""Minimal xbmcgui stand-ins that record what the addon asked Kodi to draw.

The stubs enforce the constraints the real bindings enforce, most importantly
that ListItem properties must be strings, so type slips show up here rather
than on the telly.
"""

NOTIFICATION_INFO = "info"
NOTIFICATION_WARNING = "warning"
NOTIFICATION_ERROR = "error"


class ControlBase(object):
    def __init__(self):
        self.visible = True
        self.label = ""

    def setVisible(self, visible):
        self.visible = bool(visible)

    def setLabel(self, label, *args, **kwargs):
        if not isinstance(label, str):
            raise TypeError("setLabel needs a string, got %r" % (label,))
        self.label = label

    def getLabel(self):
        return self.label


class ControlImage(ControlBase):
    def __init__(self, x, y, width, height, filename, aspectRatio=0, colorDiffuse=""):
        ControlBase.__init__(self)
        for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
            if not isinstance(value, int):
                raise TypeError("ControlImage %s must be an int, got %r" % (name, value))
        if not isinstance(filename, str):
            raise TypeError("ControlImage filename must be a string")
        if colorDiffuse and not colorDiffuse.startswith("0x"):
            raise ValueError("colorDiffuse should look like 0xAARRGGBB, got %r" % colorDiffuse)
        self.x, self.y, self.width, self.height = x, y, width, height
        self.filename = filename
        self.colorDiffuse = colorDiffuse
        self.aspectRatio = aspectRatio

    def setImage(self, filename, useCache=True):
        if not isinstance(filename, str):
            raise TypeError("setImage needs a string, got %r" % (filename,))
        self.filename = filename

    def setColorDiffuse(self, colorDiffuse):
        if not isinstance(colorDiffuse, str):
            raise TypeError("setColorDiffuse needs a string, got %r" % (colorDiffuse,))
        if colorDiffuse and not colorDiffuse.startswith("0x"):
            raise ValueError("colorDiffuse should look like 0xAARRGGBB, got %r" % colorDiffuse)
        self.colorDiffuse = colorDiffuse


class ControlLabel(ControlBase):
    def __init__(self, x, y, width, height, label, font=None, textColor=None,
                 disabledColor=None, alignment=0, hasPath=False, angle=0):
        ControlBase.__init__(self)
        for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
            if not isinstance(value, int):
                raise TypeError("ControlLabel %s must be an int, got %r" % (name, value))
        if not isinstance(label, str):
            raise TypeError("ControlLabel label must be a string, got %r" % (label,))
        if textColor and not textColor.startswith("0x"):
            raise ValueError("textColor should look like 0xAARRGGBB, got %r" % textColor)
        self.x, self.y, self.width, self.height = x, y, width, height
        self.label = label
        self.font = font
        self.textColor = textColor
        self.alignment = alignment


class ControlList(ControlBase):
    def __init__(self):
        ControlBase.__init__(self)
        self.items = []
        self.position = 0

    def reset(self):
        self.items = []
        self.position = 0

    def addItems(self, items):
        self.items.extend(items)

    def getSelectedPosition(self):
        if not self.items:
            return -1
        return self.position

    def getListItem(self, index):
        return self.items[index]

    def selectItem(self, index):
        self.position = index

    def size(self):
        return len(self.items)


class ListItem(object):
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label = label
        self._properties = {}

    def setProperty(self, key, value):
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("ListItem.setProperty needs strings, got %r=%r" % (key, value))
        self._properties[key] = value

    def getProperty(self, key):
        return self._properties.get(key, "")

    def setLabel(self, label):
        self.label = label


class Window(object):
    _GLOBAL = {}

    def __init__(self, window_id=0):
        self.window_id = window_id

    def setProperty(self, key, value):
        Window._GLOBAL[(self.window_id, key)] = value

    def getProperty(self, key):
        return Window._GLOBAL.get((self.window_id, key), "")

    def clearProperty(self, key):
        Window._GLOBAL.pop((self.window_id, key), None)


class WindowXML(object):
    def __init__(self, *args, **kwargs):
        self.added = []
        self.controls = {}
        self.closed = False

    def addControls(self, controls):
        for control in controls:
            if not isinstance(control, ControlBase):
                raise TypeError("only controls can be added, got %r" % (control,))
        self.added.extend(controls)

    def addControl(self, control):
        self.addControls([control])

    def removeControls(self, controls):
        for control in controls:
            if control in self.added:
                self.added.remove(control)

    def getControl(self, control_id):
        if control_id not in self.controls:
            raise RuntimeError("no control with id %s" % control_id)
        return self.controls[control_id]

    def doModal(self):
        pass

    def close(self):
        self.closed = True


class Dialog(object):
    def notification(self, heading, message, icon=None, time=5000, sound=True):
        Dialog.last = (heading, message)

    def ok(self, heading, message):
        return True


class DialogProgressBG(object):
    def create(self, heading, message=""):
        pass

    def close(self):
        pass
