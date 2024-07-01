"""Run reports and hwtest.py compatibility (SRS section 13)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hwval_studio import __version__
from hwval_studio.persistence.database import HistoryStore
from hwval_studio.protocol.codec import verdict_text

SUMMARY_KEYS = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "N/A": "N/A"}


def report_stem(uid: str, started_at: str) -> str:
    try:
        stamp = datetime.fromisoformat(started_at.replace("Z", "+00:00")).strftime("%Y%m%d-%H%M%S")
    except (ValueError, TypeError):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    uid8 = (uid or "0" * 8)[-8:]
    return f"hwval_{uid8}_{stamp}"


def summarise(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0}
    for result in results:
        value = verdict_text(result)
        if value in summary:
            summary[value] += 1
    return summary


def _measured(result: dict[str, Any]) -> str:
    text = result.get("measured_text") or ""
    if text:
        return text
    value = result.get("measured_value")
    unit = result.get("measured_unit") or ""
    return f"{value} {unit}".strip() if value is not None else ""


def _limits(result: dict[str, Any]) -> str:
    text = result.get("limits_text") or ""
    if text:
        return text
    low = result.get("limit_min")
    high = result.get("limit_max")
    unit = result.get("limit_unit") or ""
    if low is None and high is None:
        return ""
    return f"{low if low is not None else ''}–{high if high is not None else ''} {unit}".strip()


def run_payload(run: dict[str, Any], results: list[dict[str, Any]], gui_version: str = __version__) -> dict[str, Any]:
    summary = summarise(results)
    try:
        selection_data = json.loads(run.get("selection") or "{}")
    except (TypeError, ValueError):
        selection_data = {}
    selector = selection_data.get("ids") or selection_data.get("groups") or selection_data.get("selector") or "all"
    groups: dict[str, dict[str, int]] = {}
    for result in results:
        group = str(result.get("group_code") or result.get("group") or "Other")
        bucket = groups.setdefault(group, {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0, "total": 0})
        value = str(result.get("result") or "N/A")
        if value == "NA":
            value = "N/A"
        bucket[value] = bucket.get(value, 0) + 1
        bucket["total"] += 1
    return {
        "meta": {
            "uid": run.get("uid"),
            "version": run.get("fw_version") or "",
            "git": run.get("fw_commit") or "",
            "srs": "SRS-HWVAL-F767",
            "date": run.get("started_at"),
            "selector": selector,
            "flags": run.get("selection"),
            "gui": gui_version,
            "mode": run.get("mode"),
            "operator": run.get("operator_name") or "",
            "board": run.get("device_label") or "",
            "overall": run.get("overall"),
            "status": run.get("status"),
        },
        "summary": summary,
        "groups": groups,
        "results": [
            {
                "id": result.get("test_id"),
                "group": result.get("group_code"),
                "result": "N/A" if result.get("result") == "NA" else result.get("result"),
                "duration_ms": result.get("duration_ms"),
                "reason": result.get("reason") or "",
                "measured": _measured(result),
                "limits": _limits(result),
                "reqs": result.get("reqs") or "",
            }
            for result in results
        ],
    }


def markdown_report(run: dict[str, Any], results: list[dict[str, Any]], gui_version: str = __version__) -> str:
    payload = run_payload(run, results, gui_version)
    meta = payload["meta"]
    summary = payload["summary"]
    try:
        selection = json.loads(run.get("selection") or "{}")
        selection_text = json.dumps(selection, separators=(",", ":"))
    except (TypeError, ValueError):
        selection_text = str(run.get("selection"))
    lines = [
        "# HWVAL test report",
        "",
        f"chip UID: `{meta['uid']}`  ",
        f"firmware: {meta['version']} (git {meta['git']})  ",
        f"SRS: {meta['srs']}  ",
        f"date: {meta['date']}  ",
        f"board: {meta.get('board') or '—'}  ",
        f"operator: {meta.get('operator') or '—'}  ",
        f"mode: {meta.get('mode')}  ",
        f"GUI: HWVAL Studio {gui_version}  ",
        f"selection: `{selection_text}`  ",
        "",
        "**{} PASS / {} FAIL / {} SKIP / {} N/A of {}**".format(
            summary.get("PASS", 0),
            summary.get("FAIL", 0),
            summary.get("SKIP", 0),
            summary.get("N/A", 0),
            len(results),
        ),
        "",
    ]
    groups = payload.get("groups") or {}
    if groups:
        lines += [
            "## Totals by group",
            "",
            "| Group | PASS | FAIL | SKIP | N/A | Total |",
            "|---|---|---|---|---|---|",
        ]
        for code in sorted(groups):
            values = groups[code]
            lines.append(
                f"| {code} | {values.get('PASS', 0)} | {values.get('FAIL', 0)} | "
                f"{values.get('SKIP', 0)} | {values.get('N/A', 0)} | {values.get('total', 0)} |"
            )
        lines.append("")
    failures = [result for result in results if str(result.get("result")).upper() == "FAIL"]
    skips = [result for result in results if str(result.get("result")).upper() == "SKIP"]
    if failures:
        lines += ["## Failures", ""]
        for result in failures:
            lines.append(
                f"- **{result.get('test_id')}** {result.get('reason') or ''} "
                f"(measured {_measured(result) or '—'}, limits {_limits(result) or '—'})"
            )
        lines.append("")
    if skips:
        lines += ["## Skips", ""]
        for result in skips:
            lines.append(f"- **{result.get('test_id')}** {result.get('reason') or '—'}")
        lines.append("")
    lines += [
        "## Results",
        "",
        "| ID | result | ms | measured | limits | reason |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                result.get("test_id", "?"),
                "N/A" if result.get("result") == "NA" else result.get("result", "?"),
                result.get("duration_ms", 0),
                _measured(result).replace("|", "\\|"),
                _limits(result).replace("|", "\\|"),
                (result.get("reason") or "").replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def export_run(store: HistoryStore, run_id: int, directory: str | Path) -> tuple[Path, Path]:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    results = store.get_results(run_id)
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    stem = report_stem(str(run.get("uid", "")), str(run.get("started_at", "")))
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    payload = run_payload(run, results)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(run, results), encoding="utf-8")
    return json_path, md_path


def export_run_json(store: HistoryStore, run_id: int, path: str | Path) -> Path:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    p = Path(path)
    p.write_text(json.dumps(run_payload(run, store.get_results(run_id)), indent=2) + "\n", encoding="utf-8")
    return p


def export_run_markdown(store: HistoryStore, run_id: int, path: str | Path) -> Path:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    p = Path(path)
    p.write_text(markdown_report(run, store.get_results(run_id)), encoding="utf-8")
    return p


def import_hwtest_json(store: HistoryStore, path: str | Path) -> int:
    """Import a JSON report produced by scripts/hwtest.py (REP-004)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "results" not in raw:
        raise ValueError("not a hwtest.py JSON report")
    meta = raw.get("meta") or {}
    uid = str(meta.get("uid") or "0" * 24)
    selection = {
        "ids": [],
        "groups": [],
        "all": True,
        "levels": "S,L,E",
        "allow_operator": False,
        "allow_destructive": False,
        "repeat": 1,
        "until_fail": False,
        "selector": meta.get("selector"),
        "flags": meta.get("flags"),
    }
    run_id = store.start_run(
        uid=uid,
        fw_name="HWVAL",
        fw_version=str(meta.get("version") or ""),
        fw_commit=str(meta.get("git") or ""),
        gui_version=__version__,
        mode="IMPORTED",
        operator_name=str(meta.get("operator") or ""),
        selection=selection,
    )
    results = raw.get("results") or []
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0}
    for result in results:
        value = str(result.get("result") or "N/A")
        if value == "NA":
            value = "N/A"
        counts[value] = counts.get(value, 0) + 1
        measured = str(result.get("measured") or "")
        limits = str(result.get("limits") or "")
        store.add_result(
            run_id,
            {
                "id": result.get("id", ""),
                "group": result.get("group", str(result.get("id", "")).split(".")[0]),
                "result_name": value,
                "duration_ms": int(result.get("duration_ms") or 0),
                "reason": str(result.get("reason") or ""),
                "measured": {"text": measured, "value": None, "unit": ""},
                "limits": {"text": limits, "min": None, "max": None, "unit": ""},
                "reqs": str(result.get("reqs") or ""),
            },
        )
    store.finish_run(
        run_id,
        status="COMPLETE",
        overall="FAIL" if counts["FAIL"] else "PASS",
        n_pass=counts["PASS"],
        n_fail=counts["FAIL"],
        n_skip=counts["SKIP"],
        n_na=counts["N/A"],
    )
    return run_id


