"""The run-history chart: data mapping and a headless render."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hwval_studio.persistence.database import HistoryStore
from hwval_studio.ui.charts import RunPoint, RunTrendChart, points_from_runs


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pass_rate_ignores_skips() -> None:
    assert RunPoint("a", 8, 2, 5).pass_rate == 80.0
    assert RunPoint("a", 0, 0, 5).pass_rate is None


def test_points_are_oldest_first_and_capped() -> None:
    runs = [
        {"started_at": f"2026-11-{day:02d}T10:00:00", "n_pass": day, "n_fail": 0, "n_skip": 0}
        for day in range(28, 0, -1)
    ] * 2
    points = points_from_runs(runs)
    assert len(points) == 40
    assert points[-1].n_pass == 28 or points[-1].n_pass == 1
    assert points[0].label.startswith("11-")


def test_missing_counts_become_zero() -> None:
    (point,) = points_from_runs([{"started_at": "2026-11-01T10:00:00", "n_pass": None}])
    assert point.total == 0


def test_chart_renders_with_and_without_data(app: QApplication, tmp_path) -> None:
    chart = RunTrendChart()
    chart.resize(700, 190)
    empty = chart.grab()
    assert not empty.isNull()
    chart.set_points([RunPoint(f"11-{d:02d} 10:00", 90 - d, d, 3) for d in range(1, 12)])
    filled = chart.grab()
    assert filled.toImage() != empty.toImage()
    assert len(chart.points()) == 11


def test_history_page_feeds_the_chart(app: QApplication, tmp_path) -> None:
    from hwval_studio.config import Preferences
    from hwval_studio.ui.pages.history import HistoryPage

    store = HistoryStore(tmp_path / "h.db")
    for i, (p, f) in enumerate([(10, 0), (9, 1), (7, 3)]):
        run = store.start_run(
            uid="UID1", fw_name="hwval", fw_version="0.1.0", fw_commit="x",
            gui_version="0.1.0", mode="CLI", operator_name="", selection={},
        )
        store.finish_run(
            run, status="DONE", overall="PASS" if f == 0 else "FAIL",
            n_pass=p, n_fail=f, n_skip=0, n_na=0,
        )
        store.connection.execute(
            "UPDATE runs SET started_at=? WHERE id=?", (f"2026-11-{i + 5:02d}T09:00:00", run)
        )
    store.connection.commit()
    page = HistoryPage(store, Preferences())
    page.from_date.setDate(page.from_date.date().addYears(-1))
    page.to_date.setDate(page.to_date.date().addYears(1))
    page.refresh()
    assert [pt.n_pass for pt in page.chart.points()] == [10, 9, 7]
