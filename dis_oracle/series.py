"""Read-only registry of lottery-rune-hash-v2 draws in one cycle journal.

Archival outcomes, descriptive comparisons and prospective trials are separate
populations. Their counts overlap and are not added together. No personal
archive is embedded here: if this journal has no such import, the real set
stays unavailable.
"""
from research_stats.core import report as statistics_report

from .contracts import digest, timestamp
from .lottery import (CONTROL_ID, METHOD_VERSION, author_outcome_slot, draw_record_key,
                      expectation)


NOTICE = ("Personal outcome archive was not supplied with this journal. "
          "Counts below are this database only. Archival outcomes, descriptive "
          "comparisons and prospective trials are separate populations and are not added together.")


def _slot(request, separate_study):
    if separate_study:
        if "lottery_outcomes" not in request:
            return None
        return request["lottery_outcomes"]
    return author_outcome_slot(request)


def _applied_chain(reports):
    """Latest report whose supersedes links walk back to a root, or none."""
    by_id = {report["request"]["report_id"]: report for report in reports}
    for start in reversed(reports):
        chain, cursor, seen, valid = [], start, set(), True
        while cursor is not None:
            report_id = cursor["request"]["report_id"]
            if report_id in seen:
                valid = False
                break
            seen.add(report_id)
            chain.append(cursor)
            parent_id = cursor["request"].get("supersedes")
            if not parent_id:
                break
            parent = by_id.get(parent_id)
            if parent is None or cursor.get("parent_report_hash") != digest(parent):
                valid = False
                break
            cursor = parent
        if valid:
            chain.reverse()
            return chain
    return []


def _times(*values):
    found = []
    for value in values:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found.extend(_times(item.get("occurred_at"), item.get("recorded_at")))
    return found