def compare_runs(
    store: HistoryStore, left_run: int, right_run: int
) -> list[dict[str, Any]]:
    left = {row["test_id"]: row for row in store.get_results(left_run)}
    right = {row["test_id"]: row for row in store.get_results(right_run)}
    rows: list[dict[str, Any]] = []
    for test_id in sorted(set(left) | set(right)):
        a = left.get(test_id)
        b = right.get(test_id)
        a_result = (a or {}).get("result", "NOT RUN")
        b_result = (b or {}).get("result", "NOT RUN")
        rows.append(
            {
                "test_id": test_id,
                "group": (a or b or {}).get("group_code", ""),
                "left": a_result,
                "right": b_result,
                "changed": a_result != b_result,
                "left_reason": (a or {}).get("reason", ""),
                "right_reason": (b or {}).get("reason", ""),
            }
        )
    return rows


def write_cli_reports(meta: dict[str, Any], results: list[dict[str, Any]], out_dir: str | Path) -> tuple[Path, Path]:
    """Write the hwtest.py-compatible JSON and Markdown pair (REP-001)."""
    from datetime import datetime

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    uid8 = str(meta.get("uid") or "0" * 8)[-8:]
    stem = f"hwval_{uid8}_{stamp}"
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    rows = []
    for result in results:
        rows.append(
            {
                "id": result.get("id"),
                "group": result.get("group"),
                "result": "N/A" if result.get("result_name") == "N/A" else result.get("result_name"),
                "duration_ms": result.get("duration_ms"),
                "reason": result.get("reason") or "",
                "measured": result.get("measured", {}).get("text", "") if isinstance(result.get("measured"), dict) else str(result.get("measured") or ""),
                "limits": result.get("limits", {}).get("text", "") if isinstance(result.get("limits"), dict) else str(result.get("limits") or ""),
                "reqs": result.get("reqs") or "",
            }
        )
    summary = {"PASS": 0, "FAIL": 0, "SKIP": 0, "N/A": 0}
    for row in rows:
        summary[row["result"]] = summary.get(row["result"], 0) + 1
    json_path.write_text(json.dumps({"meta": meta, "summary": summary, "results": rows}, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# HWVAL test report",
        "",
        f"chip UID: `{meta.get('uid')}`  ",
        f"firmware: {meta.get('version')} (git {meta.get('git')})  ",
        f"SRS: {meta.get('srs')}  ",
        f"date: {meta.get('date')}  ",
        f"selection: `{meta.get('selector')}`  flags: `{meta.get('flags')}`",
        "",
        "**{} PASS / {} FAIL / {} SKIP / {} N/A of {}**".format(
            summary.get("PASS", 0), summary.get("FAIL", 0), summary.get("SKIP", 0), summary.get("N/A", 0), len(rows)
        ),
        "",
        "| ID | result | ms | measured | limits | reason |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                row["id"], row["result"], row["duration_ms"], row["measured"], row["limits"], row["reason"]
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
