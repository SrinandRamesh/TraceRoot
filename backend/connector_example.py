"""Example authorized connector: pushes a CSV export to TraceRoot's source ingestion endpoint.

1. Start the backend with an authorized source, e.g. (PowerShell):
       $env:TRACEROOT_SOURCE_KEYS="acme:change-me"; uvicorn main:app --port 8000
2. Run:  python connector_example.py --source acme --key change-me --file samples/cascading_latency.csv

A real connector (cron job, log shipper webhook, warehouse export) would send the same request.
Identical files are de-duplicated; a new file matching an active finding refreshes that investigation.
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--source", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    path = Path(args.file)
    request = urllib.request.Request(
        f"{args.api.rstrip('/')}/api/sources/{args.source}/datasets",
        data=path.read_bytes(),
        headers={"Content-Type": "text/csv", "X-TraceRoot-Key": args.key, "X-Dataset-Name": path.name},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode()}")
    inv = body["investigation"]
    state = "duplicate" if body.get("duplicate") else "updated existing" if body.get("grouped") else "created"
    print(f"{state}: {inv['id']} [{inv['severity']}] {inv['title']}")


if __name__ == "__main__":
    main()
