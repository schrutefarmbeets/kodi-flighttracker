"""Just enough xbmc to import and exercise the addon outside Kodi."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4

LOG_LINES = []


def log(message, level=LOGINFO):
    LOG_LINES.append((level, message))


def executebuiltin(command, wait=False):
    LOG_LINES.append((LOGINFO, "executebuiltin: %s" % command))


class Monitor(object):
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=None):
        return False
