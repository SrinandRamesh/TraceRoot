"""TraceRoot API - dataset-driven incident investigation and recurrence prevention."""

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import report
import storage
from dataset_pipeline import MAX_BYTES, DatasetError, normalize, parse_csv_bytes, parse_json_records, preview
from investigation import analyze, compare_fix

app = FastAPI(title="TraceRoot API", description="Dataset-driven incident investigation", version="0.6.0")

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

storage.init_db()

SAMPLES_DIR = Path(__file__).with_name("samples")
SAMPLES = {
    "database_overload.csv": "Synthetic: checkout-api latency rises while DB timeouts and pool utilization climb.",
    "application_exception.csv": "Synthetic: repeated exceptions with HTTP 500s mixed into normal traffic (duplicates, gaps).",
    "cascading_latency.csv": "Synthetic: one service slows first, others follow later; out-of-order and missing values.",
    "database_overload_after_fix.csv": "Synthetic: post-fix data for database_overload (use in Fix Validation).",
}
LOCAL_WORKSPACE = "local"
STATUSES = ("Open", "Investigating", "Monitoring", "Resolved", "No issue found")
REC_STATUSES = ("open", "in_progress", "completed")


def source_keys() -> dict[str, str]:
    """Authorized sources from TRACEROOT_SOURCE_KEYS='source_id:key,other:key2'."""
    pairs = [p.split(":", 1) for p in os.environ.get("TRACEROOT_SOURCE_KEYS", "").split(",") if ":" in p]
    return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}


async def read_upload(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".txt")):
        raise HTTPException(400, "Only .csv files are supported.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than the 10 MB limit.")
    return data


def run_pipeline(headers, rows, dataset_name: str, source: str, workspace: str, content_hash: str,
                 group_with_active: bool) -> dict[str, Any]:
    """validate → normalize → analyze → save. Shared by UI uploads, samples and authorized sources."""
    try:
        records, quality = normalize(headers, rows)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    result = analyze(records, quality)
    result["data_quality"] = quality
    problem = result["problem"]
    top = result["hypotheses"][0]["hypothesis"] if result["hypotheses"] else "none"
    title = (problem["title"] if problem else f"No significant problem in {dataset_name}")
    record = {"workspace": workspace, "title": title, "dataset_name": dataset_name, "source": source,
              "content_hash": content_hash, "signature": f"{result['primary_service']}|{top}" if problem else None,
              "status": "Open" if problem else "No issue found", "outcome": result["status"],
              "severity": result["severity"], "primary_service": result["primary_service"], "result": result}
    if group_with_active and record["signature"]:
        existing = storage.find_active_by_signature(workspace, record["signature"])
        if existing:
            storage.update_with_new_data(existing, record, f"New dataset {dataset_name} from {source} matched this active "
                                                           "investigation; analysis refreshed instead of opening a duplicate.")
            return {"investigation": require(existing), "created": False, "grouped": True}
    inv_id = storage.save_investigation(record, f"Dataset {dataset_name} ({quality['rows_processed']} rows) from {source} analysed.")
    return {"investigation": require(inv_id), "created": True, "grouped": False}


def cause_family(inv: dict[str, Any]) -> str | None:
    hyps = inv["result"]["hypotheses"]
    if inv["outcome"] == "no_significant_problem" or not hyps:
        return None
    return re.split(r" (?:in|on|originating|introduced) ", hyps[0]["hypothesis"])[0].lower()


