"""SQLite run history (SRS section 12, Appendix C)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  uid           TEXT PRIMARY KEY,
  dev_id        INTEGER, rev_id INTEGER,
  label         TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY,
  uid           TEXT NOT NULL REFERENCES devices(uid),
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT NOT NULL,
  overall       TEXT,
  fw_name       TEXT, fw_version TEXT, fw_commit TEXT,
  gui_version   TEXT NOT NULL,
  mode          TEXT NOT NULL,
  operator_name TEXT,
  selection     TEXT NOT NULL,
  n_pass INTEGER DEFAULT 0, n_fail INTEGER DEFAULT 0,
  n_skip INTEGER DEFAULT 0, n_na   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS results (
  id            INTEGER PRIMARY KEY,
  run_id        INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  test_id       TEXT NOT NULL,
  group_code    TEXT NOT NULL,
  iteration     INTEGER NOT NULL DEFAULT 1,
  result        TEXT NOT NULL,
  duration_ms   INTEGER,
  reason        TEXT,
  measured_value REAL, measured_unit TEXT, measured_text TEXT,
  limit_min REAL, limit_max REAL, limit_unit TEXT, limits_text TEXT,
  reqs          TEXT,
  finished_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS results_run  ON results(run_id);
CREATE INDEX IF NOT EXISTS results_test ON results(test_id);

CREATE TABLE IF NOT EXISTS catalogue (
  fw_version    TEXT NOT NULL,
  test_id       TEXT NOT NULL,
  group_code    TEXT NOT NULL,
  title         TEXT, level TEXT, operator INTEGER, destructive INTEGER,
  timeout_ms    INTEGER, reqs TEXT,
  PRIMARY KEY (fw_version, test_id)
);

CREATE TABLE IF NOT EXISTS firmware_ops (
  id            INTEGER PRIMARY KEY,
  uid           TEXT,
  at            TEXT NOT NULL,
  kind          TEXT NOT NULL,
  file_name     TEXT, file_sha256 TEXT,
  image_name    TEXT, image_version TEXT,
  slot          TEXT,
  outcome       TEXT NOT NULL,
  detail        TEXT
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, path: str | Path, *, recover_running: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self._lock:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self._migrate()
            if recover_running:
                # Only the first opener recovers runs; a second window in
                # the same process must not mark the live run INCOMPLETE.
                self.mark_incomplete_runs()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    # -- schema --------------------------------------------------------
    def _migrate(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            self.connection.executescript(SCHEMA)
            self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.connection.commit()
        elif version > SCHEMA_VERSION:
            raise RuntimeError(
                f"history database schema {version} is newer than this application ({SCHEMA_VERSION})"
            )
        else:
            backup = self.path.with_suffix(f".v{version}.bak")
            try:
                if self.path.exists():
                    shutil.copy2(self.path, backup)
            except OSError:
                pass
            if version < SCHEMA_VERSION:
                # Future migrations append here.  v1 is the initial schema.
                self.connection.executescript(SCHEMA)
                self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                self.connection.commit()
        # Query indexes, added on existing databases too.  Safe to run after
        # the schema (fresh) or after the migration (existing).
        self.connection.executescript(
            "CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at);"
            "CREATE INDEX IF NOT EXISTS runs_uid ON runs(uid);"
            "CREATE INDEX IF NOT EXISTS results_run_test ON results(run_id, test_id);"
        )
        self.connection.commit()

    def mark_incomplete_runs(self) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE runs SET status='INCOMPLETE', finished_at=COALESCE(finished_at, ?) "
                "WHERE status='RUNNING'",
                (utc_now(),),
            )
            self.connection.commit()

    # -- devices -------------------------------------------------------
    def record_device(self, uid: str, dev_id: int = 0, rev_id: int = 0, label: str | None = None) -> None:
        now = utc_now()
        with self._lock:
            row = self.connection.execute("SELECT uid, label FROM devices WHERE uid=?", (uid,)).fetchone()
            if row is None:
                self.connection.execute(
                    "INSERT INTO devices(uid, dev_id, rev_id, label, first_seen, last_seen) VALUES(?,?,?,?,?,?)",
                    (uid, dev_id, rev_id, label, now, now),
                )
            else:
                if label is not None:
                    self.connection.execute(
                        "UPDATE devices SET dev_id=?, rev_id=?, label=?, last_seen=? WHERE uid=?",
                        (dev_id, rev_id, label, now, uid),
                    )
                else:
                    self.connection.execute(
                        "UPDATE devices SET dev_id=?, rev_id=?, last_seen=? WHERE uid=?",
                        (dev_id, rev_id, now, uid),
                    )
            self.connection.commit()

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute("SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
        return [dict(row) for row in rows]

    def set_device_label(self, uid: str, label: str) -> None:
        with self._lock:
            self.connection.execute("UPDATE devices SET label=? WHERE uid=?", (label, uid))
            self.connection.commit()

    # -- runs ----------------------------------------------------------
    def start_run(
        self,
        *,
        uid: str,
        fw_name: str,
        fw_version: str,
        fw_commit: str,
        gui_version: str,
        mode: str,
        operator_name: str,
        selection: dict[str, Any],
    ) -> int:
        now = utc_now()
        with self._lock:
            row = self.connection.execute("SELECT uid FROM devices WHERE uid=?", (uid,)).fetchone()
            if row is None:
                self.record_device(uid)
            cursor = self.connection.execute(
                "INSERT INTO runs(uid, started_at, status, fw_name, fw_version, fw_commit, "
                "gui_version, mode, operator_name, selection) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    now,
                    "RUNNING",
                    fw_name,
                    fw_version,
                    fw_commit,
                    gui_version,
                    mode,
                    operator_name,
                    json.dumps(selection, separators=(",", ":")),
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def add_result(self, run_id: int, result: dict[str, Any]) -> None:
        measured = result.get("measured") or {}
        limits = result.get("limits") or {}
        # HIS-009: do not store the 0.0 defaults of an invalid measurement.
        measured_ok = bool(measured.get("valid", True))
        limits_ok = bool(limits.get("valid", True))
        with self._lock:
            self.connection.execute(
                "INSERT INTO results(run_id, test_id, group_code, iteration, result, duration_ms, "
                "reason, measured_value, measured_unit, measured_text, limit_min, limit_max, "
                "limit_unit, limits_text, reqs, finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    str(result.get("id", "")),
                    str(result.get("group", "")),
                    int(result.get("iteration", 1)),
                    str(result.get("result_name") or result.get("result", "N/A")),
                    int(result.get("duration_ms", 0)),
                    str(result.get("reason", "")),
                    measured.get("value") if measured_ok else None,
                    measured.get("unit") if measured_ok else None,
                    measured.get("text") if measured_ok else None,
                    limits.get("min") if limits_ok else None,
                    limits.get("max") if limits_ok else None,
                    limits.get("unit") if limits_ok else None,
                    limits.get("text") if limits_ok else None,
                    str(result.get("reqs", "")),
                    utc_now(),
                ),
            )
            self.connection.commit()

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        overall: str,
        n_pass: int,
        n_fail: int,
        n_skip: int,
        n_na: int,
    ) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE runs SET finished_at=?, status=?, overall=?, n_pass=?, n_fail=?, "
                "n_skip=?, n_na=? WHERE id=?",
                (utc_now(), status, overall, n_pass, n_fail, n_skip, n_na, run_id),
            )
            self.connection.commit()

    def update_counts(self, run_id: int, n_pass: int, n_fail: int, n_skip: int, n_na: int) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE runs SET n_pass=?, n_fail=?, n_skip=?, n_na=? WHERE id=?",
                (n_pass, n_fail, n_skip, n_na, run_id),
            )
            self.connection.commit()

    def list_runs(
        self,
        *,
        uid: str = "",
        date_from: str = "",
        date_to: str = "",
        overall: str = "",
        fw_version: str = "",
        mode: str = "",
        test_id: str = "",
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if uid:
            clauses.append("r.uid LIKE ?")
            params.append(f"%{uid}%")
        if date_from:
            clauses.append("r.started_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("r.started_at <= ?")
            params.append(date_to + "T23:59:59")
        if overall:
            clauses.append("r.overall = ?")
            params.append(overall)
        if fw_version:
            clauses.append("r.fw_version LIKE ?")
            params.append(f"%{fw_version}%")
        if mode:
            clauses.append("r.mode = ?")
            params.append(mode)
        if test_id:
            clauses.append("EXISTS (SELECT 1 FROM results t WHERE t.run_id=r.id AND t.test_id=?)")
            params.append(test_id)
        sql = (
            "SELECT r.*, d.label AS device_label "
            "FROM runs r LEFT JOIN devices d ON d.uid=r.uid "
            f"WHERE {' AND '.join(clauses)} ORDER BY r.started_at DESC, r.id DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._lock:
            rows = self.connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT r.*, d.label AS device_label, d.dev_id, d.rev_id "
                "FROM runs r LEFT JOIN devices d ON d.uid=r.uid WHERE r.id=?",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_results(self, run_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM results WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_results(self, run_id: int) -> None:
        with self._lock:
            self.connection.execute("DELETE FROM results WHERE run_id=?", (int(run_id),))
            self.connection.commit()

    def delete_runs(self, run_ids: Iterable[int]) -> None:
        ids = [int(value) for value in run_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            self.connection.execute(f"DELETE FROM results WHERE run_id IN ({placeholders})", ids)
            self.connection.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", ids)
            self.connection.commit()

    def purge_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            ids = [
                int(row[0])
                for row in self.connection.execute(
                    "SELECT id FROM runs WHERE started_at < ?", (cutoff,)
                ).fetchall()
            ]
            self.delete_runs(ids)
        return len(ids)

    # -- catalogue cache ----------------------------------------------
    def save_catalogue(self, fw_version: str, tests: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            for test in tests:
                self.connection.execute(
                    "INSERT OR REPLACE INTO catalogue(fw_version, test_id, group_code, title, level, "
                    "operator, destructive, timeout_ms, reqs) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        fw_version,
                        str(test.get("id", "")),
                        str(test.get("group", "")),
                        str(test.get("title", "")),
                        str(test.get("level_name", test.get("level", "S"))),
                        int(bool(test.get("operator", False))),
                        int(bool(test.get("destructive", False))),
                        int(test.get("timeout_ms", 0)),
                        str(test.get("reqs", "")),
                    ),
                )
            self.connection.commit()

    def load_catalogue(self, fw_version: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM catalogue WHERE fw_version=?", (fw_version,)
            ).fetchall()
        return {row["test_id"]: dict(row) for row in rows}

    # -- firmware operations -------------------------------------------
    def record_firmware_op(
        self,
        *,
        kind: str,
        outcome: str,
        uid: str = "",
        file_name: str = "",
        file_sha256: str = "",
        image_name: str = "",
        image_version: str = "",
        slot: str = "",
        detail: str = "",
    ) -> int:
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO firmware_ops(uid, at, kind, file_name, file_sha256, image_name, "
                "image_version, slot, outcome, detail) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    utc_now(),
                    kind,
                    file_name,
                    file_sha256,
                    image_name,
                    image_version,
                    slot,
                    outcome,
                    detail,
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def firmware_ops(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM firmware_ops ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    # -- exports -------------------------------------------------------
    def export_runs_json(self, path: str | Path) -> Path:
        p = Path(path)
        payload = {
            "exported_at": utc_now(),
            "gui": "HWVAL Studio",
            "devices": self.devices(),
            "runs": [],
        }
        for run in self.list_runs(limit=100000):
            entry = dict(run)
            entry["results"] = self.get_results(int(run["id"]))
            payload["runs"].append(entry)
        p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return p

    def export_runs_csv(self, path: str | Path) -> Path:
        import csv

        p = Path(path)
        with p.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "run_id",
                    "started_at",
                    "finished_at",
                    "uid",
                    "device_label",
                    "status",
                    "overall",
                    "fw_name",
                    "fw_version",
                    "mode",
                    "operator",
                    "n_pass",
                    "n_fail",
                    "n_skip",
                    "n_na",
                    "test_id",
                    "group",
                    "result",
                    "duration_ms",
                    "reason",
                    "measured",
                    "limits",
                    "reqs",
                ]
            )
            for run in self.list_runs(limit=100000):
                results = self.get_results(int(run["id"])) or [{}]
                for result in results:
                    writer.writerow(
                        [
                            run["id"],
                            run["started_at"],
                            run["finished_at"] or "",
                            run["uid"],
                            run.get("device_label") or "",
                            run["status"],
                            run["overall"] or "",
                            run["fw_name"] or "",
                            run["fw_version"] or "",
                            run["mode"],
                            run.get("operator_name") or "",
                            run["n_pass"],
                            run["n_fail"],
                            run["n_skip"],
                            run["n_na"],
                            result.get("test_id", ""),
                            result.get("group_code", ""),
                            result.get("result", ""),
                            result.get("duration_ms", ""),
                            result.get("reason", ""),
                            result.get("measured_text", ""),
                            result.get("limits_text", ""),
                            result.get("reqs", ""),
                        ]
                    )
        return p

    def database_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
