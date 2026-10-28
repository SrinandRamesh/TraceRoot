# TraceRoot AI

Evidence-based incident investigation for distributed systems. Upload operational data (metrics and/or logs as
CSV). TraceRoot cleans it, compares every signal with its own baseline, and reports **what is wrong, where, when
it started, the evidence, the most likely cause, how certain that is, and what to do next**. Findings feed fix
validation (using post-fix data) and preventive recommendations. **Hackathon prototype**, not a production monitor.

```
Dataset → Problem identified → Evidence → Likely root cause → Next action → Fix validation → Prevention
```

There are no built-in incidents. A fresh start shows *"No investigations yet. Upload a dataset or connect a data
source to begin."* The sample CSVs are **synthetic** and go through the same pipeline as any other file. Nothing in
the code depends on a file's name.

## Layout
```
TraceRoot/
├── backend/
│   ├── main.py               FastAPI routes (v0.6.0)
│   ├── dataset_pipeline.py   Source adapters (CSV / JSON records), column aliasing, cleaning, data-quality report
│   ├── investigation.py      Anomalies, error/log analysis, ranked hypotheses, problem statement, fix comparison
│   ├── storage.py            SQLite persistence (investigations, recommendations, validations, activity)
│   ├── report.py             HTML investigation report (print to PDF from the browser)
│   ├── connector_example.py  Example authorized connector (pushes a CSV to the source endpoint)
│   ├── samples/              database_overload.csv, application_exception.csv, cascading_latency.csv,
│   │                         database_overload_after_fix.csv, generate_samples.py
│   ├── tests/test_pipeline.py
│   ├── requirements.txt, .env.example
├── frontend/                 React + TypeScript + Vite (TraceRoot theme and mascot)
│   └── src/App.tsx, api.ts, types.ts, App.css, features.css, components/
├── README.md, SETUP_WINDOWS.md
```

## Run (Windows PowerShell). Details are in SETUP_WINDOWS.md
```powershell
# Terminal 1
cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000        # API docs: http://127.0.0.1:8000/docs
# Terminal 2
cd frontend; npm install; npm run dev         # http://localhost:5173
```
Tests: `cd backend; python -m pytest tests -q`. Frontend build: `cd frontend; npm run build`.

## How the analysis works
1. **Normalize.** Column names are matched case-insensitively against aliases. For example `timestamp/time/datetime/event_time/when`, `service/service_name/component/app`, `latency_ms/latency/response_time/duration_ms`, `error_count/errors`, `timeout_count/db_timeouts`, `status_code/http_status/status`, `cpu_usage/cpu_percent`, `memory_usage/memory_percent`, `connection_pool_pct/db_pool_pct`, `request_rate/requests_per_second`, `log_level/level`, `message/log_message`, `stack_trace/exception`, `event_type`. Unknown columns are listed as ignored.
   - Numbers stored as text (`"120ms"`, `"45%"`) are parsed.
   - 0–1 fractions in percentage columns are rescaled to percent.
   - Timestamps are accepted as ISO, common date formats or epoch values. Values without a timezone are treated as UTC.
   - Service names are normalized (`Order Service` → `order-service`).
   - Exact duplicate rows are removed and counted.
   - Missing cells are never filled in. Invalid values are excluded and counted.
   - Rows are sorted by time, and out-of-order rows are reported.
2. **Anomalies.** Each `(service, metric)` series uses the median and scaled MAD of its first 40% of samples as the baseline.
   - A value is flagged when its robust z-score is ≥ 3.5, or when a percentage metric is ≥ 90% (saturation).
   - Flagged points close together are grouped into one episode. An episode needs ≥ 3 points to count as sustained.
   - Baselines with no variation and series with fewer than 8 values are handled explicitly and reported.
3. **Errors and logs.** A row counts as an error if its status is ≥ 500, its log level is error, fatal or critical, `error_count` is above 0, it has a stack trace, or (in log-only data) its message contains error words.
   - For each service, the error rate after onset is compared with the early period.
   - Repeated exceptions are grouped by exception class or by normalized message.
   - Messages mentioning deploy, release or rollout are treated as change events.
