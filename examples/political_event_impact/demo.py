"""Generate frozen-input and evaluation fixtures for a synthetic event and control."""

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from dis_oracle.political_event_impact import PRIMARY, STOPPING, VERSION, WINDOWS


def fixtures():
    headline = "Synthetic announcement for event-study tests"
    event = {
        "event_id": "SYNTH-EVENT", "actor": "Synthetic policymaker", "event_type": "announcement",
        "source_url": "https://example.invalid/research/synthetic-event",
        "published_at_utc": "2026-11-18T15:30:30+00:00", "observed_at_utc": "2026-11-18T15:30:35+00:00",
        "headline": headline, "headline_sha256": sha256(headline.encode()).hexdigest(),
        "affected_symbols": ["DEMO"], "provenance": "SYNTHETIC",
    }
    control_session = {"open_at_utc": "2026-11-11T14:30:00+00:00", "close_at_utc": "2026-11-11T21:00:00+00:00"}
    protocol = {
        "schema_version": VERSION, "study_id": "SYNTH-PEI-01",
        "registered_at_utc": "2026-11-18T14:00:00+00:00", "decision_cutoff_utc": "2026-11-18T15:30:40+00:00",
        "time_windows": list(WINDOWS), "symbol": "DEMO", "market_benchmark": "INDEX",
        "venue": "DEMO-XNYS", "venue_timezone": "America/New_York",
        "session": {"open_at_utc": "2026-11-18T14:30:00+00:00", "close_at_utc": "2026-11-18T21:00:00+00:00"},
        "controls": [{
            "control_id": "SYNTH-CONTROL", "reference_at_utc": "2026-11-11T15:30:30+00:00",
            "session": control_session, "source": "synthetic:neutral-control-v1",
        }],
        "primary_metric": PRIMARY, "stopping_rule": STOPPING,
    }

    def stream(day, symbol, after, closes):
        start = datetime.fromisoformat(f"2026-11-{day:02}T{'15:31' if after else '14:30'}:00+00:00")
        opening = 100.0
        for index, closing in enumerate(closes):
            left = start + timedelta(minutes=index)
            right = left + timedelta(minutes=1)
            yield {
                "symbol": symbol, "venue": protocol["venue"], "start_at_utc": left.isoformat(),
                "end_at_utc": right.isoformat(), "available_at_utc": right.isoformat(),
                "open": opening, "high": max(opening, closing), "low": min(opening, closing),
                "close": closing, "volume": 100, "source": "synthetic:known-path-v1", "synthetic": True,
            }
            opening = closing

    pre = [100.0 + 0.02 * (index % 2) for index in range(60)]
    market = [100.0 + (index + 1) / 300 for index in range(60)]
    impacted = [100.30, 100.025, 99.75, 100.55, 101.0] + [102.0] * 10 + [101.5] * 45
    features, later = [], []
    for symbol in ("DEMO", "INDEX"):
        features.extend(stream(18, symbol, False, pre))
        later.extend(stream(18, symbol, True, impacted if symbol == "DEMO" else market))
        later.extend(stream(11, symbol, False, pre))
        later.extend(stream(11, symbol, True, market))
    return (
        {"event": event, "protocol": protocol, "feature_bars": features},
        {"study_id": protocol["study_id"], "event_id": event["event_id"], "evaluation_id": "SYNTH-EVAL-v1",
         "bars": later, "as_of_utc": "2026-11-18T16:32:00+00:00"},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    directory = parser.parse_args().directory
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in zip(("freeze.json", "evaluate.json"), fixtures()):
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
