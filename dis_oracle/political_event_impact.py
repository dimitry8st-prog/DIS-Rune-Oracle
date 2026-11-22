"""Research-only event study with frozen inputs and descriptive matched controls."""

import argparse
from datetime import timedelta
from hashlib import sha256
import json
from math import fsum, isfinite, log, sqrt
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import ContractError, digest, sequence, shape, text, timestamp
from .journal import Journal

VERSION = "political-event-v0.1"
WINDOWS = (1, 5, 15, 60)
MINUTE = timedelta(minutes=1)
PRIMARY = "matched_excess_delta_realized_volatility_m60"
STOPPING = "one_event_all_registered_controls_no_replacement"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


def utc(value):
    result = timestamp(value)
    if not value.endswith(("Z", "+00:00")):
        raise ContractError("explicit UTC timestamp required")
    return result


def require_id(value, name):
    text(value, name)
    if not IDENTIFIER.fullmatch(value):
        raise ContractError(f"invalid {name}")


def session_bounds(session):
    shape(session, ("open_at_utc", "close_at_utc"))
    opened, closed = (utc(session[key]) for key in ("open_at_utc", "close_at_utc"))
    if opened >= closed or any(t.second or t.microsecond for t in (opened, closed)):
        raise ContractError("invalid regular session interval")
    return opened, closed


def minute_edges(anchor):
    floor = anchor.replace(second=0, microsecond=0)
    return floor, floor if anchor == floor else floor + MINUTE


def study_inputs(event, protocol):
    shape(event, ("event_id", "actor", "event_type", "source_url", "published_at_utc",
                  "observed_at_utc", "headline_sha256", "affected_symbols", "provenance"),
          ("headline", "topic", "surprise_label"))
    require_id(event["event_id"], "event_id")
    for key in ("actor", "event_type", "source_url", "headline_sha256"):
        text(event[key], key)
    source = urlsplit(event["source_url"])
    if source.scheme != "https" or not source.hostname or source.username or source.password:
        raise ContractError("event needs an HTTPS source without credentials")
    if not re.fullmatch(r"[0-9a-f]{64}", event["headline_sha256"]):
        raise ContractError("invalid headline SHA-256")
    if "headline" in event:
        text(event["headline"], "headline")
        if sha256(event["headline"].encode()).hexdigest() != event["headline_sha256"]:
            raise ContractError("headline SHA-256 mismatch")
    for key in ("topic", "surprise_label"):
        if key in event:
            text(event[key], key)
    sequence(event["affected_symbols"], "affected_symbols")
    for symbol in event["affected_symbols"]:
        require_id(symbol, "symbol")
    if not event["affected_symbols"] or len(set(event["affected_symbols"])) != len(event["affected_symbols"]):
        raise ContractError("affected_symbols must be nonempty and unique")
    if event["provenance"] not in ("SYNTHETIC", "IMPORTED"):
        raise ContractError("unsupported event provenance")

    shape(protocol, ("schema_version", "study_id", "registered_at_utc", "decision_cutoff_utc",
                     "time_windows", "symbol", "market_benchmark", "venue", "venue_timezone",
                     "session", "controls", "primary_metric", "stopping_rule"))
    for key in ("study_id", "symbol", "market_benchmark", "venue"):
        require_id(protocol[key], key)
    text(protocol["venue_timezone"], "venue_timezone")
    try:
        timezone = ZoneInfo(protocol["venue_timezone"])
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ContractError("venue_timezone must be an IANA zone") from exc
    if (
        protocol["schema_version"] != VERSION or protocol["time_windows"] != list(WINDOWS)
        or protocol["primary_metric"] != PRIMARY or protocol["stopping_rule"] != STOPPING
    ):
        raise ContractError("unsupported study protocol")
    if protocol["symbol"] not in event["affected_symbols"] or protocol["market_benchmark"] == protocol["symbol"]:
        raise ContractError("study needs an affected asset and a distinct benchmark")
    anchor, observed = (utc(event[key]) for key in ("published_at_utc", "observed_at_utc"))
    registered, cutoff = (utc(protocol[key]) for key in ("registered_at_utc", "decision_cutoff_utc"))
    if not registered <= anchor <= observed <= cutoff:
        raise ContractError("registration, publication, observation and decision cutoff are out of order")
    opened, closed = session_bounds(protocol["session"])
    if not opened <= anchor < closed:
        raise ContractError("published event is outside the registered regular session")

    sequence(protocol["controls"], "controls")
    control_ids, references = {event["event_id"]}, set()
    local = anchor.astimezone(timezone)
    for control in protocol["controls"]:
        shape(control, ("control_id", "reference_at_utc", "session", "source"))
        require_id(control["control_id"], "control_id")
        text(control["source"], "control source")
        reference = utc(control["reference_at_utc"])
        start, end = session_bounds(control["session"])
        before, after = minute_edges(reference)
        comparable = reference.astimezone(timezone)
        if (
            comparable.weekday() != local.weekday() or comparable.time() != local.time()
            or not start <= before - 60 * MINUTE <= after + 60 * MINUTE <= end <= registered
        ):
            raise ContractError("controls must match local weekday/time across completed historical sessions")
        if control["control_id"] in control_ids or reference in references:
            raise ContractError("duplicate control identifier or time")
        control_ids.add(control["control_id"])
        references.add(reference)
    return anchor, cutoff


