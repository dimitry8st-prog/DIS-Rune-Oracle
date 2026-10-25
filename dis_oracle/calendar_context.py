"""Deterministic cultural calendar context; never a core vote or numeric seed.

Gregorian-to-lunar and modern-to-Egyptian correlations are reported inputs,
not authenticated historical facts. No clock, RNG, network or journal is used.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import ContractError, digest, shape, text, timestamp, validate_event


SCHEMA_VERSION = "rune-calendar-context-v1"
SCOPE = "CULTURAL_CONTEXT_ONLY"
PROFILES = ("japanese_rokuyo", "egyptian_cairo")
ROKUYO = ("Sensho", "Tomobiki", "Senbu", "Butsumetsu", "Taian", "Shakko")
ROKUYO_SOURCE = "https://www.ndl.go.jp/koyomi/chapter3/s3.html"
CAIRO_SCHEMA = "cairo-calendar-prognoses-v1"
CAIRO_CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "calendar" / "cairo_calendar_prognoses.json"
COMMON_FIELDS = ("calendar_date", "source_ref", "source_locator", "available_at")
PROFILE_FIELDS = {
    "japanese_rokuyo": COMMON_FIELDS + ("lunar_month", "lunar_day", "is_leap_month"),
    "egyptian_cairo": COMMON_FIELDS + ("month", "day", "mapping_rule"),
}
LIMITATIONS = [
    "Calendar labels describe declared cultural traditions, not measured probabilities or predictive efficacy.",
    "Reported dates, correlations and source references are USER_DECLARED, not authenticated.",
    "Calendar context does not change rune positions, lottery-rune-hash-v2, control samples or core weights.",
    "No Gregorian-to-lunar conversion or historical modern-to-Egyptian correlation is inferred.",
]


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{name} must be an integer in {low}..{high}; bool is not an integer")


def _url(value, name):
    text(value, name)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port  # Reject malformed declared ports, without making a request.
    except ValueError as exc:
        raise ContractError(f"{name} must be a complete HTTP(S) URL") from exc
    if (parsed.scheme not in ("http", "https") or not hostname
            or parsed.username is not None or parsed.password is not None
            or any(character.isspace() for character in value)):
        raise ContractError(f"{name} must be a complete HTTP(S) URL without credentials or whitespace")


def _civil_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ContractError("calendar_date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("invalid calendar_date") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate key in Cairo calendar corpus")
        result[key] = value
    return result


def _cairo_corpus():
    """Return a validated local snapshot, or None only when it is unavailable."""
    try:
        raw = CAIRO_CORPUS_PATH.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContractError("Cairo calendar corpus cannot be read") from exc
    try:
        corpus = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ContractError("invalid Cairo calendar corpus JSON") from exc
    shape(corpus, ("schema_version", "source_ref", "rights_notice", "rows"))
    if corpus["schema_version"] != CAIRO_SCHEMA:
        raise ContractError("unsupported Cairo calendar corpus schema")
    _url(corpus["source_ref"], "corpus.source_ref")
    text(corpus["rights_notice"], "corpus.rights_notice")
    if not isinstance(corpus["rows"], list):
        raise ContractError("Cairo calendar rows must be an array")
    rows = {}
    for row in corpus["rows"]:
        shape(row, ("month", "day", "segments"))
        _integer(row["month"], "corpus.month", 1, 12)
        _integer(row["day"], "corpus.day", 1, 30)
        key = (row["month"], row["day"])
        if key in rows:
            raise ContractError("duplicate month/day in Cairo calendar corpus")
        segments = row["segments"]
        if (not isinstance(segments, list) or len(segments) != 3
                or (segments != [None, None, None]
                    and any(type(item) is not str or item not in ("G", "S") for item in segments))):
            raise ContractError("Cairo calendar segments must be three G/S labels or three nulls")
        rows[key] = list(segments)
    return {"schema_version": CAIRO_SCHEMA, "source_ref": corpus["source_ref"],
            "rights_notice": corpus["rights_notice"],
            "sha256": hashlib.sha256(raw).hexdigest(), "rows": rows}


def validate_context(config, event, registered_at):
    """Validate every requested profile, including a present local corpus, before RNG."""
    shape(config, ("schema_version", "event_at", "timezone", "day_boundary", "profiles"))
    if config["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported calendar context schema")
    if config["day_boundary"] != "civil_midnight":
        raise ContractError("calendar context requires explicit civil_midnight")
    axes = validate_event(event)
    instant = timestamp(config["event_at"])
    registered = timestamp(registered_at)
    if not any(instant == timestamp(axis["deadline"]) for axis in axes.values()):
        raise ContractError("calendar event_at must match a registered event deadline")
    text(config["timezone"], "timezone")
    try:
        zone = ZoneInfo(config["timezone"])
        local = instant.astimezone(zone)
    except (ZoneInfoNotFoundError, ValueError, OverflowError) as exc:
        raise ContractError("timezone must be an available IANA timezone") from exc
    shape(config["profiles"], (), PROFILES)
    cutoff = min(registered, timestamp(event["cutoff_at"]))
    for profile_id, profile in config["profiles"].items():
        if not isinstance(profile, dict):
            raise ContractError("calendar profile must be an object")
        if not profile:  # Explicitly requested but unavailable, not a malformed partial observation.
            continue
        shape(profile, PROFILE_FIELDS[profile_id])
        if _civil_date(profile["calendar_date"]) != local.date():
            raise ContractError("calendar_date differs from event local date")
        _url(profile["source_ref"], "source_ref")
        text(profile["source_locator"], "source_locator")
        if timestamp(profile["available_at"]) > cutoff:
            raise ContractError("calendar inputs/source were not available before the fact cutoff/registration")
        if profile_id == "japanese_rokuyo":
            _integer(profile["lunar_month"], "lunar_month", 1, 12)
            _integer(profile["lunar_day"], "lunar_day", 1, 30)
            if type(profile["is_leap_month"]) is not bool:
                raise ContractError("is_leap_month must be a boolean")
        else:
            _integer(profile["month"], "month", 1, 13)
            _integer(profile["day"], "day", 1, 5 if profile["month"] == 13 else 30)
            if profile["mapping_rule"] != "DECLARED_MODERN_CORRELATION":
                raise ContractError("Egyptian dates require an explicit DECLARED_MODERN_CORRELATION")
            if profile["month"] != 13:
                _cairo_corpus()
    return {"local_datetime": local.isoformat(), "local_date": local.date().isoformat(),
            "local_time": local.timetz().isoformat(), "utc_offset_seconds": int(local.utcoffset().total_seconds()),
            "fold": local.fold}


def _profile_base(profile_id, profile):
    return {"profile_id": profile_id,
            "profile_version": "japanese-rokuyo-manual-lunar-v1" if profile_id == "japanese_rokuyo" else "egyptian-cairo-declared-correlation-v1",
            "scope": SCOPE, "status": "ABSTAIN", "reason": "MISSING_INPUTS",
            "source_verification": "USER_DECLARED", "forecast_status": "ABSTAIN",
            "inputs": deepcopy(profile), "input_hash": digest(profile),
            "day_quality": None, "segments": []}


def _rokuyo(profile):
    result = _profile_base("japanese_rokuyo", profile)
    result["rules_source_ref"] = ROKUYO_SOURCE
    if not profile:
        return result
    index = (profile["lunar_month"] + profile["lunar_day"] - 2) % 6
    label = ROKUYO[index]
    quality = "favorable" if label == "Taian" else "unfavorable" if label == "Butsumetsu" else "mixed"
    result.update(status="OK", reason="DECLARED_LUNAR_DATE_CONDITIONAL_CALCULATION",
                  calendar_position={"lunar_month": profile["lunar_month"], "lunar_day": profile["lunar_day"],
                                     "is_leap_month": profile["is_leap_month"], "index": index, "label": label},
                  day_quality=quality, correlation_status="USER_DECLARED_NO_GREGORIAN_TO_LUNAR_CONVERTER")
    if label in ("Sensho", "Senbu"):
        morning = "favorable" if label == "Sensho" else "unfavorable"
        result["segments"] = [{"period": "morning", "quality": morning},
                              {"period": "afternoon", "quality": "unfavorable" if morning == "favorable" else "favorable"}]
    # Tomobiki/Shakko remain mixed; no unsupported numerical clock boundaries are assigned.
    result["clock_boundaries_assigned"] = False
    return result


def _egypt(profile):
    result = _profile_base("egyptian_cairo", profile)
    result["correlation_status"] = "USER_DECLARED_NOT_HISTORICALLY_AUTHENTICATED"
    if not profile:
        return result
    result["calendar_position"] = {"month": profile["month"], "day": profile["day"]}
    if profile["month"] == 13:
        result["reason"] = "EPAGOMENAL_PROGNOSES_UNAVAILABLE"
        return result
    corpus = _cairo_corpus()
    if corpus is None:
        result["reason"] = "CORPUS_UNAVAILABLE"
        return result
    result["corpus"] = {key: value for key, value in corpus.items() if key != "rows"}
    segments = corpus["rows"].get((profile["month"], profile["day"]))
    if segments is None:
        result["reason"] = "CORPUS_ROW_UNAVAILABLE"
        return result
    if segments == [None, None, None]:
        result.update(reason="UNREADABLE_SOURCE_ROW",
                      segments=[{"segment": index, "source_label": None, "quality": None}
                                for index in (1, 2, 3)], clock_boundaries_assigned=False)
        return result
    quality = "favorable" if segments == ["G"] * 3 else "unfavorable" if segments == ["S"] * 3 else "mixed"
    result.update(status="OK", reason="LOCAL_CORPUS_WITH_DECLARED_MODERN_CORRELATION", day_quality=quality,
                  segments=[{"segment": index, "source_label": value,
                             "quality": "favorable" if value == "G" else "unfavorable"}
                            for index, value in enumerate(segments, 1)], clock_boundaries_assigned=False)
    return result


def build_context(config, event, registered_at):
    """Build a deterministic JSON-compatible snapshot, preserving declared provenance."""
    local = validate_context(config, event, registered_at)
    contexts = []
    for profile_id in PROFILES:  # Stable order independent of object insertion order.
        if profile_id in config["profiles"]:
            build = _rokuyo if profile_id == "japanese_rokuyo" else _egypt
            contexts.append(build(config["profiles"][profile_id]))
    return {"state": "CALENDAR_CONTEXT", "schema_version": SCHEMA_VERSION, "scope": SCOPE,
            "event_id": event["event_id"], "event_at": config["event_at"], "timezone": config["timezone"],
            "day_boundary": config["day_boundary"], **local,
            "config_hash": digest(config), "source_verification": "USER_DECLARED",
            "contexts": contexts, "limitations": list(LIMITATIONS)}
