"""Offline research audit; deliberately separate from the runtime adapter.

Run from any directory: python scripts/yijing_audit.py [--check].
The reference data contains factual extracts from pinned external sources.
No Qwen expected answer is used to calculate the six-line structures.
"""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "research/audit"
INPUT = ROOT / "research/qwen/yijing_examples_v2_UNVERIFIED.json"
SPEC = ROOT / "research/qwen/YIJING_SPECIFICATION_v2_UNVERIFIED.md"
TRIGRAMS = {
    (1, 1, 1): ("☰", "乾"), (0, 0, 0): ("☷", "坤"),
    (1, 0, 0): ("☳", "震"), (0, 1, 0): ("☵", "坎"),
    (0, 0, 1): ("☶", "艮"), (0, 1, 1): ("☴", "巽"),
    (1, 0, 1): ("☲", "離"), (1, 1, 0): ("☱", "兌"),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def references():
    return json.loads((AUDIT / "sources/reference_data.json").read_text())


def reading_evidence():
    return json.loads((AUDIT / "sources/reading_evidence.json").read_text())


def extract_wikipedia_facts(html):
    """Extract facts, excluding Wikipedia's changing navigation/HTML shell."""
    class Paragraphs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.buffer = []
            self.paragraphs = []

        def handle_starttag(self, tag, attrs):
            if tag == "p":
                self.inside = True
                self.buffer = []

        def handle_endtag(self, tag):
            if tag == "p" and self.inside:
                self.paragraphs.append("".join(self.buffer))
                self.inside = False

        def handle_data(self, data):
            if self.inside:
                self.buffer.append(data)

    parser = Paragraphs()
    parser.feed(html)
    rows = []
    for paragraph in parser.paragraphs:
        name = re.match(r"Hexagram (\d+) is named (.+?) \(([^)]+)\)", paragraph)
        if not name:
            continue
        lower = re.search(r"inner \(lower\) trigram is ([☰-☷])", paragraph)
        upper = re.search(r"outer \(upper\) trigram is ([☰-☷])", paragraph)
        if not lower or (not upper and "outer (upper) trigram is identical" not in paragraph):
            raise ValueError("missing Wikipedia trigram facts")
        rows.append({"king_wen_number": int(name[1]), "name": name[2], "pinyin": name[3],
                     "lower_trigram": lower[1], "upper_trigram": upper[1] if upper else lower[1]})
    if len(rows) != 64 or [r["king_wen_number"] for r in rows] != list(range(1, 65)):
        raise ValueError("Wikipedia extract must contain all 64 ordered entries")
    return rows


def reference_table(refs=None):
    refs = refs or references()
    values = refs["oeis"]["values"]
    if len(values) != 64 or set(values) != set(range(64)):
        raise ValueError("OEIS reference must enumerate every six-bit value once")
    names = refs["chinese_names"]["names_by_lines"]
    english = refs["unicode"]["hexagram_names"]
    if set(english) != {str(i) for i in range(1, 65)}:
        raise ValueError("Unicode reference must enumerate all 64 names")
    if set(names) != {f"{i:06b}" for i in range(64)}:
        raise ValueError("Chinese name reference must cover all 64 structures")
    table = []
    for number, value in enumerate(values, 1):
        # OEIS explicitly assigns the bottom line to bit 0, top to bit 5.
        bits = [(value >> position) & 1 for position in range(6)]
        wiki = refs["wikipedia"]["rows"][number - 1]
        if (wiki["king_wen_number"] != number
                or wiki["lower_trigram"] != TRIGRAMS[tuple(bits[:3])][0]
                or wiki["upper_trigram"] != TRIGRAMS[tuple(bits[3:])][0]):
            raise ValueError(f"Wikipedia/OEIS structure disagrees at hexagram {number}")
        table.append({
            "king_wen_number": number,
            "name": names["".join(map(str, bits))],
            "pinyin": wiki["pinyin"],
            "english": english[str(number)].title(),
            "lines_binary": bits,
            "lower_trigram": TRIGRAMS[tuple(bits[:3])][0],
            "upper_trigram": TRIGRAMS[tuple(bits[3:])][0],
            "unicode": chr(0x4DC0 + number - 1),
        })
    return table


def calculate(throws, table=None):
    """Independent summation, polarity and transformation, bottom to top."""
    if not isinstance(throws, list) or len(throws) != 6:
        raise ValueError("six throws required, bottom to top")
    for coins in throws:
        if (not isinstance(coins, list) or len(coins) != 3
                or any(type(coin) is not int or coin not in (2, 3) for coin in coins)):
            raise ValueError("each throw needs three integer coins, each 2 or 3")
    lines = [sum(coins) for coins in throws]
    bits = [int(line % 2 == 1) for line in lines]
    moving = [i + 1 for i, line in enumerate(lines) if line in (6, 9)]
    transformed = [{6: 7, 9: 8}.get(line, line) for line in lines]
    transformed_bits = [int(line % 2 == 1) for line in transformed]
    lookup = {tuple(row["lines_binary"]): row for row in (table or reference_table())}
    result = {
        "throws_bottom_up": throws,
        "lines_bottom_up": lines,
        "yin_yang_bottom_up": ["yang" if bit else "yin" for bit in bits],
        "moving_lines": moving,
        "moving_count": len(moving),
        "stable_lines": [i for i in range(1, 7) if i not in moving],
        "transformed_lines_bottom_up": transformed,
        "transformed_yin_yang_bottom_up": ["yang" if bit else "yin" for bit in transformed_bits],
        "primary_hexagram": lookup[tuple(bits)],
        # With zero changes there is no distinct relating hexagram.
        "relating_hexagram": lookup[tuple(transformed_bits)] if moving else None,
        "procedure_status": "OK",
        "interpretation_status": "ABSTAIN",
        "interpretation_reason": "No edition-certified text corpus or interpretation/forecast claims supplied.",
        "claims": [],
        "runtime_changed": False,
    }
    result["reading_rule"] = select_reading(result)
    return result


def select_reading(result):
    """Research-only text selectors for unambiguous, sourced rules.

    No selected text is interpreted or integrated into the runtime.
    Unresolved priorities and special six-change cases explicitly abstain.
    """
    count = result["moving_count"]
    primary = result["primary_hexagram"]["king_wen_number"]
    relating = (result["relating_hexagram"] or {}).get("king_wen_number")
    key = str(count) if count < 6 else ("6_special" if primary in (1, 2) else "6_ordinary")
    evidence = reading_evidence()["rules"][key]
    rule = {"moving_count": count, "method": "zhu_xi", "status": evidence["status"],
            "citation": evidence["citation"], "reason": evidence["reason"],
            "ruling_texts": [], "priority": None, "text_corpus_status": "EDITION_CONFLICT"}
    if evidence["status"] != "VERIFIED_SOURCE":
        return rule
    if count == 0:
        rule["ruling_texts"] = [{"type": "judgment", "hexagram": primary}]
    elif count in (1, 2):
        rule["ruling_texts"] = [{"type": "line", "hexagram": primary, "line_number": line}
                                for line in result["moving_lines"]]
        rule["priority"] = "single_line" if count == 1 else "upper_line"
        if count == 2:
            rule["ruling_texts"][-1]["priority"] = "predominant"
    elif count in (4, 5):
        rule["ruling_texts"] = [{"type": "line", "hexagram": relating, "line_number": line}
                                for line in result["stable_lines"]]
        rule["priority"] = "lower_stable_line_in_relating" if count == 4 else "stable_line_in_relating"
        if count == 4:
            rule["ruling_texts"][0]["priority"] = "predominant"
    else:
        rule["ruling_texts"] = [{"type": "judgment", "hexagram": relating}]
        rule["priority"] = "judgment_in_relating"
    return rule


def leaves(value, path=""):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaves(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list) and value and any(isinstance(item, dict) for item in value):
        for index, child in enumerate(value):
            yield from leaves(child, f"{path}[{index}]")
    else:
        yield path, value


def compare_expected(expected, actual):
    """Account for every supplied Qwen field, including unverified citations.

    English labels are translation variants, not alternative bit structures.
    Pinyin is cross-checked against the revision-pinned Wikipedia facts.
    Reading selectors are compared only where Adler's rule is unambiguous.
    """
    comparisons = []
    for path, value in leaves(expected):
        checked = None
        if path.startswith("reading_rule.") and (path.endswith(".source") or path.endswith(".url")):
            status = "EDITION_CONFLICT"
        elif path.startswith("reading_rule.") and path.endswith(".note"):
            status = "UNVERIFIED_COMMENTARY"
        elif (path.startswith("reading_rule.") and path != "reading_rule.moving_count"
              and actual["reading_rule"]["status"] != "VERIFIED_SOURCE"):
            status = "BLOCKED_SOURCE"
        else:
            checked = actual
            for component in path.split("."):
                match = re.fullmatch(r"(\w+)\[(\d+)\]", component)
                if match and isinstance(checked, dict):
                    values = checked.get(match[1], [])
                    checked = values[int(match[2])] if len(values) > int(match[2]) else None
                else:
                    checked = checked.get(component) if isinstance(checked, dict) else None
            if path.endswith(".english") and value != checked:
                status = "TRANSLATION_VARIANT"
            else:
                status = "MATCH" if value == checked else "MISMATCH"
        comparisons.append({"field": path, "qwen": value, "audit": checked, "status": status})
    return comparisons


def audit_qwen_table(table):
    rows = []
    for line in SPEC.read_text().splitlines():
        if re.match(r"\| \d+ \|", line):
            columns = [part.strip() for part in line.strip("|").split("|")]
            number = int(columns[0])
            rows.append({"king_wen_number": number, "name": columns[1],
                         "pinyin": columns[2], "upper_trigram": columns[3],
                         "lower_trigram": columns[4],
                         "lines_binary": [int(bit) for bit in columns[5].split(",")],
                         "unicode": columns[6]})
    if len(rows) != 64 or {r["king_wen_number"] for r in rows} != set(range(1, 65)):
        raise ValueError("Qwen table must contain each King Wen number exactly once")
    checks = []
    for row in rows:
        actual = table[row["king_wen_number"] - 1]
        fields = ("name", "pinyin", "upper_trigram", "lower_trigram", "lines_binary", "unicode")
        mismatches = [field for field in fields if row[field] != actual[field]]
        checks.append({"king_wen_number": row["king_wen_number"],
                       "status": "MISMATCH" if mismatches else "MATCH",
                       "mismatching_fields": mismatches,
                       "external_reference": actual})
    return {"rows": len(rows), "unique_structures": len({tuple(r["lines_binary"]) for r in rows}),
            "numbering_source": "OEIS A102241, pinned external sequence, bottom bit = 2^0",
            "chinese_name_source": "ichingpy pinned secondary dataset, keyed by bottom-up lines",
            "english_name_source": "Unicode NamesList, pinned official data",
            "pinyin_and_trigram_source": "Wikipedia revision 1344901076, all 64 rows independently checked against OEIS",
            "historical_primary_manuscript_checked": False, "checks": checks}


def audit_raw_fragment():
    fragment = SPEC.read_text().split("Текущий `raw_result` (v0.2):", 1)[1].split("```", 2)[1]
    fragment = fragment.removeprefix("json\n").strip()
    try:
        json.loads(fragment)
        valid = True
    except json.JSONDecodeError:
        valid = False
    lines = json.loads(re.search(r'"lines_bottom_up":\s*(\[[^\]]+\])', fragment)[1])
    polarity = re.search(r'"yin_yang_bottom_up":\s*\[([^\]]+)\]', fragment)[1]
    prefix = re.findall(r'"(yin|yang)"', polarity)
    expected = ["yang" if line in (7, 9) else "yin" for line in lines]
    return {
        "source_fragment": fragment, "valid_json": valid,
        "contains_placeholders": "..." in fragment,
        "declared_polarity_prefix": prefix,
        "expected_polarity_from_declared_lines": expected,
        "contradictory_positions": [i + 1 for i, value in enumerate(prefix) if value != expected[i]],
        "claimed_runtime_example": False,
    }


def build_outputs():
    original = json.loads(INPUT.read_text())
    refs = references()
    table = reference_table(refs)
    corrections, differences = [], []
    for index, case in enumerate(original["cases"], 1):
        result = calculate(case["input"]["throws_bottom_up"], table)
        comparisons = compare_expected(case["qwen_expected_unverified"], result)
        corrections.append({"id": f"qwen-{index:02}", "source_case_index": index,
                            "original_label": case["label"], "input": case["input"], "result": result})
        differences.append({"id": f"qwen-{index:02}", "comparisons": comparisons,
                            "checked_mismatch_count": sum(c["status"] == "MISMATCH" for c in comparisons)})
    # New inputs, not edits to any of the eight source cases.
    additions = {
        "audit-four-changes-01": [9, 6, 9, 6, 7, 7],
        "audit-six-changes-ordinary-01": [6, 9, 6, 9, 9, 6],
    }
    coins = {6: [2, 2, 2], 7: [2, 2, 3], 8: [2, 3, 3], 9: [3, 3, 3]}
    for identifier, lines in additions.items():
        throws = [coins[line][:] for line in lines]
        corrections.append({"id": identifier, "source_case_index": None,
                            "input": {"throws_bottom_up": throws}, "result": calculate(throws, table)})
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in (INPUT, SPEC)}
    document = {
        "schema_version": "yijing-independent-audit-v1", "line_order": "bottom-up",
        "source_sha256": hashes,
        "scope": "Offline mechanical research results; no runtime integration or reading rules.",
        "cases": corrections,
    }
    diff = {"source_sha256": hashes, "cases": differences,
            "qwen_table_audit": audit_qwen_table(table), "current_raw_result_audit": audit_raw_fragment(),
            "document_conflicts": [
                {"case": "qwen-05", "field": "moving_count", "qwen_label": 4, "audit": 5},
                {"case": "qwen-05", "field": "reading_rule.priority",
                 "json_predominant_line": 6, "prose_and_outer_priority_line": 5,
                 "status": "INTERNAL_CONTRADICTION; neither priority applied"},
                {"field": "Legge URL template", "prose": "ic{N}.htm without leading zero",
                 "examples": "ic01.htm, ic02.htm, ic05.htm, ic09.htm",
                 "status": "INTERNAL_CONTRADICTION; actual pages BLOCKED_SOURCE"},
            ]}
    return {"corrected_results.json": document, "discrepancies.json": diff}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare regenerated JSON with committed artifacts")
    args = parser.parse_args()
    outputs = build_outputs()
    for filename, data in outputs.items():
        content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path = AUDIT / filename
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise SystemExit(f"FAIL: stale/missing artifact: {path.relative_to(ROOT)}")
        else:
            path.write_text(content)
    cases = outputs["corrected_results.json"]["cases"]
    diffs = outputs["discrepancies.json"]["cases"]
    print(f"Mechanical audit: {len(cases)} cases; moving counts {sorted({c['result']['moving_count'] for c in cases})}")
    print(f"Qwen mismatching checked fields: {sum(c['checked_mismatch_count'] for c in diffs)}")
    checked = outputs["discrepancies.json"]["qwen_table_audit"]
    print(f"External table comparison: {checked['rows']} rows; {checked['unique_structures']} unique structures; "
          f"{sum(c['status'] == 'MISMATCH' for c in checked['checks'])} mismatching rows")
    print("Zhu Xi: verified rules 0/1/2/4/5/6 ordinary; BLOCKED_SOURCE for 3 and 6 special")
    print("Interpretation: ABSTAIN; Legge corpus: EDITION_CONFLICT; runtime unchanged")
    print("Artifacts: " + ("MATCH" if args.check else "WRITTEN"))


if __name__ == "__main__":
    main()
