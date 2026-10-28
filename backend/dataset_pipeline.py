"""Source adapters + normalization: turn CSV bytes or JSON records into a common telemetry schema.

Every input (UI upload, sample file, authorized source) goes through the same functions here.
"""

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 200_000

ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp", "time", "datetime", "date_time", "event_time", "ts", "date", "@timestamp", "logged_at", "when"],
    "service": ["service", "service_name", "component", "app", "application", "host_service", "source_service", "svc", "app_name"],
    "latency_ms": ["latency_ms", "latency", "response_time", "response_time_ms", "duration_ms", "duration", "elapsed_ms"],
    "error_count": ["error_count", "errors", "exception_count", "error", "num_errors"],
    "timeout_count": ["timeout_count", "timeouts", "db_timeouts", "timeout_errors"],
    "status_code": ["status_code", "http_status", "status", "response_code", "http_code"],
    "cpu_pct": ["cpu_usage", "cpu_percent", "cpu", "cpu_pct", "cpu_util"],
    "memory_pct": ["memory_usage", "memory_percent", "memory", "mem_pct", "memory_pct", "mem_usage"],
    "connection_pool_pct": ["connection_pool_pct", "connection_pool", "db_pool_pct", "pool_usage", "db_connection_pool"],
    "request_rate": ["request_rate", "requests_per_second", "rps", "throughput", "requests"],
    "log_level": ["log_level", "level", "severity", "loglevel", "lvl"],
    "message": ["message", "log_message", "error_message", "msg", "log", "text", "description", "details"],
    "stack_trace": ["stack_trace", "exception", "exception_message", "stacktrace", "traceback"],
    "event_type": ["event_type", "event", "change_type", "type"],
}
NUMERIC = {"latency_ms", "error_count", "timeout_count", "status_code", "cpu_pct", "memory_pct",
           "connection_pool_pct", "request_rate"}
PERCENT = {"cpu_pct", "memory_pct", "connection_pool_pct"}
LABELS = {
    "latency_ms": "latency (ms)", "error_count": "error count", "timeout_count": "timeout count",
    "cpu_pct": "CPU utilization (%)", "memory_pct": "memory utilization (%)",
    "connection_pool_pct": "connection-pool utilization (%)", "request_rate": "request rate",
}
TIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d"]


class DatasetError(ValueError):
    """Raised for inputs that cannot be analyzed; message is safe to show to users."""


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9@]+", "_", name.strip().lower()).strip("_")


