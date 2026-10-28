"""Generates the three SYNTHETIC sample datasets (not real company data). Run: python generate_samples.py"""

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent
START = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)


def maybe(value, rng, p=0.02):
    return "" if rng.random() < p else value


def database_overload(rng, fixed=False):
    rows = []
    for m in range(240):
        t = START + timedelta(minutes=m + (300 if fixed else 0))
        incident = m >= 160 and not fixed
        ramp = min(1.0, (m - 160) / 20) if incident else 0
        latency = rng.gauss(120, 15) + ramp * rng.uniform(700, 1300)
        status = rng.choices([200, 504, 500], [0.82, 0.12, 0.06])[0] if incident and ramp > 0.4 else (500 if rng.random() < 0.01 else 200)
        msg = ("DB query timed out waiting for a connection from the pool" if status == 504 else
               "Internal error while saving order" if status == 500 else "OK")
        rows.append([t.strftime("%Y-%m-%d %H:%M:%S"), "checkout-api", maybe(f"{latency:.0f}", rng), status, "", "",
                     maybe(f"{rng.gauss(42, 6):.0f}", rng), msg, rng.choice(["eu-west", "us-east"])])
        pool = rng.uniform(35, 55) if not incident else min(99.5, 60 + ramp * 38 + rng.uniform(-2, 1.5))
        timeouts = 0 if not incident else int(ramp * rng.uniform(3, 12))
        rows.append([t.strftime("%Y-%m-%d %H:%M:%S"), rng.choice(["database", "Database"]), "", "",
                     maybe(f"{pool:.1f}", rng), timeouts, maybe(f"{rng.gauss(50, 8):.0f}", rng),
                     "connection pool near capacity" if pool > 90 else "", "eu-west"])
    header = ["Timestamp", "Service Name", "Response_Time", "HTTP Status", "DB Pool Pct", "DB Timeouts", "CPU %", "Message", "Region"]
    return header, rows


def application_exception(rng):
    rows = []
    for i in range(420):
        t = START + timedelta(seconds=20 * i)
        svc = rng.choice(["orders-api", "orders-api", "auth-service"])
        failing = svc == "orders-api" and i >= 230 and rng.random() < 0.3
        if failing:
            rows.append([t.strftime("%d/%m/%Y %H:%M:%S"), svc, "ERROR", 500, maybe(f"{rng.gauss(95, 20):.0f}", rng, 0.05),
                         "Unhandled exception while mapping order response",
                         "NullPointerException: order.customer is null at OrderMapper.toDto(OrderMapper.java:88)", ""])
        else:
            rows.append([t.strftime("%d/%m/%Y %H:%M:%S"), svc, "INFO", rng.choices([200, 201, 404], [0.85, 0.1, 0.05])[0],
                         maybe(f"{rng.gauss(85, 18):.0f}", rng, 0.05), "request completed", "", ""])
        if i == 205:
            rows.append([t.strftime("%d/%m/%Y %H:%M:%S"), "orders-api", "INFO", "", "", "Deployed orders-api v2.4.1 (order DTO refactor)", "", "deployment"])
    for _ in range(15):
        rows.insert(rng.randrange(len(rows)), list(rows[rng.randrange(len(rows))]))
    rows[50][0] = "not-a-date"
    rows[51][4] = "fast"
    header = ["time", "component", "level", "status", "duration_ms", "log_message", "exception", "event_type"]
    return header, rows


def cascading_latency(rng):
    rows = []
    onsets = {"inventory-service": 100, "order-service": 112, "api-gateway": 121}
    base = {"inventory-service": 60, "order-service": 140, "api-gateway": 180}
    for m in range(200):
        t = START + timedelta(minutes=m)
        for svc in onsets:
            slow = m >= onsets[svc]
            factor = min(1.0, (m - onsets[svc]) / 8) if slow else 0
            latency = rng.gauss(base[svc], base[svc] * 0.1) * (1 + factor * rng.uniform(4, 7))
            cpu = rng.gauss(40, 6) + (factor * 52 if svc == "inventory-service" else 0)
            errors = int(factor * rng.uniform(2, 9)) if svc == "api-gateway" and slow else (1 if rng.random() < 0.03 else 0)
            label = {"order-service": rng.choice(["order-service", "Order Service"])}.get(svc, svc)
            value = f"{latency:.0f}ms" if rng.random() < 0.2 else f"{latency:.0f}"
            rows.append([t.isoformat().replace("+00:00", "Z"), label, maybe(value, rng, 0.03),
                         maybe(f"{min(cpu, 99):.0f}", rng, 0.03), errors, f"{rng.gauss(55, 6):.0f}"])
    for _ in range(12):
        i = rng.randrange(len(rows) - 4)
        rows[i], rows[i + 3] = rows[i + 3], rows[i]
    header = ["event_time", "service", "latency", "cpu_percent", "errors", "requests_per_second"]
    return header, rows


if __name__ == "__main__":
    for name, fn, seed in (("database_overload.csv", database_overload, 7),
                           ("application_exception.csv", application_exception, 11),
                           ("cascading_latency.csv", cascading_latency, 23),
                           ("database_overload_after_fix.csv", lambda rng: database_overload(rng, fixed=True), 31)):
        header, rows = fn(random.Random(seed))
        with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"wrote {name}: {len(rows)} rows")