def similar_past(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """Pattern memory: earlier investigations with the same leading-cause family or the same affected component."""
    family = cause_family(inv)
    if not family:
        return []
    mine = set((inv["result"].get("problem") or {}).get("affected_components", []))
    matches = []
    for item in storage.list_investigations(inv["workspace"]):
        if item["id"] == inv["id"] or item["received_at"] > inv["received_at"]:
            continue
        other = storage.get_investigation(item["id"])
        same_family = cause_family(other) == family
        shared = sorted(mine & set(item.get("affected_components") or []))
        if not same_family:
            continue
        validated = [v for v in other["validations"] if v["result"] == "improved"]
        matches.append({"id": item["id"], "dataset_name": item["dataset_name"], "received_at": item["received_at"],
                        "status": item["status"], "leading_cause": other["result"]["hypotheses"][0]["hypothesis"],
                        "same_cause_family": same_family, "shared_components": shared,
                        "confirmed_fix": validated[0]["fix_description"] if validated else None})
    return sorted(matches, key=lambda m: (m["confirmed_fix"] is None, not m["same_cause_family"]))[:5]


def require(inv_id: str) -> dict[str, Any]:
    inv = storage.get_investigation(inv_id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    inv["similar_past"] = similar_past(inv)
    return inv


@app.get("/")
def root():
    return {"app": "TraceRoot", "status": "running", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "traceroot-backend", "version": app.version, "persistence": "sqlite",
            "investigation_count": len(storage.list_investigations()), "authorized_sources": len(source_keys())}


@app.get("/api/workspaces")
def list_workspaces():
    items = [{"id": LOCAL_WORKSPACE, "name": "Local uploads", "data_mode": "uploaded datasets"}]
    items += [{"id": s, "name": f"Source: {s}", "data_mode": "authorized source"} for s in source_keys()]
    return {"workspaces": items}


@app.get("/api/samples")
def list_samples():
    return {"samples": [{"name": n, "description": d, "synthetic": True} for n, d in SAMPLES.items()
                        if (SAMPLES_DIR / n).exists()]}


@app.get("/api/samples/{name}")
def get_sample(name: str):
    if name not in SAMPLES or not (SAMPLES_DIR / name).exists():
        raise HTTPException(404, "Sample not found")
    return FileResponse(SAMPLES_DIR / name, media_type="text/csv", filename=name)


@app.post("/api/datasets/preview")
async def preview_dataset(file: UploadFile = File(...)):
    try:
        headers, rows = parse_csv_bytes(await read_upload(file))
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    return {"filename": file.filename, **preview(headers, rows)}


@app.post("/api/datasets/analyze", status_code=201)
async def analyze_dataset(file: UploadFile = File(...), source_label: str = Form("manual upload")):
    data = await read_upload(file)
    try:
        headers, rows = parse_csv_bytes(data)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    return run_pipeline(headers, rows, file.filename or "upload.csv", source_label[:60] or "manual upload",
                        LOCAL_WORKSPACE, hashlib.sha256(data).hexdigest(), group_with_active=False)


@app.post("/api/sources/{source_id}/datasets", status_code=201)
async def ingest_from_source(source_id: str, request: Request, x_traceroot_key: str | None = Header(default=None)):
    """Automatic processing for an authorized source. Accepts text/csv body, multipart 'file', or JSON {records:[...]}."""
    keys = source_keys()
    if not keys:
        raise HTTPException(503, "No authorized sources are configured (set TRACEROOT_SOURCE_KEYS).")
    expected = keys.get(source_id)
    if not expected or not x_traceroot_key or not hmac.compare_digest(expected, x_traceroot_key):
        raise HTTPException(401, "Unknown source or invalid X-TraceRoot-Key.")
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("application/json"):
            body = await request.json()
            records = body.get("records") if isinstance(body, dict) else None
            if not isinstance(records, list):
                raise HTTPException(422, "JSON body must be {\"records\": [ ... ]}.")
            headers, rows = parse_json_records(records)
            data, name = repr(records).encode(), body.get("dataset_name") or "records.json"
        elif ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise HTTPException(422, "Multipart body must include a 'file' field.")
            data, name = await read_upload(upload), upload.filename or "upload.csv"
            headers, rows = parse_csv_bytes(data)
        else:
            data = await request.body()
            name = request.headers.get("x-dataset-name", "dataset.csv")
            headers, rows = parse_csv_bytes(data)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    content_hash = hashlib.sha256(data).hexdigest()
    duplicate = storage.find_by_hash(source_id, content_hash)
    if duplicate:
        return {"investigation": storage.get_investigation(duplicate), "created": False, "grouped": False,
                "duplicate": True, "message": "Identical dataset already analysed; no new investigation created."}
    return run_pipeline(headers, rows, name[:120], f"source:{source_id}", source_id, content_hash, group_with_active=True)


@app.get("/api/investigations")
def list_investigations(workspace: str | None = None):
    items = storage.list_investigations(workspace)
    return {"count": len(items), "investigations": items}


@app.get("/api/investigations/{inv_id}")
def get_investigation(inv_id: str):
    return require(inv_id)


@app.delete("/api/investigations/{inv_id}", status_code=204)
def delete_investigation(inv_id: str):
    require(inv_id)
    storage.delete_investigation(inv_id)


class StatusUpdate(BaseModel):
    status: str


@app.patch("/api/investigations/{inv_id}/status")
def update_status(inv_id: str, payload: StatusUpdate):
    inv = require(inv_id)
    if payload.status not in STATUSES:
        raise HTTPException(400, f"Status must be one of {', '.join(STATUSES)}")
    if payload.status == "Resolved" and not any(v["result"] == "improved" for v in inv["validations"]):
        raise HTTPException(409, "Cannot resolve: no fix validation has shown that the original findings returned to baseline.")
    storage.set_status(inv_id, payload.status, f"Status changed from {inv['status']} to {payload.status}.")
    return require(inv_id)


@app.get("/api/investigations/{inv_id}/report", response_class=HTMLResponse)
def investigation_report(inv_id: str, autoprint: bool = False):
    return HTMLResponse(report.render(require(inv_id), auto_print=autoprint))


@app.post("/api/investigations/{inv_id}/validations", status_code=201)
async def validate_fix(inv_id: str, file: UploadFile = File(...), fix_description: str = Form(...)):
    inv = require(inv_id)
    if inv["outcome"] == "no_significant_problem":
        raise HTTPException(409, "This investigation found no problem, so there is nothing to validate.")
    if len(fix_description.strip()) < 3:
        raise HTTPException(422, "Describe the fix being validated.")
    try:
        headers, rows = parse_csv_bytes(await read_upload(file))
        records, quality = normalize(headers, rows)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    outcome = compare_fix(inv["result"], records, quality)
    storage.add_validation(inv_id, fix_description.strip()[:300], file.filename or "post-fix.csv", outcome)
    if outcome["result"] == "improved" and inv["status"] in ("Open", "Investigating"):
        storage.set_status(inv_id, "Monitoring", "Fix validation showed measured improvement; moved to Monitoring.")
    elif outcome["result"] in ("worsened", "inconclusive") and inv["status"] == "Monitoring":
        storage.set_status(inv_id, "Investigating", "Latest fix validation did not confirm improvement.")
    return {"validation": outcome, "investigation": require(inv_id)}


@app.get("/api/prevention")
def prevention(workspace: str | None = None):
    recs = storage.list_recommendations(workspace or LOCAL_WORKSPACE)
    return {"count": len(recs), "recommendations": recs}


class RecStatus(BaseModel):
    status: str


@app.patch("/api/recommendations/{rec_id}")
def update_recommendation(rec_id: int, payload: RecStatus):
    if payload.status not in REC_STATUSES:
        raise HTTPException(400, f"Status must be one of {', '.join(REC_STATUSES)}")
    if not storage.set_recommendation_status(rec_id, payload.status):
        raise HTTPException(404, "Recommendation not found")
    return {"id": rec_id, "status": payload.status}