def map_columns(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return {raw_header: canonical} and the list of ignored headers."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        key = _key(header)
        for canonical, names in ALIASES.items():
            if canonical not in used and key in names:
                mapping[header] = canonical
                used.add(canonical)
                break
    for header in headers:  # loose fallbacks for unfamiliar names
        if header in mapping:
            continue
        key = _key(header)
        guess = ("latency_ms" if re.search(r"latency|resp|duration|elapsed", key) else
                 "cpu_pct" if "cpu" in key else "memory_pct" if re.search(r"mem(ory)?", key) else
                 "connection_pool_pct" if "pool" in key else "timeout_count" if "timeout" in key else None)
        if guess and guess not in used:
            mapping[header] = guess
            used.add(guess)
    return mapping, [h for h in headers if h not in mapping]


def parse_csv_bytes(data: bytes) -> tuple[list[str], list[list[str]]]:
    if not data.strip():
        raise DatasetError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise DatasetError("The file is larger than the 10 MB limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if "\x00" in text[:2048]:
        raise DatasetError("This does not look like a text CSV file.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        raise DatasetError("The file has no header row.")
    if len([h for h in headers if h]) < 2:
        raise DatasetError("Expected a header row with at least two named columns.")
    rows = []
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise DatasetError(f"The file has more than {MAX_ROWS} rows.")
        if any(cell.strip() for cell in row):
            rows.append(row)
    if not rows:
        raise DatasetError("The file has a header but no data rows.")
    return headers, rows


def parse_json_records(records: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    if not records:
        raise DatasetError("No records supplied.")
    if len(records) > MAX_ROWS:
        raise DatasetError(f"More than {MAX_ROWS} records supplied.")
    headers: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise DatasetError("Each record must be a JSON object.")
        headers.extend(k for k in record if k not in headers)
    rows = [["" if r.get(h) is None else str(r.get(h)) for h in headers] for r in records]
    return headers, rows


def parse_time(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    if re.fullmatch(r"\d{9,13}(\.\d+)?", value):
        number = float(value)
        number = number / 1000 if number > 1e11 else number
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for fmt in TIME_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_number(raw: str) -> float | None:
    value = raw.strip().lower().replace(",", "").rstrip("%").replace("ms", "").strip()
    if not value or value in {"na", "n/a", "nan", "null", "none", "-"}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def normalize_service(raw: str) -> str | None:
    value = re.sub(r"[\s_]+", "-", raw.strip().lower())
    return value or None


def infer_type(values: list[str]) -> str:
    present = [v for v in values if v.strip()][:200]
    if not present:
        return "empty"
    if all(parse_number(v) is not None for v in present):
        return "numeric"
    if sum(parse_time(v) is not None for v in present) >= 0.8 * len(present):
        return "timestamp"
    return "text"


def preview(headers: list[str], rows: list[list[str]]) -> dict[str, Any]:
    mapping, ignored = map_columns(headers)
    columns = []
    for index, header in enumerate(headers):
        values = [r[index] if index < len(r) else "" for r in rows]
        columns.append({"name": header, "mapped_to": mapping.get(header), "detected_type": infer_type(values),
                        "missing": sum(1 for v in values if not v.strip())})
    return {"row_count": len(rows), "columns": columns, "ignored_columns": ignored,
            "sample_rows": [dict(zip(headers, r)) for r in rows[:10]]}


def normalize(headers: list[str], rows: list[list[str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Clean rows into canonical records and build a data-quality report. Nothing is imputed."""
    mapping, ignored = map_columns(headers)
    index = {canonical: headers.index(raw) for raw, canonical in mapping.items()}
    if not set(index) & (NUMERIC | {"log_level", "message", "stack_trace"}):
        raise DatasetError("No recognizable telemetry columns (latency, errors, status codes, resource metrics "
                           "or log messages) were found. See the README for supported column names.")

    seen: set[tuple[str, ...]] = set()
    missing = {h: 0 for h in headers}
    invalid: dict[str, int] = {}
    duplicates = invalid_ts = out_of_order = malformed = 0
    services_raw: dict[str, set[str]] = {}
    percent_values: dict[str, list[float]] = {f: [] for f in PERCENT}
    records: list[dict[str, Any]] = []
    previous_ts = None

    for row_number, row in enumerate(rows, start=2):
        if len(row) != len(headers):
            malformed += 1
            row = (row + [""] * len(headers))[:len(headers)]
        cells = tuple(c.strip() for c in row)
        if cells in seen:
            duplicates += 1
            continue
        seen.add(cells)
        for h, c in zip(headers, cells):
            if not c:
                missing[h] += 1
        record: dict[str, Any] = {"row": row_number}
        for canonical, i in index.items():
            raw = cells[i]
            if canonical == "timestamp":
                ts = parse_time(raw)
                if raw and ts is None:
                    invalid_ts += 1
                if ts and previous_ts and ts < previous_ts:
                    out_of_order += 1
                previous_ts = ts or previous_ts
                record["timestamp"] = ts
            elif canonical == "service":
                record["service"] = normalize_service(raw)
                if record["service"]:
                    services_raw.setdefault(record["service"], set()).add(raw)
            elif canonical in NUMERIC:
                number = parse_number(raw)
                if raw and number is None:
                    invalid[canonical] = invalid.get(canonical, 0) + 1
                elif number is not None and number < 0:
                    invalid[canonical] = invalid.get(canonical, 0) + 1
                    number = None
                record[canonical] = number
                if canonical in PERCENT and number is not None:
                    percent_values[canonical].append(number)
            else:
                record[canonical] = raw or None
        record.setdefault("service", None)
        records.append(record)

    notes = []
    for field, values in percent_values.items():  # 0-1 fractions are rescaled to percent
        if values and max(values) <= 1.0:
            for r in records:
                if r.get(field) is not None:
                    r[field] *= 100
            notes.append(f"{field} values were between 0 and 1 and were treated as fractions (×100).")
        over = sum(1 for r in records if (r.get(field) or 0) > 100)
        if over:
            invalid[field] = invalid.get(field, 0) + over
            for r in records:
                if (r.get(field) or 0) > 100:
                    r[field] = None
    for r in records:
        if r.get("service") is None:
            r["service"] = "(unspecified)"

    timed = [r for r in records if r.get("timestamp")]
    has_time = "timestamp" in index and len(timed) >= max(3, 0.5 * len(records))
    if has_time:
        records.sort(key=lambda r: (r["timestamp"] is None, r["timestamp"] or datetime.min.replace(tzinfo=timezone.utc)))
    limitations = []
    if "timestamp" not in index:
        limitations.append("No timestamp column: onset times and event order cannot be determined; file order is used.")
    elif not has_time:
        limitations.append("Most timestamps could not be parsed; file order is used instead of time order.")
    if "service" not in index:
        limitations.append("No service/component column: all records are treated as one component.")
    if invalid_ts:
        limitations.append(f"{invalid_ts} row(s) had unparseable timestamps; they are kept but excluded from the timeline.")
    variants = {s: sorted(v) for s, v in services_raw.items() if len(v) > 1}

    quality = {
        "rows_received": len(rows),
        "rows_processed": len(records),
        "duplicate_rows_removed": duplicates,
        "malformed_rows_padded_or_truncated": malformed,
        "invalid_timestamps": invalid_ts,
        "out_of_order_timestamps": out_of_order,
        "invalid_values_by_field": invalid,
        "missing_values_by_column": {h: n for h, n in missing.items() if n},
        "column_mapping": {raw: canonical for raw, canonical in mapping.items()},
        "ignored_columns": ignored,
        "service_name_variants_merged": variants,
        "normalization_notes": notes + (["Timestamps without a timezone were treated as UTC."] if has_time else []),
        "time_ordered": has_time,
        "limitations": limitations,
        "fields_available": sorted(index),
    }
    return records, quality