def bar_index(rows, event, protocol, as_of, *, before=None):
    sequence(rows, "bars")
    indexed = {}
    for row in rows:
        shape(row, ("symbol", "venue", "start_at_utc", "end_at_utc", "available_at_utc",
                    "open", "high", "low", "close", "volume", "source", "synthetic"))
        text(row["source"], "bar source")
        if row["symbol"] not in (protocol["symbol"], protocol["market_benchmark"]) or row["venue"] != protocol["venue"]:
            raise ContractError("bar symbol or venue differs from the protocol")
        if type(row["synthetic"]) is not bool or row["synthetic"] != (event["provenance"] == "SYNTHETIC"):
            raise ContractError("market bar and event provenance differ")
        start, end, available = (utc(row[key]) for key in ("start_at_utc", "end_at_utc", "available_at_utc"))
        if start.second or start.microsecond or end != start + MINUTE or available < end:
            raise ContractError("bar must be a completed, UTC-aligned M1 interval")
        if available > as_of or (before is not None and end > before):
            raise ContractError("look-ahead: bar not available at cutoff or crosses publication")
        values = [row[key] for key in ("open", "high", "low", "close", "volume")]
        if any(type(value) not in (int, float) or not isfinite(value) for value in values):
            raise ContractError("OHLCV must contain finite numbers")
        opening, high, low, closing, volume = values
        if not 0 < low <= min(opening, closing) <= max(opening, closing) <= high or volume < 0:
            raise ContractError("invalid OHLCV prices or volume")
        key = (row["symbol"], start)
        if key in indexed:
            raise ContractError("duplicate M1 bar")
        indexed[key] = row
    return indexed


def freeze(event, protocol, feature_bars):
    """Validate pre-event inputs. Evaluation bars are never stored as features."""
    anchor, cutoff = study_inputs(event, protocol)
    indexed = bar_index(feature_bars, event, protocol, cutoff, before=anchor)
    payload = {
        "event": event, "protocol": protocol,
        "feature_bars": [indexed[key] for key in sorted(indexed)],
    }
    return {"state": "FROZEN", "inputs_sha256": digest(payload), **payload}


def _metrics(rows):
    prices = [rows[0]["open"], *(bar["close"] for bar in rows)]
    logs = [log(price) for price in prices]
    volatility = sqrt(fsum((end - start) ** 2 for start, end in zip(logs, logs[1:])))
    total_return = prices[-1] / prices[0] - 1
    if not isfinite(total_return):
        raise ContractError("price ratio out of numeric range")
    return {
        "return": total_return, "rv": volatility,
        "ohlcv": {
            "open": prices[0], "high": max(row["high"] for row in rows),
            "low": min(row["low"] for row in rows), "close": prices[-1],
            "volume": fsum(row["volume"] for row in rows),
        },
    }


def _window(indexed, protocol, anchor, session, minutes, as_of):
    first, after = minute_edges(anchor)
    start = first - minutes * MINUTE
    end = after + minutes * MINUTE
    opened, closed = session_bounds(session)
    if start < opened or end > closed:
        return {"status": "ABSTAIN", "reason": "OUTSIDE_REGISTERED_SESSION"}
    if end > as_of:
        return {"status": "ABSTAIN", "reason": "WINDOW_NOT_ELAPSED"}
    streams = []
    for symbol in (protocol["symbol"], protocol["market_benchmark"]):
        for origin in (start, after):
            rows = [indexed.get((symbol, origin + minute * MINUTE)) for minute in range(minutes)]
            if any(row is None for row in rows):
                return {"status": "ABSTAIN", "reason": "MISSING_COMPLETED_M1"}
            if any(row["volume"] == 0 for row in rows):
                return {"status": "ABSTAIN", "reason": "ZERO_TRADED_VOLUME"}
            streams.append(rows)
    asset_pre, asset, benchmark_pre, benchmark = map(_metrics, streams)
    if not any(item["rv"] for item in (asset_pre, asset, benchmark_pre, benchmark)):
        return {"status": "ABSTAIN", "reason": "FLAT_MARKET"}
    return {
        "status": "OK", "return": asset["return"], "benchmark_return": benchmark["return"],
        "abnormal_return": asset["return"] - benchmark["return"],
        "rv_before": asset_pre["rv"], "rv_after": asset["rv"],
        "delta_rv": asset["rv"] - asset_pre["rv"], "benchmark_rv_before": benchmark_pre["rv"],
        "benchmark_rv_after": benchmark["rv"], "asset_ohlcv": asset["ohlcv"],
        "benchmark_ohlcv": benchmark["ohlcv"],
    }


