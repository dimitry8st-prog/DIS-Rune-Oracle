"""Read-only recheck of source access; HTTP success still requires content review.

No local records are overwritten. No TLS checks are disabled. No code downloaded
from these URLs is executed. Full text stays outside the repository.
"""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def check(row):
    result={"id":row["id"],"url":row["url"],"accessed_at":datetime.now(timezone.utc).isoformat(),"content_verified":False}
    url=urllib.parse.quote(row['url'],safe=':/?=&%()')
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'DIS-Research-Source-Audit/0.3'})
        with urllib.request.urlopen(request,timeout=18) as response:
            body=response.read(3_000_000)
            result.update(http_status=response.status,final_url=response.url,sha256=hashlib.sha256(body).hexdigest(),status='FETCHED_REQUIRES_CONTENT_REVIEW')
    except Exception as exc:result.update(status='BLOCKED_SOURCE',error=str(exc))
    return result


if __name__=='__main__':
    rows=json.loads((ROOT/'research/audit/four_cores/source_access.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:results=list(pool.map(check,rows))
    print(json.dumps(results,ensure_ascii=False,indent=2))
