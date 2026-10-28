"""Dataset investigation engine: anomalies, error/log analysis, evidence-ranked hypotheses, problem statement.

Methods are deliberately simple and explainable: per-series median/MAD baselines (robust z-scores),
error-rate comparison against the early part of the dataset, repeated-exception grouping and
time-window overlap. Scores are explained rule points, not probabilities.
"""

import re
from datetime import datetime
from statistics import median
from typing import Any

from dataset_pipeline import LABELS

Z_THRESHOLD = 3.5
SATURATION_PCT = 90.0
BASELINE_SHARE = 0.4
MIN_SERIES = 8
METRICS = ["latency_ms", "error_count", "timeout_count", "cpu_pct", "memory_pct", "connection_pool_pct", "request_rate"]
EXC_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Timeout))\b")
DEPLOY_RE = re.compile(r"\b(deploy(ed|ment|ing)?|release[d]?|rollout|rolled out|upgrade[d]?)\b", re.I)
ERRWORD_RE = re.compile(r"\b(error|exception|failed|failure|fatal|timed out|timeout)\b", re.I)
DB_RE = re.compile(r"\b(db|database|sql|postgres|mysql|connection pool|pool|query)\b", re.I)


def fmt(value: float) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}".rstrip("0").rstrip(".")


class Context:
    def __init__(self, records: list[dict[str, Any]], quality: dict[str, Any]):
        self.records = records
        self.timed = quality["time_ordered"]
        for pos, r in enumerate(records):
            r["pos"] = pos
        self.limitations: list[str] = list(quality["limitations"])

    def key(self, r: dict[str, Any]) -> float:
        return r["timestamp"].timestamp() if self.timed and r.get("timestamp") else float(r["pos"])

    def when(self, r: dict[str, Any]) -> str:
        if self.timed and r.get("timestamp"):
            return r["timestamp"].strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"row {r['row']}"

    def iso(self, r: dict[str, Any]) -> str | None:
        return r["timestamp"].isoformat() if self.timed and r.get("timestamp") else None


def find_episodes(ctx: Context) -> list[dict[str, Any]]:
    episodes = []
    services = sorted({r["service"] for r in ctx.records})
    for service in services:
        for metric in METRICS:
            series = [r for r in ctx.records if r["service"] == service and r.get(metric) is not None]
            if not series:
                continue
            if len(series) < MIN_SERIES:
                ctx.limitations.append(f"{service} {LABELS[metric]}: only {len(series)} values, too few for a baseline.")
                continue
            base = series[:max(5, int(len(series) * BASELINE_SHARE))]
            values = [r[metric] for r in base]
            med = median(values)
            mad = median([abs(v - med) for v in values]) * 1.4826
            constant = mad == 0
            scale = mad or max(abs(med) * 0.05, 1e-6)
            upper = med + Z_THRESHOLD * scale
            flagged = []
            for i, r in enumerate(series):
                z = (r[metric] - med) / scale
                hit = z >= Z_THRESHOLD or (metric == "request_rate" and z <= -Z_THRESHOLD)
                saturated = metric.endswith("_pct") and r[metric] >= SATURATION_PCT
                if hit or saturated:
                    flagged.append((i, z, saturated and not hit))
            groups: list[list[tuple[int, float, bool]]] = []
            for item in flagged:
                if groups and item[0] - groups[-1][-1][0] <= 3:
                    groups[-1].append(item)
                else:
                    groups.append([item])
            for group in groups:
                rows = [series[i] for i, _, _ in group]
                vals = [r[metric] for r in rows]
                peak_row = max(rows, key=lambda r: abs(r[metric] - med))
                ep_med = median(vals)
                episodes.append({
                    "service": service, "metric": metric, "label": LABELS[metric],
                    "start": ctx.when(rows[0]), "end": ctx.when(rows[-1]),
                    "start_iso": ctx.iso(rows[0]), "end_iso": ctx.iso(rows[-1]),
                    "start_key": ctx.key(rows[0]), "end_key": ctx.key(rows[-1]),
                    "count": len(rows), "sustained": len(rows) >= 3,
                    "peak": peak_row[metric], "episode_median": ep_med,
                    "baseline_median": med, "baseline_upper": upper, "baseline_samples": len(base),
                    "direction": "below" if ep_med < med else "above",
                    "ratio": round(ep_med / med, 2) if med else None,
                    "max_robust_z": round(max(abs(z) for _, z, _ in group), 1),
                    "constant_baseline": constant,
                    "reason": (f"{len(rows)} value(s) beyond median + {Z_THRESHOLD}×scaled MAD "
                               f"({fmt(upper)}) of the first {len(base)} samples"
                               + ("; baseline was constant, 5% of median used as minimum spread" if constant else "")
                               + (f"; or ≥{SATURATION_PCT:.0f}% saturation" if metric.endswith('_pct') else "")),
                    "series_rows": [series.index(r) for r in rows],
                })
    return episodes


