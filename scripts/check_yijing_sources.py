"""Fetch pinned factual sources and record access to the proposed reading corpus.

TLS verification stays enabled. --fetch is explicit because normal audit/test
runs must work offline. A fetched document is NOT a verified reading rule.
"""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import urllib.error
import urllib.request

from yijing_audit import AUDIT, INPUT, extract_wikipedia_facts, references

PROPOSED = {
    "wikipedia_table": "https://en.wikipedia.org/wiki/List_of_hexagrams_of_the_I_Ching",
    "adler_original_url": "http://www2.kenyon.edu/Depts/Religion/Fac/Adler/Writings/Qimeng-3.pdf",
    "adler_https": "https://www2.kenyon.edu/Depts/Religion/Fac/Adler/Writings/Qimeng-3.pdf",
    "legge_index": "https://sacred-texts.com/ich/index.htm",
    "legge_1882_pdf": "https://www.biroco.com/yijing/Legge1882.pdf",
    "legge_title": "https://sacred-texts.com/book/the-i-ching/title-page",
    "legge_unpadded_1": "https://sacred-texts.com/ich/ic1.htm",
    "legge_unpadded_9": "https://sacred-texts.com/ich/ic9.htm",
}


def fetch(item):
    label, url = item
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "DIS-Yijing-Research-Audit/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            result = {"label": label, "url": url, "final_url": response.url,
                    "http_status": response.status, "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(), "status": "FETCHED_NOT_REVIEWED"}
            if label == "wikipedia":
                result["extracted_facts"] = extract_wikipedia_facts(content.decode())
            elif label == "oeis":
                result["extracted_facts"] = [int(value) for line in content.decode().splitlines()
                                             if line.startswith(("%S A102241 ", "%T A102241 ", "%U A102241 "))
                                             for value in line.split(" ", 2)[2].strip(",").split(",")]
            elif label == "unicode":
                result["extracted_facts"] = {
                    str(int(code, 16) - 0x4DC0 + 1): name
                    for code, name in re.findall(r"^(4D[C-F][0-9A-F])\tHEXAGRAM FOR (.+)$", content.decode(), re.M)}
            elif label == "chinese_names":
                result["extracted_facts"] = {"".join(map(str, ast.literal_eval(key))): value["name"]
                                             for key, value in json.loads(content)["hexagrams"].items()}
            return result
    except urllib.error.HTTPError as error:
        return {"label": label, "url": url, "status": f"HTTP_{error.code}", "error": str(error)}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"label": label, "url": url, "status": "BLOCKED_SOURCE", "error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="perform HTTPS source checks and write an access report")
    args = parser.parse_args()
    if not args.fetch:
        parser.error("use --fetch to perform network checks; offline mechanical audit is yijing_audit.py")
    refs = references()
    pinned = [(name, data["url"]) for name, data in refs.items()]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pinned_results = list(pool.map(fetch, pinned))
    for result in pinned_results:
        expected = refs[result["label"]]["sha256"]
        if result.get("sha256"):
            if result["label"] == "wikipedia":
                # Keep the originally observed raw SHA; do not rewrite it to match
                # a new response. A pinned article's HTML shell changes independently
                # of its revision. Check all extracted facts against the original.
                result["raw_html_sha256_matches"] = result["sha256"] == expected
                result["status"] = ("VERIFIED_FACTS" if result.pop("extracted_facts") == refs["wikipedia"]["rows"]
                                    else "FACT_MISMATCH")
            else:
                result["status"] = "VERIFIED_SHA256" if result["sha256"] == expected else "CHECKSUM_MISMATCH"
                expected_facts = refs[result["label"]][{
                    "oeis": "values", "unicode": "hexagram_names", "chinese_names": "names_by_lines"
                }[result["label"]]]
                if result.pop("extracted_facts") != expected_facts:
                    result["status"] = "FACT_MISMATCH"
    cases = json.loads(INPUT.read_text())["cases"]
    urls = sorted({text["url"] for case in cases
                   for text in case["qwen_expected_unverified"]["reading_rule"]["ruling_texts"]})
    # Check all actual cited links, not just whether a hostname answers.
    requests = list(PROPOSED.items()) + [("qwen_cited_url", url) for url in urls]
    with ThreadPoolExecutor(max_workers=4) as pool:
        access = list(pool.map(fetch, requests))
    report = {"checked_on": "2026-10-14", "pinned_sources": pinned_results,
              "proposed_sources": access,
        "reading_rules_status": "See reading_evidence.json for manual content review and unresolved rules",
              "note": "Access alone never certifies page identity, edition or a reading rule; review document content."}
    path = AUDIT / "sources/source_access.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for result in pinned_results + access:
        print(result["status"], result["url"])
    if any(r["status"] not in ("VERIFIED_SHA256", "VERIFIED_FACTS") for r in pinned_results):
        raise SystemExit("FAIL: at least one pinned factual source could not be verified")
    print(f"Pinned factual sources: {len(pinned_results)}/{len(pinned_results)} verified; access does not certify content.")


if __name__ == "__main__":
    main()