def series_summary(journal):
    """Aggregate saved pairs. Does not append, draw, or sample numbers."""
    records = journal.export()
    lottery_rows = [row for row in records if row["record_key"].endswith(":lottery-rune-hash-v2")]
    grouped = {}
    for row in lottery_rows:
        payload = row["payload"]
        grouped.setdefault((payload.get("game"), payload.get("draw")), []).append(row)
    kept, duplicate_imports = [], []
    for identity, rows in grouped.items():
        rows.sort(key=lambda row: row["seq"])
        kept.append(rows[0])
        duplicate_imports.extend({"game": identity[0], "draw": identity[1], "record_key": extra["record_key"]}
                                 for extra in rows[1:])
    draws, study_events, study_predictions, study_outcomes = [], [], [], []
    stamps, registrations, provenances = [], [], []
    for row in sorted(kept, key=lambda item: item["seq"]):
        pair = row["payload"]
        prefix = row["record_key"].rsplit(":lottery-rune-hash-v2", 1)[0]
        registration = journal.get(prefix + ":registered")
        if not registration:
            duplicate_imports.append({"game": pair.get("game"), "draw": pair.get("draw"),
                                      "record_key": row["record_key"], "reason": "registration missing"})
            continue
        manifest = registration["manifest"]
        separate_study = manifest.get("numeric_study") is not None
        reports = [item["payload"] for item in records
                   if item["record_key"].startswith(prefix + ":science:")]
        chain = _applied_chain(reports)
        applied_ids = {report["request"]["report_id"] for report in chain}
        versions = []
        for report in chain:
            slot = _slot(report["request"], separate_study)
            if slot is not None:
                versions.append(slot)
        applied = versions[-1] if versions else []
        history = [{"report_id": report["request"]["report_id"],
                    "supersedes": report["request"].get("supersedes"),
                    "reason": report["request"]["reason"],
                    "in_applied_chain": report["request"]["report_id"] in applied_ids,
                    "lottery_outcomes": _slot(report["request"], separate_study)}
                   for report in reports]
        event_id = draw_record_key(pair["game"], pair["draw"])
        mode = manifest["event"]["mode"]
        provenances.append(manifest["provenance"])
        registrations.append(registration["registered_at"])
        stamps.extend(_times(registration["registered_at"], pair["fixed_at"], pair.get("target_at"), applied))
        stamps.extend(report.get("analysis_at") for report in reports if isinstance(report.get("analysis_at"), str))
        study_events.append({"event_id": event_id, "registered_at": registration["registered_at"],
                             "target_at": pair.get("target_at")})
        for strategy, picked, suffix in ((METHOD_VERSION, pair["method_fields"], "method"),
                                         (CONTROL_ID, pair["control_fields"], "control")):
            study_predictions.append({"prediction_id": f"{event_id}:{suffix}", "event_id": event_id,
                                      "strategy_id": strategy, "mode": "forecast" if mode == "forecast" else "retrospective",
                                      "status": "PICK", "fixed_at": pair["fixed_at"], "confirmation": "CONFIRMED",
                                      "evidence_ref": pair["seed"], "fields": picked})
        outcome = None
        if len(applied) == 1:
            source = applied[0]
            outcome = {key: source[key] for key in
                       ("occurred_at", "recorded_at", "confirmation", "source_ref", "fields")}
            outcome["event_id"] = event_id
            study_outcomes.append(outcome)
        draws.append({"game": pair["game"], "draw": pair["draw"], "event_id": manifest["event"]["event_id"],
                      "run_prefix": prefix, "mode": mode, "target_at": pair.get("target_at"),
                      "fixed_at": pair["fixed_at"], "method_fields": pair["method_fields"],
                      "control_fields": pair["control_fields"], "outcome": outcome,
                      "history": history, "repeated_outcome_versions_excluded": max(0, len(versions) - 1),
                      "separate_imported_study": separate_study, "series_event_id": event_id})
    statistics = None
    if draws:
        study = {"schema_version": "dis-statistics-v1", "study_id": "lottery-rune-hash-v2-series",
                 "provenance": "SYNTHETIC" if set(provenances) == {"SYNTHETIC"} else "IMPORTED",
                 "method_id": METHOD_VERSION, "control_id": CONTROL_ID,
                 "registered_at": min(registrations, key=timestamp),
                 "analysis_at": max(stamps, key=timestamp),
                 "events": study_events, "predictions": study_predictions, "outcomes": study_outcomes}
        statistics = statistics_report(study)
    rows = _classify(draws, statistics)
    counts = _counts(rows)
    prospective = [row for row in rows if "prospective" in row["populations"]]
    method_sum = sum(sum(row["method_hits"]) for row in prospective) if prospective else None
    control_sum = sum(sum(row["control_hits"]) for row in prospective) if prospective else None
    result = {"schema_version": "lottery-series-summary-v1", "read_only": True,
              "method_id": METHOD_VERSION, "control_id": CONTROL_ID,
              "real_personal_archive": "UNAVAILABLE", "archive_note": NOTICE,
              "imported_numeric_study": "separate from lottery-rune-hash-v2; not added to these counts",
              "counts": counts,
              "duplicate_imports_excluded": duplicate_imports,
              "repeated_outcome_versions_excluded": sum(row["repeated_outcome_versions_excluded"] for row in rows),
              "prospective": {"trials": len(prospective), "method_hit_sum": method_sum,
                              "control_hit_sum": control_sum,
                              "difference_method_minus_control": None if method_sum is None else method_sum - control_sum,
                              "hits_by_field": {"method": [row["method_hits"] for row in prospective],
                                                "control": [row["control_hits"] for row in prospective]},
                              "expected_outcome": expectation()},
              "draws": rows, "statistics": statistics,
              "limitations": ["This registry does not authenticate sources or claim predictive efficacy.",
                              "Unknown outcome times stay unknown; archival rows are not relabelled as forecasts.",
                              "The personal archive was not in this database and its counts are not hardcoded."]}
    result["table"] = _table(result)
    return result


