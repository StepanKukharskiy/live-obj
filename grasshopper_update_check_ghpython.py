# Spellshape Grasshopper - Update Checker
# Release date: 2026-05-17
# License: MIT
# Source: https://github.com/StepanKukharskiy/live-obj
#
# Network behavior:
# - Only runs when check=True.
# - Sends one GET request to the configured Spellshape release JSON URL.
# - Does not send telemetry from this script.
#
# Inputs to create:
#   check       bool  button: check for updates
#   site_url    str   optional, default https://live-obj-production.up.railway.app/
#   local_date  str   optional, default release date below
#   timeout_sec int   optional HTTP timeout, default 15
#
# Outputs to create:
#   info
#   update_available
#   latest_date
#   release_url
#   raw_json
#   error
#
# Wire info to a Panel.

import json
import System
import scriptcontext as sc
from System.IO import StreamReader
from System.Net import WebRequest, ServicePointManager, SecurityProtocolType


LOCAL_RELEASE_DATE = "2026-05-17"
DEFAULT_SITE_URL = "https://live-obj-production.up.railway.app/"
RELEASE_PATH = "grasshopper-release.json"


def safe_str(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def input_value(name, fallback=None):
    try:
        return globals().get(name, fallback)
    except Exception:
        return fallback


def set_message(text):
    try:
        ghenv.Component.Message = text
    except Exception:
        pass


def sticky_key(name):
    try:
        guid = str(ghenv.Component.InstanceGuid)
    except Exception:
        guid = "default"
    return "spellshape_update_check:%s:%s" % (guid, name)


def get_cached(name, fallback=None):
    return sc.sticky.get(sticky_key(name), fallback)


def set_cached(name, value):
    sc.sticky[sticky_key(name)] = value


def save_result():
    set_cached("info", info)
    set_cached("update_available", update_available)
    set_cached("latest_date", latest_date)
    set_cached("release_url", release_url)
    set_cached("raw_json", raw_json)
    set_cached("error", error)


def parse_timeout_ms(value):
    try:
        seconds = int(value)
    except Exception:
        seconds = 15
    seconds = max(5, min(60, seconds))
    return seconds * 1000


def release_endpoint(site):
    site = safe_str(site, DEFAULT_SITE_URL).strip() or DEFAULT_SITE_URL
    site = site.rstrip("/") + "/"
    return site + RELEASE_PATH


def fetch_text(url):
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass
    req = WebRequest.Create(url)
    req.Method = "GET"
    timeout_ms = parse_timeout_ms(input_value("timeout_sec", None))
    try:
        req.Timeout = timeout_ms
        req.ReadWriteTimeout = timeout_ms
    except Exception:
        pass
    resp = req.GetResponse()
    reader = StreamReader(resp.GetResponseStream())
    try:
        return reader.ReadToEnd()
    finally:
        reader.Close()
        resp.Close()


def date_key(text):
    parts = safe_str(text).strip().split("-")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 0, 0)


release_url = release_endpoint(input_value("site_url", DEFAULT_SITE_URL))
info = safe_str(get_cached("info", "Press check to look for Spellshape Grasshopper updates."))
update_available = bool(get_cached("update_available", False))
latest_date = safe_str(get_cached("latest_date", ""))
raw_json = safe_str(get_cached("raw_json", ""))
error = safe_str(get_cached("error", ""))

local = safe_str(input_value("local_date", LOCAL_RELEASE_DATE), LOCAL_RELEASE_DATE).strip() or LOCAL_RELEASE_DATE

if bool(input_value("check", False)):
    try:
        set_message("checking...")
        raw_json = fetch_text(release_url)
        data = json.loads(raw_json)
        latest_date = safe_str(data.get("latest_date", "")).strip()
        message = safe_str(data.get("message", "")).strip()
        download_url = safe_str(data.get("download_url", DEFAULT_SITE_URL)).strip()
        update_available = date_key(latest_date) > date_key(local)
        if update_available:
            info = "\n".join([
                "Update available",
                "Local date: " + local,
                "Latest date: " + latest_date,
                message or "Download the latest Spellshape Grasshopper file.",
                "URL: " + download_url,
            ])
            set_message("update available")
        else:
            info = "\n".join([
                "Spellshape Grasshopper scripts are up to date.",
                "Local date: " + local,
                "Latest date: " + (latest_date or "unknown"),
            ])
            set_message("up to date")
        save_result()
    except Exception as e:
        error = str(e)
        info = "Update check failed: " + error
        set_message("check failed")
        save_result()
else:
    if latest_date:
        set_message("last checked")
    else:
        set_message("idle")