def is_error(r: dict[str, Any]) -> bool:
    level = (r.get("log_level") or "").lower()
    text = f"{r.get('message') or ''} {r.get('stack_trace') or ''}"
    return bool((r.get("status_code") or 0) >= 500 or level in {"error", "critical", "fatal", "severe"}
                or (r.get("error_count") or 0) > 0
                or r.get("stack_trace") or (not level and r.get("status_code") is None and ERRWORD_RE.search(text)))


def error_findings(ctx: Context) -> list[dict[str, Any]]:
    findings = []
    for service in sorted({r["service"] for r in ctx.records}):
        rows = [r for r in ctx.records if r["service"] == service]
        if len(rows) < MIN_SERIES:
            continue
        flags = [is_error(r) for r in rows]
        if not any(flags):
            continue
        cut = max(5, int(len(rows) * BASELINE_SHARE))
        base_rate = sum(flags[:cut]) / cut
        later = flags[cut:]
        if not later:
            continue
        later_rate = sum(later) / len(later)
        threshold = max(2 * base_rate, base_rate + 0.05)
        if sum(later) < 3 or later_rate < threshold:
            continue
        window = 10
        onset = None
        for i in range(cut, len(rows)):
            chunk = flags[i:i + window]
            if len(chunk) >= 3 and sum(chunk) / len(chunk) >= threshold and flags[i]:
                onset = rows[i]
                break
        onset = onset or next(r for r, f in zip(rows[cut:], later) if f)
        err_rows = [r for r, f in zip(rows, flags) if f and ctx.key(r) >= ctx.key(onset)]
        findings.append({
            "service": service, "baseline_rate": round(base_rate, 3), "later_rate": round(later_rate, 3),
            "baseline_rows": cut, "later_rows": len(later), "errors_after_onset": len(err_rows),
            "http_5xx": sum(1 for r in err_rows if (r.get("status_code") or 0) >= 500),
            "onset": ctx.when(onset), "onset_iso": ctx.iso(onset), "start_key": ctx.key(onset),
            "end_key": ctx.key(err_rows[-1]), "end": ctx.when(err_rows[-1]),
        })
    return findings


def exception_groups(ctx: Context) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in ctx.records:
        text = r.get("stack_trace") or r.get("message") or ""
        if not text or not is_error(r):
            continue
        match = EXC_RE.search(text)
        signature = match.group(1) if match else re.sub(r"\d+", "#", re.sub(r"0x[0-9a-f]+", "#", text.lower()))[:80]
        g = groups.setdefault((r["service"], signature), {
            "service": r["service"], "signature": signature, "count": 0, "with_5xx": 0, "db_related": 0,
            "first": ctx.when(r), "first_iso": ctx.iso(r), "start_key": ctx.key(r), "sample": text[:200]})
        g["count"] += 1
        g["with_5xx"] += 1 if (r.get("status_code") or 0) >= 500 else 0
        g["db_related"] += 1 if DB_RE.search(text) and re.search(r"time(d)? ?out", text, re.I) else 0
        g["last"], g["end_key"] = ctx.when(r), ctx.key(r)
    return sorted((g for g in groups.values() if g["count"] >= 3), key=lambda g: -g["count"])


def deployments(ctx: Context) -> list[dict[str, Any]]:
    found = []
    for r in ctx.records:
        text = f"{r.get('event_type') or ''} {r.get('message') or ''}"
        if DEPLOY_RE.search(text):
            found.append({"service": r["service"], "when": ctx.when(r), "iso": ctx.iso(r),
                          "key": ctx.key(r), "text": text.strip()[:160]})
    return found[:20]


