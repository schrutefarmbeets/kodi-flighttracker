"""Stub xbmcvfs backed by the local filesystem."""

import os


def translatePath(path):
    return path


def exists(path):
    return os.path.exists(path)


def mkdirs(path):
    try:
        os.makedirs(path)
        return True
    except OSError:
        return os.path.isdir(path)


def delete(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False
