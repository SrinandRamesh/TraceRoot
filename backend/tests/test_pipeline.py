"""Backend tests: run with `python -m pytest tests -q` from the backend folder."""

import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TRACEROOT_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["TRACEROOT_SOURCE_KEYS"] = "acme:test-key"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)
SAMPLES = ROOT / "samples"


def upload(name: str, content: bytes):
    return client.post("/api/datasets/analyze", files={"file": (name, content, "text/csv")})


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def test_starts_empty():
    assert client.get("/api/investigations").json()["count"] == 0
    assert client.get("/api/prevention").json()["count"] == 0


def test_samples_produce_different_findings():
    results = {n: upload(n, sample(n)).json()["investigation"] for n in
               ("database_overload.csv", "application_exception.csv", "cascading_latency.csv")}
    tops = {n: r["result"]["hypotheses"][0]["hypothesis"] for n, r in results.items()}
    assert tops["database_overload.csv"].startswith("Database saturation")
    assert tops["application_exception.csv"].startswith("Application exception in orders-api")
    assert tops["cascading_latency.csv"].startswith("Degradation originating in inventory-service")
    assert all(r["recommendations"] for r in results.values())


def test_results_depend_on_content_not_filename():
    r = upload("database_overload.csv", sample("application_exception.csv")).json()["investigation"]
    assert r["result"]["hypotheses"][0]["hypothesis"].startswith("Application exception")


def test_normal_data_creates_no_problem():
    rng = random.Random(3)
    rows = "\n".join(f"2026-01-01T10:{i // 60:02d}:{i % 60:02d},web,{rng.gauss(100, 8):.0f}" for i in range(120))
    r = upload("normal.csv", f"timestamp,service,latency_ms\n{rows}\n".encode()).json()["investigation"]
    assert r["outcome"] == "no_significant_problem" and r["result"]["problem"] is None


def test_messy_and_invalid_inputs():
    assert upload("bad.csv", b"a,b\n1,2\n").status_code == 422
    assert upload("empty.csv", b"").status_code == 422
    assert client.post("/api/datasets/analyze", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    messy = b"Time,Service Name,Response_Time\nnot-a-date,api,12\n2026-01-01 10:00:00,API,abc\n2026-01-01 10:00:00,API,abc\n"
    q = upload("messy.csv", messy).json()["investigation"]["result"]["data_quality"]
    assert q["duplicate_rows_removed"] == 1 and q["invalid_timestamps"] == 1 and q["invalid_values_by_field"]["latency_ms"] == 1


def test_fix_validation_and_resolve_guard():
    inv = upload("database_overload.csv", sample("database_overload.csv")).json()["investigation"]
    assert client.patch(f"/api/investigations/{inv['id']}/status", json={"status": "Resolved"}).status_code == 409
    bad = client.post(f"/api/investigations/{inv['id']}/validations", data={"fix_description": "noop"},
                      files={"file": ("x.csv", sample("application_exception.csv"), "text/csv")}).json()
    assert bad["validation"]["result"] == "insufficient_data"
    good = client.post(f"/api/investigations/{inv['id']}/validations", data={"fix_description": "pool 20->40"},
                       files={"file": ("after.csv", sample("database_overload_after_fix.csv"), "text/csv")}).json()
    assert good["validation"]["result"] == "improved" and good["investigation"]["status"] == "Monitoring"
    assert client.patch(f"/api/investigations/{inv['id']}/status", json={"status": "Resolved"}).status_code == 200


def test_authorized_source_ingestion_and_dedupe():
    body = sample("cascading_latency.csv")
    assert client.post("/api/sources/acme/datasets", content=body, headers={"Content-Type": "text/csv"}).status_code == 401
    h = {"Content-Type": "text/csv", "X-TraceRoot-Key": "test-key"}
    first = client.post("/api/sources/acme/datasets", content=body, headers=h).json()
    again = client.post("/api/sources/acme/datasets", content=body, headers=h).json()
    assert first["created"] and again["duplicate"] and again["investigation"]["id"] == first["investigation"]["id"]


def test_report_renders():
    inv_id = client.get("/api/investigations").json()["investigations"][0]["id"]
    html = client.get(f"/api/investigations/{inv_id}/report").text
    assert "Incident report" in html and inv_id in html and "window.print" not in html
    assert "window.print" in client.get(f"/api/investigations/{inv_id}/report?autoprint=true").text


def test_pattern_memory_links_similar_past_investigation():
    first = upload("db_week1.csv", sample("database_overload.csv")).json()["investigation"]
    client.post(f"/api/investigations/{first['id']}/validations", data={"fix_description": "pool 20->40"},
                files={"file": ("after.csv", sample("database_overload_after_fix.csv"), "text/csv")})
    second = upload("db_week2.csv", sample("database_overload.csv") + b"\n").json()["investigation"]
    match = next(m for m in second["similar_past"] if m["id"] == first["id"])
    assert match["same_cause_family"] and match["confirmed_fix"] == "pool 20->40"