def overlaps(a: dict[str, Any], b: dict[str, Any], slack: float) -> bool:
    return a["start_key"] <= b["end_key"] + slack and b["start_key"] <= a["end_key"] + slack


class Hypotheses:
    def __init__(self):
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, name: str, points: int, evidence: str, services: list[str], kind: str) -> None:
        h = self.items.setdefault(name, {"hypothesis": name, "score": 0, "evidence": [], "contradicting": [],
                                         "services": [], "signal_types": [], "next_steps": [], "kind": kind})
        h["score"] += points
        h["evidence"].append(f"{evidence} (+{points})")
        h["services"] = sorted(set(h["services"]) | set(services))

    def against(self, name: str, text: str) -> None:
        if name in self.items:
            self.items[name]["contradicting"].append(text)


def rank(ctx, eps, errs, excs, deps) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    span = (max((ctx.key(r) for r in ctx.records), default=0) - min((ctx.key(r) for r in ctx.records), default=0))
    slack = span * 0.03
    H = Hypotheses()
    sustained = [e for e in eps if e["sustained"] or (e["metric"].endswith("_pct") and e["peak"] >= SATURATION_PCT)]
    by_metric = lambda m: [e for e in sustained if e["metric"] == m]  # noqa: E731
    lat, pool, tmo = by_metric("latency_ms"), by_metric("connection_pool_pct"), by_metric("timeout_count")
    db_exc = [g for g in excs if g["db_related"] >= 3]
    DB = "Database saturation or connection-pool exhaustion"
    for e in pool:
        H.add(DB, 4, f"Connection-pool utilization on {e['service']} reached {fmt(e['peak'])}% "
                     f"(baseline median {fmt(e['baseline_median'])}%) between {e['start']} and {e['end']}", [e["service"]], "pool")
    for e in tmo:
        H.add(DB, 4, f"Timeouts on {e['service']} rose to a median of {fmt(e['episode_median'])} per sample "
                     f"(baseline {fmt(e['baseline_median'])}) from {e['start']}", [e["service"]], "timeouts")
    for g in db_exc[:1]:
        H.add(DB, 3, f"{g['count']} database timeout log entries on {g['service']} from {g['first']}", [g["service"]], "timeout_logs")
    if DB in H.items:
        db_windows = pool + tmo + [{"start_key": g["start_key"], "end_key": g["end_key"]} for g in db_exc]
        hit = [e for e in lat if any(overlaps(e, w, slack) for w in db_windows)]
        if hit:
            e = max(hit, key=lambda e: e["ratio"] or 0)
            H.add(DB, 3, f"Latency on {e['service']} rose to {fmt(e['episode_median'])} ms (baseline {fmt(e['baseline_median'])} ms) "
                         "in the same window", [e["service"]], "latency")
        pool_services = {r["service"] for r in ctx.records if r.get("connection_pool_pct") is not None}
        if not pool_services:
            H.against(DB, "No connection-pool metric in the data, so pool exhaustion cannot be checked directly.")

    for g in excs[:2]:
        name = f"Application exception in {g['service']} ({g['signature']})"
        H.add(name, 4, f"{g['signature']} occurred {g['count']} times on {g['service']} between {g['first']} and {g['last']}",
              [g["service"]], "exceptions")
        if g["with_5xx"] >= max(2, g["count"] // 2):
            H.add(name, 3, f"{g['with_5xx']} of those entries returned HTTP 5xx", [g["service"]], "http_5xx")
        total = sum(x["count"] for x in excs)
        if total and g["count"] / total >= 0.8 and len({x['service'] for x in excs}) > 1:
            H.add(name, 1, "Exceptions are concentrated in this component", [g["service"]], "concentration")
        if g["db_related"] >= 3:
            H.against(name, "The exception text references database timeouts; it may be a symptom of a dependency problem.")
        if pool or tmo:
            H.against(name, "Database saturation signals were also present in the data.")

    symptoms = [e for e in sustained if e["metric"] in ("latency_ms", "error_count", "timeout_count")] + errs
    first_symptom = min(symptoms, key=lambda s: s["start_key"]) if symptoms else None
    if first_symptom:
        for d in deps:
            gap = first_symptom["start_key"] - d["key"]
            limit = 3600 if ctx.timed else max(20, len(ctx.records) * 0.1)
            name = f"Regression introduced by a change on {d['service']}"
            if 0 <= gap <= limit:
                unit = f"{gap / 60:.0f} min" if ctx.timed else f"{gap:.0f} rows"
                H.add(name, 4, f"Change event at {d['when']} (\"{d['text'][:60]}\") preceded the first symptom by {unit}",
                      [d["service"]], "deployment")
                if d["service"] == first_symptom["service"]:
                    H.add(name, 1, "The change was on the same component as the first symptom", [d["service"]], "same_service")
                H.against(name, "Timing alone does not prove the change caused the problem; compare versions or roll back in staging.")

    lat_by_service: dict[str, dict[str, Any]] = {}
    for e in lat:
        if e["service"] not in lat_by_service or e["start_key"] < lat_by_service[e["service"]]["start_key"]:
            lat_by_service[e["service"]] = e
    propagation = None
    if len(lat_by_service) >= 2:
        order = sorted(lat_by_service.values(), key=lambda e: e["start_key"])
        step = max(slack, 1.0 if not ctx.timed else 60.0)
        if order[1]["start_key"] - order[0]["start_key"] >= step:
            src = order[0]["service"]
            name = f"Degradation originating in {src} and propagating to other services"
            H.add(name, 3, f"{src} latency rose first at {order[0]['start']} "
                           f"({fmt(order[0]['episode_median'])} ms vs baseline {fmt(order[0]['baseline_median'])} ms)", [src], "first_onset")
            for e in order[1:3]:
                H.add(name, 1, f"{e['service']} latency rose later, at {e['start']}", [e["service"]], "later_onset")
            for e in sustained:
                if e["service"] == src and e["metric"] in ("cpu_pct", "memory_pct", "connection_pool_pct", "timeout_count"):
                    H.add(name, 1, f"{src} also showed abnormal {e['label']} (peak {fmt(e['peak'])})", [src], "source_resource")
            H.against(name, "Service dependencies are not in the data; propagation is inferred from timing only.")
            propagation = {"label": "Inferred from onset timing; dependencies not confirmed by the data",
                           "order": [{"service": e["service"], "onset": e["start"], "onset_iso": e["start_iso"],
                                      "latency_median": e["episode_median"], "baseline_median": e["baseline_median"]} for e in order]}

    for metric, label in (("cpu_pct", "CPU"), ("memory_pct", "Memory")):
        for e in by_metric(metric):
            name = f"{label} saturation on {e['service']}"
            H.add(name, 3, f"{e['label']} on {e['service']} reached {fmt(e['peak'])} (baseline median {fmt(e['baseline_median'])}) "
                           f"from {e['start']}", [e["service"]], metric)
            if any(s["service"] == e["service"] and overlaps(s, e, slack) for s in symptoms):
                H.add(name, 2, f"Latency or errors on {e['service']} rose in the same window", [e["service"]], "co_symptom")
            oom = [g for g in excs if g["service"] == e["service"] and re.search(r"memory|heap|gc overhead", g["sample"], re.I)]
            if metric == "memory_pct" and oom:
                H.add(name, 2, f"{oom[0]['count']} memory-related errors ({oom[0]['signature']}) on {e['service']}",
                      [e["service"]], "oom_logs")

    for e in [x for x in by_metric("request_rate") if x["direction"] == "above"]:
        name = f"Traffic surge on {e['service']}"
        H.add(name, 3, f"Request rate on {e['service']} rose to {fmt(e['episode_median'])} (baseline {fmt(e['baseline_median'])}) "
                       f"from {e['start']}", [e["service"]], "traffic")
        if any(overlaps(s, e, slack) for s in symptoms):
            H.add(name, 2, "Latency or errors rose in the same window", [e["service"]], "co_symptom")

    if not H.items and (sustained or errs):
        H.add("Unexplained deviation (no matching pattern)", 2,
              "Metrics or error rates deviated from their baselines, but no corroborating signal type was found",
              sorted({s["service"] for s in sustained + errs}), "deviation")

    ranked = sorted(H.items.values(), key=lambda h: (-h["score"], h["hypothesis"]))
    for i, h in enumerate(ranked):
        h.pop("kind", None)
        h.pop("signal_types", None)
        h["assessment"] = ("tied" if i == 0 and len(ranked) > 1 and ranked[1]["score"] == h["score"] else
                           "supported" if h["score"] >= 6 else "weak")
        h["independent_signals"] = len(h["evidence"])
        h["next_steps"] = next_steps(h)
    return ranked, propagation


def next_steps(h: dict[str, Any]) -> list[str]:
    s = ", ".join(h["services"]) or "the affected component"
    name = h["hypothesis"]
    if name.startswith("Database"):
        return [f"Inspect database connection utilization, slow queries and pool exhaustion for {s} during the affected window.",
                "Check for long-held transactions or connections that are not released.",
                "Proposed only, needs human approval: adjust pool size or query timeouts after review."]
    if name.startswith("Application exception"):
        return [f"Open the stack traces for {s} and identify the failing handler.",
                "Reproduce the failing request outside production and review recent code changes in that path."]
    if name.startswith("Regression"):
        return [f"Diff the change deployed on {s} against the previous version.",
                "Proposed only, needs human approval: roll back in staging first and compare the same metrics."]
    if name.startswith("Degradation originating"):
        src = name.split(" in ")[1].split(" and ")[0]
        return [f"Confirm whether the other services call {src} (traces or dependency config).",
                f"Investigate {src} first: its resource usage, dependencies and recent changes."]
    if "saturation on" in name:
        return [f"Profile {s} for hot paths or memory growth during the window.", "Compare resource usage with request volume."]
    if name.startswith("Traffic"):
        return [f"Identify the source of the extra traffic on {s} (clients, endpoints, retries).", "Review autoscaling and rate limits."]
    return ["Collect logs, traces and change events for the affected window to corroborate the deviation."]


PREVENTION = {
    "Database": [("Connection-pool configuration", "High", "Review pool size, connection timeouts and leak detection for {s}."),
                 ("Query performance", "Medium", "Profile and index the slowest queries observed during {w}."),
                 ("Alert thresholds", "Medium", "Alert on connection-pool utilization and DB timeouts before saturation.")],
    "Application exception": [("Exception handling", "High", "Handle the failing case and return a controlled error in {s}."),
                              ("Regression testing", "Medium", "Add a test that reproduces the exception seen during {w}.")],
    "Regression": [("Change safety", "High", "Use canary releases with automatic halt on latency/error regressions for {s}."),
                   ("Regression testing", "Medium", "Add a pre-release performance check for the changed path.")],
    "Degradation originating": [("Dependency timeouts", "High", "Set client timeouts and circuit breakers for calls into {s}."),
                                ("Capacity planning", "Medium", "Review capacity of {s}, the first component to degrade.")],
    "CPU": [("Resource monitoring", "Medium", "Alert on sustained CPU above baseline for {s}."),
            ("Capacity planning", "Medium", "Review instance sizing/autoscaling for {s}.")],
    "Memory": [("Resource monitoring", "High", "Track memory growth over time for {s} to catch leaks early.")],
    "Traffic": [("Capacity planning", "Medium", "Plan capacity and rate limits for traffic peaks like the one during {w}.")],
}


def recommendations(ranked, eps, primary_window: str) -> list[dict[str, Any]]:
    recs = []
    for h in [h for h in ranked if h["score"] >= 3][:3]:
        key = next((k for k in PREVENTION if h["hypothesis"].startswith(k)), None)
        if not key:
            continue
        for category, priority, action in PREVENTION[key]:
            recs.append({"category": category, "priority": priority if h["assessment"] != "weak" else "Low",
                         "problem": h["hypothesis"], "why": f"Rule score {h['score']} ({h['assessment']}) in this investigation.",
                         "evidence": h["evidence"][0].split(" (+")[0], "action": action.format(s=", ".join(h["services"]), w=primary_window)})
    for e in [e for e in eps if e["sustained"] and e["metric"] == "latency_ms"][:2]:
        recs.append({"category": "Alert thresholds", "priority": "Medium", "problem": f"Latency regression on {e['service']}",
                     "why": "Threshold derived from this dataset's baseline.",
                     "evidence": f"Baseline median {fmt(e['baseline_median'])} ms; incident median {fmt(e['episode_median'])} ms",
                     "action": f"Alert when {e['service']} latency stays above {fmt(e['baseline_upper'])} ms (baseline median + {Z_THRESHOLD}×scaled MAD)."})
    return recs


def symptom_phrase(s: dict[str, Any], kind: str) -> str:
    if kind == "metric":
        return (f"{s['label']} on {s['service']} rose from a baseline median of {fmt(s['baseline_median'])} "
                f"to {fmt(s['episode_median'])} (peak {fmt(s['peak'])})")
    if kind == "errors":
        return (f"the error rate on {s['service']} increased from {s['baseline_rate']:.0%} to {s['later_rate']:.0%}"
                + (f" with {s['http_5xx']} HTTP 5xx responses" if s["http_5xx"] else ""))
    return f"{s['service']} repeatedly raised {s['signature']} ({s['count']} occurrences)"


def short_phrase(s: dict[str, Any], kind: str) -> str:
    if kind == "metric":
        return f"{s['label'].split(' (')[0]} on {s['service']} at {fmt(s['episode_median'])} (baseline {fmt(s['baseline_median'])})"
    if kind == "errors":
        return f"errors on {s['service']} at {s['later_rate']:.0%} (baseline {s['baseline_rate']:.0%})"
    return f"repeated {s['signature'][:40]} on {s['service']}"


def analyze(records: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any]:
    ctx = Context(records, quality)
    eps = find_episodes(ctx)
    errs = error_findings(ctx)
    excs = exception_groups(ctx)
    deps = deployments(ctx)
    ranked, propagation = rank(ctx, eps, errs, excs, deps)
    sustained = [e for e in eps if e["sustained"] or (e["metric"].endswith("_pct") and e["peak"] >= SATURATION_PCT)]

    candidates = [(e["ratio"] or 1, "metric", e) for e in sustained if e["direction"] == "above"]
    candidates += [(max(e["later_rate"] * 10, 1.5), "errors", e) for e in errs]
    candidates += [(1.2, "exceptions", g) for g in excs]
    status, problem, severity, rationale = "no_significant_problem", None, "None", "No sustained deviation, error increase or repeated exception was found."
    chart = None
    if candidates:
        primary_kind, primary = None, None
        impact, primary_kind, primary = max(candidates, key=lambda c: c[0])
        start = primary.get("start") or primary.get("onset") or primary.get("first")
        others = [short_phrase(s, k) for _, k, s in sorted(candidates, key=lambda c: -c[0])
                  if s is not primary and overlaps(s, primary, 1e18 if not ctx.timed else 600)][:2]
        title = (f"{primary['label'].split(' (')[0].capitalize()} {'increase' if primary['direction'] == 'above' else 'drop'} on "
                 f"{primary['service']} ({primary['ratio']}× baseline)" if primary_kind == "metric" else
                 f"Error-rate increase on {primary['service']} ({primary['later_rate']:.0%})" if primary_kind == "errors" else
                 f"Repeated {primary['signature'][:40]} on {primary['service']}")
        statement = symptom_phrase(primary, primary_kind)
        statement = statement[0].upper() + statement[1:] + f", starting {start}"
        if others:
            statement += ", alongside " + " and ".join(others)
        statement += "."
        affected = sorted({s["service"] for _, _, s in candidates})
        top = ranked[0] if ranked else None
        reliable = top and top["assessment"] in ("supported", "tied") and top["score"] >= 6
        status = "problem_found" if reliable else "insufficient_evidence"
        missing = [f for f in ("timestamp", "service", "latency_ms", "status_code", "connection_pool_pct", "message")
                   if f not in quality["fields_available"]]
        max_err = max((e["later_rate"] for e in errs), default=0)
        max_ratio = max((e["ratio"] or 0 for e in sustained if e["metric"] == "latency_ms"), default=0)
        n_aff = len(affected)
        severity = ("Critical" if max_err >= 0.25 or (max_ratio >= 5 and n_aff >= 2) else
                    "High" if max_err >= 0.10 or max_ratio >= 3 else
                    "Medium" if sustained or errs else "Low")
        parts = ([f"error rate after onset {max_err:.0%}"] if errs else []) + \
                ([f"latency up to {max_ratio:.1f}× its baseline median"] if max_ratio else []) + \
                [f"{n_aff} component(s) affected"]
        rationale = "Based on " + "; ".join(parts) + "."
        problem = {
            "title": title,
            "statement": statement,
            "affected_components": affected,
            "onset": min(((c[2]["start_key"], c[2].get("start") or c[2].get("onset") or c[2].get("first")) for c in candidates),
                         key=lambda x: x[0])[1],
            "evidence": [symptom_phrase(s, k) + f" ({s.get('start') or s.get('onset') or s.get('first')})"
                         for _, k, s in sorted(candidates, key=lambda c: -c[0])][:6],
            "likely_cause": (f"{top['hypothesis']} is the best-supported explanation (score {top['score']}), "
                             "but correlation in this data does not independently confirm it." if reliable else
                             "Insufficient evidence to identify a reliable root cause."
                             + (f" Weak lead: {top['hypothesis']} (score {top['score']})." if top else "")),
            "certainty": (("Moderate" if top["independent_signals"] >= 3 else "Low-to-moderate")
                          + f": {top['independent_signals']} pieces of evidence support it; contradicting points: "
                          f"{len(top['contradicting'])}." if reliable else
                          "Low: the data does not contain enough corroborating signals."),
            "next_step": top["next_steps"][0] if top else "Collect metrics, logs and change events for the affected window.",
            "missing_information": ([f"Missing fields that would help: {', '.join(missing)}."] if missing else [])
                                   + ([] if reliable else ["Add correlated signals (DB/pool metrics, error logs, deploy events) to separate competing explanations."]),
        }
        if primary_kind == "metric":
            series = [r for r in ctx.records if r["service"] == primary["service"] and r.get(primary["metric"]) is not None]
            step = max(1, len(series) // 150)
            chart = {"service": primary["service"], "metric": primary["metric"], "label": primary["label"],
                     "baseline_median": primary["baseline_median"], "baseline_upper": primary["baseline_upper"],
                     "points": [{"x": ctx.iso(r) or r["row"], "y": r[primary["metric"]],
                                 "flag": primary["start_key"] <= ctx.key(r) <= primary["end_key"]} for r in series[::step]]}

    timeline = []
    if records:
        timeline.append({"key": ctx.key(records[0]), "when": ctx.when(records[0]), "kind": "data", "service": "",
                         "text": "First record in dataset"})
    for e in sustained:
        timeline.append({"key": e["start_key"], "when": e["start"], "kind": "anomaly", "service": e["service"],
                         "text": f"{e['label']} deviates from baseline (median {fmt(e['baseline_median'])} → {fmt(e['episode_median'])})"})
    for e in errs:
        timeline.append({"key": e["start_key"], "when": e["onset"], "kind": "errors", "service": e["service"],
                         "text": f"Error rate rises above baseline ({e['baseline_rate']:.0%} → {e['later_rate']:.0%})"})
    for g in excs:
        timeline.append({"key": g["start_key"], "when": g["first"], "kind": "exception", "service": g["service"],
                         "text": f"First {g['signature']} ({g['count']} total)"})
    for d in deps:
        timeline.append({"key": d["key"], "when": d["when"], "kind": "change", "service": d["service"], "text": d["text"]})
    if records:
        timeline.append({"key": ctx.key(records[-1]), "when": ctx.when(records[-1]), "kind": "data", "service": "",
                         "text": "Last record in dataset"})
    timeline.sort(key=lambda t: t["key"])

    window = f"{problem['onset']}" if problem else "the analysed period"
    minor = [e for e in eps if e not in sustained]
    for e in eps:
        e.pop("series_rows", None)
    return {
        "status": status,
        "problem": problem,
        "severity": severity,
        "severity_rationale": rationale,
        "primary_service": problem["affected_components"][0] if problem else None,
        "anomalies": sustained,
        "minor_deviations": minor[:20],
        "error_findings": errs,
        "exceptions": excs[:10],
        "change_events": deps,
        "hypotheses": ranked,
        "propagation": propagation,
        "timeline": [{k: v for k, v in t.items() if k != "key"} for t in timeline[:40]],
        "chart": chart,
        "recommendations": recommendations(ranked, eps, window) if problem else [],
        "limitations": ctx.limitations[:15],
        "period": {"start": ctx.when(records[0]), "end": ctx.when(records[-1])} if records else None,
        "services": sorted({r["service"] for r in records}),
        "method": ("Per-series robust baselines (median and scaled MAD of the first 40% of samples, threshold "
                   f"{Z_THRESHOLD}), ≥{SATURATION_PCT:.0f}% saturation rule, error-rate comparison against the early "
                   "period, repeated-exception grouping, and time-window overlap. Hypothesis scores are explained "
                   "rule points, not probabilities."),
    }


def compare_fix(original: dict[str, Any], post_records: list[dict[str, Any]], post_quality: dict[str, Any]) -> dict[str, Any]:
    """Compare a post-fix dataset against the original baseline and incident period."""
    checks = []
    for e in original["anomalies"]:
        values = [r[e["metric"]] for r in post_records if r["service"] == e["service"] and r.get(e["metric"]) is not None]
        item = {"target": f"{e['service']} {e['label']}", "baseline_median": e["baseline_median"],
                "incident_median": e["episode_median"], "baseline_upper": e["baseline_upper"], "samples": len(values)}
        if len(values) < 3:
            item.update(result="not_measured", post_median=None, note="Fewer than 3 post-fix values for this metric.")
        else:
            post = median(values)
            better_dir = post < e["episode_median"] if e["direction"] == "above" else post > e["episode_median"]
            within = post <= e["baseline_upper"] if e["direction"] == "above" else True
            change = (post - e["episode_median"]) / e["episode_median"] if e["episode_median"] else 0
            result = ("improved" if better_dir and within and abs(change) >= 0.2 else
                      "worsened" if (change >= 0.1 if e["direction"] == "above" else change <= -0.1) else
                      "partially_improved" if better_dir and abs(change) >= 0.2 else "inconclusive")
            item.update(result=result, post_median=post,
                        note="Back within baseline range." if within and result == "improved" else
                        "Still above the original baseline range." if not within else "")
        checks.append(item)
    for f in original["error_findings"]:
        rows = [r for r in post_records if r["service"] == f["service"]]
        item = {"target": f"{f['service']} error rate", "baseline_median": f["baseline_rate"],
                "incident_median": f["later_rate"], "samples": len(rows)}
        if len(rows) < 5:
            item.update(result="not_measured", post_median=None, note="Fewer than 5 post-fix rows for this service.")
        else:
            rate = sum(is_error(r) for r in rows) / len(rows)
            limit = max(f["baseline_rate"] * 1.5, f["baseline_rate"] + 0.02)
            result = ("improved" if rate <= limit else "worsened" if rate >= f["later_rate"] else
                      "partially_improved" if rate <= f["later_rate"] * 0.8 else "inconclusive")
            item.update(result=result, post_median=round(rate, 3), note=f"Baseline-acceptable limit {limit:.0%}.")
        checks.append(item)
    measured = [c for c in checks if c["result"] != "not_measured"]
    if not measured:
        overall = "insufficient_data"
    elif any(c["result"] == "worsened" for c in measured):
        overall = "worsened"
    elif all(c["result"] == "improved" for c in measured):
        overall = "improved"
    else:
        overall = "inconclusive"
    post_analysis = analyze(post_records, post_quality)
    summary = {
        "improved": "All measured targets returned to their original baseline range.",
        "worsened": "At least one target is worse than during the incident.",
        "inconclusive": "Some targets improved, but not all returned to the baseline range.",
        "insufficient_data": "The post-fix dataset does not contain the metrics needed to evaluate the original findings.",
    }[overall]
    return {"result": overall, "summary": summary, "checks": checks,
            "post_fix_new_anomalies": len(post_analysis["anomalies"]),
            "post_fix_problem": (post_analysis["problem"] or {}).get("statement")}
