"""Read-only fetch check. Does not repeat the manual scientific content review."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, help="optional local copies for manual review")
    args = parser.parse_args()
    if args.cache_dir:
        args.cache_dir.mkdir(parents=True, exist_ok=True)
    sources = json.loads(Path(__file__).with_name("sources.json").read_text())
    sources = [s for s in sources if s["status"] == "CONTENT_REVIEWED"]
    pdfs = {"proper", "shannon", "causal", "gr", "retro", "ctc", "bell", "hoeffding_full"}

    def fetch(source):
        try:
            request = urllib.request.Request(source["url"], headers={"User-Agent": "DIS-Research/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            digest = hashlib.sha256(raw).hexdigest()
            if source["id"] in pdfs or source["id"] == "rfc_text":
                status = "HASH_MATCH" if digest == source["sha256"] else "HASH_MISMATCH_REQUIRES_REVIEW"
            else:
                status = "HTML_FETCHED_CONTENT_REVIEW_NOT_REPEATED"
            if args.cache_dir:
                (args.cache_dir / (source["id"] + (".pdf" if source["id"] in pdfs else ".txt"))).write_bytes(raw)
            return {"id": source["id"], "url": source["url"], "status": status,
                    "sha256": digest, "same_bytes_as_original_review": digest == source["sha256"]}
        except (OSError, ValueError) as error:
            return {"id": source["id"], "url": source["url"], "status": "UNAVAILABLE", "error": str(error)}

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, sources))
    print(json.dumps(results, indent=2))
    return int(any(r["status"] in ("UNAVAILABLE", "HASH_MISMATCH_REQUIRES_REVIEW") for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