def _classify(draws, statistics):
    trials = {}
    if statistics:
        for trial in statistics["trials"]:
            trials.setdefault(trial["event_id"], {})[trial["strategy_id"]] = trial
    rows = []
    for draw in draws:
        method = trials.get(draw["series_event_id"], {}).get(METHOD_VERSION, {})
        control = trials.get(draw["series_event_id"], {}).get(CONTROL_ID, {})
        method_hits = method.get("hits_by_field") or method.get("descriptive_hits_not_prospective")
        control_hits = control.get("hits_by_field") or control.get("descriptive_hits_not_prospective")
        scored = method.get("hits_by_field") is not None and control.get("hits_by_field") is not None
        reasons = list(method.get("exclusion_reasons") or [])
        populations = []
        if scored:
            populations.append("prospective")
        elif method_hits is not None and control_hits is not None:
            populations.append("descriptive")
        if draw["outcome"] is not None and "prospective" not in populations:
            populations.append("archival")
        if draw["outcome"] is None:
            populations.append("awaiting")
        difference = None
        if method_hits is not None and control_hits is not None:
            difference = sum(method_hits) - sum(control_hits)
        rows.append({**draw, "classification": method.get("classification"),
                     "exclusion_reasons": reasons, "method_hits": method_hits,
                     "control_hits": control_hits, "difference": difference,
                     "counted_in_prospective_sum": scored, "populations": populations})
    return rows


def _counts(rows):
    archival = [row for row in rows if "archival" in row["populations"]]
    descriptive = [row for row in rows if "descriptive" in row["populations"]]
    overlap = [row for row in archival if "descriptive" in row["populations"]]
    return {"archival_outcomes": len(archival), "descriptive_comparisons": len(descriptive),
            "prospective_trials": sum(row["counted_in_prospective_sum"] for row in rows),
            "overlap_archival_and_descriptive": len(overlap),
            "awaiting_outcome": sum("awaiting" in row["populations"] for row in rows),
            "late": sum(row["classification"] == "LATE" for row in rows),
            "retrospective": sum(row["classification"] == "RETROSPECTIVE" for row in rows),
            "unconfirmed": sum("UNCONFIRMED" in row["exclusion_reasons"] or "UNCONFIRMED_OUTCOME" in row["exclusion_reasons"]
                               for row in rows),
            "missing_outcome": sum("MISSING_OUTCOME" in row["exclusion_reasons"] for row in rows),
            "missing_prediction": sum("MISSING_PREDICTION" in row["exclusion_reasons"] for row in rows),
            "not_additive": True}


def _hits(value):
    if value is None:
        return "—"
    return "+".join(str(item) for item in value)


def _table(result):
    lines = ["lottery-rune-hash-v2 series  |  read only  |  personal archive: UNAVAILABLE",
             "Archival outcomes, descriptive comparisons and prospective trials are not added together.",
             "",
             f"{'game':<22} {'draw':>6}  {'populations':<24} {'method':>8} {'control':>8} {'diff':>6}  counted",
             f"{'-' * 22} {'-' * 6}  {'-' * 24} {'-' * 8} {'-' * 8} {'-' * 6}  -------"]
    for row in result["draws"]:
        lines.append(f"{row['game'][:22]:<22} {row['draw']:>6}  {','.join(row['populations']):<24} "
                     f"{_hits(row['method_hits']):>8} {_hits(row['control_hits']):>8} "
                     f"{'—' if row['difference'] is None else row['difference']:>6}  "
                     f"{'yes' if row['counted_in_prospective_sum'] else 'no'}")
    if not result["draws"]:
        lines.append("(no registered lottery draws)")
    prospective = result["prospective"]
    counts = result["counts"]
    lines += ["",
              f"prospective trials: {prospective['trials']}",
              f"prospective method sum: {prospective['method_hit_sum']}",
              f"prospective control sum: {prospective['control_hit_sum']}",
              f"prospective difference: {prospective['difference_method_minus_control']}",
              f"null expectation per prospective pair: {prospective['expected_outcome']['hits_per_field']} per field, "
              f"{prospective['expected_outcome']['total_hits']} total",
              f"archival outcomes: {counts['archival_outcomes']}",
              f"descriptive comparisons: {counts['descriptive_comparisons']}",
              f"overlap of those two populations: {counts['overlap_archival_and_descriptive']}",
              f"awaiting outcome: {counts['awaiting_outcome']}",
              f"late: {counts['late']}  retrospective: {counts['retrospective']}  "
              f"unconfirmed: {counts['unconfirmed']}  missing outcome: {counts['missing_outcome']}",
              f"duplicate imports excluded: {len(result['duplicate_imports_excluded'])}",
              f"repeated outcome versions excluded: {result['repeated_outcome_versions_excluded']}",
              result["archive_note"], ""]
    return "\n".join(lines)
