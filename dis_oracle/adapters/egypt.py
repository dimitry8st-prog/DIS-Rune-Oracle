"""Egyptian core card based on the existing declared Cairo calendar profile."""
from copy import deepcopy

from ..calendar_context import CAIRO_PROFILE_VERSION, SCHEMA_VERSION, build_context, validate_context
from ..contracts import ContractError, digest, shape


def _context_config(config):
    if config == {}:
        return None
    shape(config, ("profile", "event_at", "timezone", "day_boundary", "correlation"))
    if config["profile"] != CAIRO_PROFILE_VERSION:
        raise ContractError("unsupported Egyptian core profile")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_at": config["event_at"],
        "timezone": config["timezone"],
        "day_boundary": config["day_boundary"],
        "profiles": {"egyptian_cairo": config["correlation"]},
    }


def validate_config(config, event, registered_at):
    context_config = _context_config(config)
    if context_config is not None:
        validate_context(context_config, event, registered_at, check_corpus=False)


def card(config, event, registered_at):
    """Read one local corpus snapshot for a card to be stored with registration."""
    context_config = _context_config(config)
    inputs = {"event_id": event["event_id"], **deepcopy(config)}
    if context_config is None:
        raw = {"status": "ABSTAIN", "reason": "MISSING_INPUTS", "forecast_status": "ABSTAIN"}
    else:
        snapshot = build_context(context_config, event, registered_at)
        raw = snapshot["contexts"][0]
        raw.update(local_date=snapshot["local_date"], local_datetime=snapshot["local_datetime"])

    reason = raw["reason"]
    status = "ABSTAIN"
    if reason == "MISSING_INPUTS":
        status, reason = "UNAVAILABLE", "MISSING_MODERN_CORRELATION"
    elif reason in ("CORPUS_UNAVAILABLE", "CORPUS_ROW_UNAVAILABLE"):
        status = "UNAVAILABLE"
    elif raw["status"] == "OK":
        reason = "DECLARED_CORRELATION_LOOKUP_WITHOUT_VERIFIED_INTERPRETATION"

    return {
        "core_id": "egypt", "status": status, "reason": reason,
        "protocol_version": CAIRO_PROFILE_VERSION, "inputs": inputs, "input_hash": digest(inputs),
        "raw_result": raw,
        "interpretation": "Cultural calendar labels only; no verified historical interpretation or forecast.",
        "claims": [],
    }