4. **Hypotheses.** Each rule adds explained points once:
   - database saturation (pool, timeouts, overlapping latency)
   - application exception (repeated signature, HTTP 5xx, concentration in one component)
   - change or regression (a change event 0–60 minutes before the first symptom)
   - propagation (one service's latency rises first and others follow; inferred from timing only)
   - CPU or memory saturation (plus out-of-memory logs)
   - traffic surge
   - unexplained deviation

   Contradicting points are listed. If the top score is below 6, the result is *"Insufficient evidence to identify a reliable root cause."* together with what is missing. **Scores are not probabilities, and correlation is not proof.**
5. **Problem statement and severity.** Both are built from the strongest symptom and the symptoms overlapping it.
   - Severity: Critical if the error rate is ≥ 25%, or latency is ≥ 5× baseline across ≥ 2 components. High if the error rate is ≥ 10% or latency is ≥ 3×. Otherwise Medium or Low. The reasoning is shown.
   - A dataset with no sustained deviation is recorded as *No significant problem*. No incident is invented.
6. **Fix validation.** The post-fix CSV is normalized the same way. Each original finding is re-measured.
   - *Improved* means the metric is back within its original baseline range and at least 20% better than during the incident.
   - The other results are *worsened*, *inconclusive* and *not measured*.
   - An investigation can only be marked Resolved after an *improved* validation (otherwise the API returns HTTP 409).
7. **Prevention.** Recommendations are created from the hypotheses that have evidence. Each one records the problem, the evidence, a priority, a link to its investigation, and a status (open / in progress / completed).

## Navigation (and why)
| Tab | Purpose |
|---|---|
| Overview | Real counts, most important open finding, recent investigations (empty state before first upload) |
| Investigations | All analysed datasets, one record per dataset, searchable |
| Analyze Data | Upload / drag-drop CSV, sample datasets, preview with detected column mapping and types |
| Investigation | Problem statement, affected components, severity, likely cause, next action, evidence, chart, hypotheses, anomaly table, timeline, data quality, report |
| Fix Validation | Compare post-fix data with the original baseline and incident period |
| Prevention | Evidence-linked preventive actions with status tracking |

**Removed:** the *Service Map* (it drew a hard-coded, made-up topology); onset-order propagation now appears inside the investigation, labelled as inferred. Also removed: the demo incidents (INC-001..003), the simulation buttons, the synthetic Isolation Forest card, and the single-metric demo ingestion.

## API
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health and counts |
| GET | `/api/samples`, `/api/samples/{name}` | List / download synthetic samples |
| POST | `/api/datasets/preview` | multipart `file` → columns, mapping, types, first rows |
| POST | `/api/datasets/analyze` | multipart `file` → full pipeline → saved investigation |
| GET | `/api/investigations`, `/api/investigations/{id}` | List / full record |
| PATCH | `/api/investigations/{id}/status` | Open / Investigating / Monitoring / Resolved (guarded) |
| DELETE | `/api/investigations/{id}` | Remove an investigation |
| GET | `/api/investigations/{id}/report[?download=true]` | HTML report |
| POST | `/api/investigations/{id}/validations` | multipart `file` + `fix_description` → fix comparison |
| GET | `/api/prevention`; PATCH `/api/recommendations/{id}` | Recommendations and status |
| POST | `/api/sources/{source_id}/datasets` | Authorized automatic ingestion (see below) |

## Company data sources (authorized ingestion)
Sources are configured with `TRACEROOT_SOURCE_KEYS="sourceA:longRandomKey,sourceB:otherKey"`. A source sends
`POST /api/sources/{source_id}/datasets` with header `X-TraceRoot-Key`, as a `text/csv` body, as multipart `file`, or as JSON
`{"dataset_name": "...", "records": [{...}, ...]}`. The data is processed automatically by the same pipeline. Identical files are de-duplicated (by content hash). A new dataset whose finding matches an active investigation from that source (same primary service and same top hypothesis) refreshes that investigation instead of opening a duplicate.
Wrong or missing keys return 401. If no sources are configured, the endpoint is disabled (503). See `connector_example.py`.
**To add a new format**, write an adapter in `dataset_pipeline.py` that returns `(headers, rows)`, as
`parse_csv_bytes` and `parse_json_records` do, or add column aliases to `ALIASES`. The analysis code stays the same.
No external company, cloud or monitoring platform is connected in this prototype.

## Demo script (about 4 minutes)
1. Overview: empty, with no fake incidents.
2. Analyze Data → *Load for analysis* on `database_overload.csv`. Show the preview (messy headers mapped, the *Region* column ignored) → *Analyze dataset*.
3. Investigation: read the problem statement, then go through *Likely root cause* → *Recommended next action* → *Evidence* → chart → ranked hypotheses → data quality.
4. Repeat with `application_exception.csv` (a NullPointerException with HTTP 500s; the deployment shown as a weak lead) and `cascading_latency.csv` (inventory-service degrades first; onset order shown). Each gives a different finding.
5. Load `database_overload_after_fix.csv`: *No significant problem detected*, and no incident is created.
6. Try setting the database investigation to *Resolved* → refused. Fix Validation → pick it, upload `database_overload_after_fix.csv` → *Improved* → status becomes Monitoring → Resolved is now allowed.
7. Prevention: the recommendations link back to their investigations; mark one *In progress*.
8. *View report* / *Download* on the investigation.

## Limitations
- Root-cause ranking is transparent rules over correlations in one dataset. It is not a trained model, and it cannot confirm causation.
- The baseline is taken from the early part of each dataset. If the problem is present from the first row, it can be under-detected.
- Service dependencies are not supplied by the data. Propagation is inferred from timing and labelled as such.
- No user authentication for the local UI. Source ingestion uses shared keys from environment variables, with no rate limiting, key rotation or TLS termination. It is not production-secure.
- Uploaded files are parsed in memory and not stored. Only the analysis results are kept in `backend/traceroot.db` (delete the file to reset).