def _reaction(indexed, protocol, anchor):
    _, start = minute_edges(anchor)
    asset, bench = protocol["symbol"], protocol["market_benchmark"]
    asset_open, bench_open = (indexed[(symbol, start)]["open"] for symbol in (asset, bench))
    direction = 0
    result = dict.fromkeys(("first_move_seconds", "returned_within_band_seconds", "reversed_seconds"))
    for minute in range(60):
        t = start + minute * MINUTE
        excess = indexed[(asset, t)]["close"] / asset_open - indexed[(bench, t)]["close"] / bench_open
        elapsed = (t + MINUTE - anchor).total_seconds()
        if direction == 0 and abs(excess) >= 0.001:
            direction = 1 if excess > 0 else -1
            result["first_move_seconds"] = elapsed
        elif direction:
            if result["returned_within_band_seconds"] is None and abs(excess) < 0.001:
                result["returned_within_band_seconds"] = elapsed
            if result["reversed_seconds"] is None and direction * excess <= -0.001:
                result["reversed_seconds"] = elapsed
    return result


def evaluate(frozen, bars, as_of_utc):
    """Measure realized windows. Reports are descriptive for a single event."""
    shape(frozen, ("state", "inputs_sha256", "event", "protocol", "feature_bars"))
    event, protocol = frozen["event"], frozen["protocol"]
    if freeze(event, protocol, frozen["feature_bars"]) != frozen:
        raise ContractError("frozen study integrity check failed")
    anchor, cutoff = study_inputs(event, protocol)
    as_of = utc(as_of_utc)
    if as_of < cutoff:
        raise ContractError("evaluation time precedes the decision cutoff")
    observed = bar_index(bars, event, protocol, as_of)
    frozen_rows = bar_index(frozen["feature_bars"], event, protocol, cutoff, before=anchor)
    for key in observed.keys() & frozen_rows.keys():
        if observed[key] != frozen_rows[key]:
            raise ContractError("evaluation revises a frozen market bar")
    indexed = observed | frozen_rows
    input_hash = digest({"frozen_inputs_sha256": frozen["inputs_sha256"], "as_of_utc": as_of.isoformat(),
                         "bars": [indexed[key] for key in sorted(indexed)]})
    results = {}
    for minutes in WINDOWS:
        point = _window(indexed, protocol, anchor, protocol["session"], minutes, as_of)
        controls = {
            c["control_id"]: _window(indexed, protocol, utc(c["reference_at_utc"]), c["session"], minutes, as_of)
            for c in protocol["controls"]
        }
        point["controls"] = controls
        if point["status"] != "OK" or not controls or any(c["status"] != "OK" for c in controls.values()):
            point["matched"] = {"status": "ABSTAIN", "reason": "INCOMPLETE_EVENT_OR_REGISTERED_CONTROLS"}
        else:
            point["matched"] = {
                "status": "OK", "control_count": len(controls),
                "excess_abnormal_return": point["abnormal_return"] - fsum(c["abnormal_return"] for c in controls.values()) / len(controls),
                "excess_delta_rv": point["delta_rv"] - fsum(c["delta_rv"] for c in controls.values()) / len(controls),
            }
        results[str(minutes)] = point
    hour = results["60"]
    first, after = minute_edges(anchor)
    return {
        "schema_version": VERSION, "event_id": event["event_id"], "as_of_utc": as_of.isoformat(),
        "provenance": event["provenance"], "analysis_scope": "SINGLE_EVENT_DESCRIPTIVE",
        "market_validation": "NOT_VALIDATED_ON_REAL_MARKET",
        "inputs_sha256": input_hash, "frozen_inputs_sha256": frozen["inputs_sha256"],
        "publication_to_observation_seconds": (utc(event["observed_at_utc"]) - anchor).total_seconds(),
        "first_full_post_minute_utc": after.isoformat(), "publication_minute_excluded": first != after,
        "windows": results, "primary_metric": PRIMARY, "primary_status": hour["matched"]["status"],
        "primary_value": hour["matched"].get("excess_delta_rv"),
        "reaction_threshold_bps": 10,
        "reaction": _reaction(indexed, protocol, anchor) if hour["status"] == "OK" else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("operation", choices=("freeze", "evaluate"))
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    request = json.loads(args.input.read_text(encoding="utf-8"))
    journal = Journal(args.db)
    try:
        if args.operation == "freeze":
            shape(request, ("event", "protocol", "feature_bars"))
            report = freeze(**request)
            key = f"political-event:{report['protocol']['study_id']}:{report['event']['event_id']}"
        else:
            shape(request, ("study_id", "event_id", "evaluation_id", "bars", "as_of_utc"))
            for name in ("study_id", "event_id", "evaluation_id"):
                require_id(request[name], name)
            key = f"political-event:{request['study_id']}:{request['event_id']}"
            original = journal.get(key)
            if original is None:
                raise ContractError("freeze event and protocol first")
            report = evaluate(original, request["bars"], request["as_of_utc"])
            key += f":evaluation:{request['evaluation_id']}"
        journal.append(key, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    finally:
        journal.close()


if __name__ == "__main__":
    main()
