# TraceRoot AI – Windows setup guide

## 1. Prerequisites
| Tool | Version | Check |
|---|---|---|
| Python | 3.10 – 3.13 | `python --version` |
| Node.js | 20.19+ or 22.12+ (Vite 8) | `node --version` |

## 2. Extract
Extract `Main_Code.zip` and open the `TraceRoot` folder in VS Code.

## 3. Backend (Terminal 1)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
- If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again.
- Swagger UI: http://127.0.0.1:8000/docs
- `traceroot.db` is created on first start and holds no demo data. Delete it to reset.
- Run the tests: `python -m pytest tests -q`
- Optional, to enable authorized source ingestion: `$env:TRACEROOT_SOURCE_KEYS="acme:change-me"` before `uvicorn`, then
  `python connector_example.py --source acme --key change-me --file samples\cascading_latency.csv`

## 4. Frontend (Terminal 2)
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173. The sidebar should say **Backend connected**.
- The API address defaults to `http://127.0.0.1:8000`. To change it, copy `.env.example` to `.env` and edit `VITE_API_BASE`.
- Production build: `npm run build`

## 5. Use it
Analyze Data → load a sample (in `backend\samples\`) or drop your own CSV → **Analyze dataset**.
Regenerate the samples with: `python samples\generate_samples.py`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| "Backend unavailable" | Backend not running on 8000, or `VITE_API_BASE` is wrong |
| CORS error | Use `localhost:5173`, or set `$env:CORS_ORIGINS` |
| "No recognizable telemetry columns" | Rename columns to a supported name (see README) |
| Port 8000 busy | `uvicorn main:app --port 8001` and set `VITE_API_BASE=http://127.0.0.1:8001` |
