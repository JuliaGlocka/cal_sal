"""Acceptance criteria for the Salary Tracker application.

These tests describe the observable behavior currently provided by the app while
keeping Tkinter, network access, and the real user configuration out of tests.
"""

import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


SOURCE_PATH = Path(__file__).parents[1] / "salary_tracker 2.0.py"
MODULE_SPEC = importlib.util.spec_from_file_location("salary_tracker_2_0", SOURCE_PATH)
salary_tracker = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(salary_tracker)


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeEntry:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def delete(self, start, end):
        self.value = ""

    def insert(self, index, value):
        self.value = value


class FakeWidget:
    def __init__(self):
        self.values = {}

    def configure(self, **values):
        self.values.update(values)


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.destroyed = False

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def destroy(self):
        self.destroyed = True


def make_tracker(**values):
    tracker = salary_tracker.SalaryTracker.__new__(salary_tracker.SalaryTracker)
    defaults = {
        "hourly_rate": 0.0,
        "currency": "USD",
        "base_hourly_rate": 0.0,
        "base_currency": "USD",
        "api_key": "",
        "fx_rates": {},
        "sessions": [],
        "accumulated_seconds": 0.0,
        "session_start": None,
        "is_running": False,
        "history_visible": False,
        "root": FakeRoot(),
        "cur_var": FakeVar("USD"),
        "fx_status_var": FakeVar(),
        "salary_entry": FakeEntry(),
        "rate_lbl": FakeWidget(),
        "start_btn": FakeWidget(),
        "status_lbl": FakeWidget(),
    }
    defaults.update(values)
    for name, value in defaults.items():
        setattr(tracker, name, value)
    return tracker


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 8, 24), 0),  # Monday
        (date(2026, 8, 28), 4),  # Friday
        (date(2026, 8, 29), 5),  # Saturday
        (date(2026, 8, 30), 5),  # Sunday
    ],
)
def test_weekly_earnings_count_prior_weekdays_only(day, expected):
    """Acceptance: weekly estimates count weekdays before today, excluding today."""
    assert salary_tracker.weekdays_before_today_this_week(day) == expected


def test_monthly_earnings_count_prior_weekdays_and_exclude_today():
    """Acceptance: monthly estimates count weekdays from month start through yesterday."""
    assert salary_tracker.weekdays_before_today_this_month(date(2026, 8, 24)) == 15


def test_elapsed_time_is_zero_padded_and_truncates_fractional_seconds():
    """Acceptance: elapsed time displays as HH:MM:SS with fractional seconds truncated."""
    tracker = make_tracker()
    assert tracker.fmt_time(3661.9) == "01:01:01"
    assert tracker.fmt_time(0) == "00:00:00"


@pytest.mark.parametrize(
    ("currency", "amount", "expected"),
    [("USD", 1234.5, "$1,234.50"), ("JPY", 1234.5, "¥1,234")],
)
def test_amounts_use_currency_symbols_and_currency_precision(currency, amount, expected):
    """Acceptance: displayed earnings use the selected symbol and precision rules."""
    tracker = make_tracker(cur_var=FakeVar(currency))
    assert tracker.fmt(amount) == expected


def test_salary_input_accepts_comma_decimal_and_saves(monkeypatch):
    """Acceptance: setting `12,50` stores an hourly rate of 12.50."""
    tracker = make_tracker(salary_entry=FakeEntry("12,50"))
    tracker.update_rate_labels = lambda: None
    monkeypatch.setattr(tracker, "save_config", lambda: None)

    tracker.set_salary()

    assert tracker.hourly_rate == 12.5
    assert tracker.base_hourly_rate == 12.5
    assert tracker.base_currency == "USD"


@pytest.mark.parametrize("value", ["-5", "not-a-number"])
def test_invalid_or_negative_salary_input_becomes_zero(monkeypatch, value):
    """Acceptance: invalid and negative salary input never produces a negative rate."""
    tracker = make_tracker(salary_entry=FakeEntry(value))
    tracker.update_rate_labels = lambda: None
    monkeypatch.setattr(tracker, "save_config", lambda: None)

    tracker.set_salary()

    assert tracker.hourly_rate == 0.0


def test_currency_change_requires_fx_rates(monkeypatch):
    """Acceptance: currency changes are rejected until live FX rates are available."""
    tracker = make_tracker(currency="USD", cur_var=FakeVar("EUR"))
    monkeypatch.setattr(tracker, "save_config", lambda: None)

    tracker._on_cur_change()

    assert tracker.cur_var.get() == "USD"
    assert "Fetch live rates" in tracker.fx_status_var.get()


def test_currency_change_converts_from_base_currency_using_cached_rates(monkeypatch):
    """Acceptance: cached USD-based rates convert the base hourly salary accurately."""
    tracker = make_tracker(
        currency="USD",
        base_currency="USD",
        base_hourly_rate=10.0,
        cur_var=FakeVar("EUR"),
        fx_rates={"EUR": 0.8},
    )
    tracker.update_rate_labels = lambda: None
    monkeypatch.setattr(tracker, "save_config", lambda: None)

    tracker._on_cur_change()

    assert tracker.hourly_rate == 8.0
    assert tracker.currency == "EUR"
    assert tracker.salary_entry.value == "8.00"


def test_fetch_request_uses_user_agent_and_stores_rates(monkeypatch):
    """Acceptance: fetching live rates identifies the app and stores returned rates."""
    tracker = make_tracker()
    response = type("Response", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, exc_type, exc, tb: None,
        "read": lambda self: b'{"rates": {"EUR": 0.8}}',
    })()
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(salary_tracker.urllib.request, "urlopen", fake_urlopen)

    tracker._fetch_thread()

    assert tracker.fx_rates == {"EUR": 0.8}
    assert requests[0][0].get_header("User-agent") == "SalaryTracker/2.0"
    assert requests[0][1] == 10
    assert tracker.root.after_calls[0][1].__name__ == "_fx_ok"


def test_start_pause_and_resume_track_elapsed_time(monkeypatch):
    """Acceptance: start, pause, and resume preserve accumulated elapsed time."""
    moments = iter(
        [
            datetime(2026, 8, 24, 9, 0, 0),
            datetime(2026, 8, 24, 9, 0, 5),
            datetime(2026, 8, 24, 9, 0, 10),
        ]
    )
    monkeypatch.setattr(salary_tracker, "datetime", type("Clock", (), {"now": staticmethod(lambda: next(moments))}))
    tracker = make_tracker()

    tracker.toggle_tracking()
    tracker.toggle_tracking()
    tracker.toggle_tracking()

    assert tracker.is_running is True
    assert tracker.accumulated_seconds == 5
    assert tracker.session_start == datetime(2026, 8, 24, 9, 0, 10)


def test_reset_records_session_and_clears_timer(monkeypatch):
    """Acceptance: resetting a session records it, stops timing, and clears elapsed time."""
    tracker = make_tracker(
        hourly_rate=20.0,
        cur_var=FakeVar("USD"),
        accumulated_seconds=120.0,
        is_running=False,
    )
    tracker.update_rate_labels = lambda: None
    monkeypatch.setattr(tracker, "save_config", lambda: None)

    tracker.reset_tracking()

    assert len(tracker.sessions) == 1
    assert tracker.sessions[0]["duration"] == "00:02:00"
    assert tracker.sessions[0]["earned"] == 0.67
    assert tracker.accumulated_seconds == 0.0
    assert tracker.status_lbl.values["text"] == "Stopped"


def test_save_and_load_config_round_trip_and_limit_history(tmp_path, monkeypatch):
    """Acceptance: configuration round-trips and only the latest 100 sessions persist."""
    config_path = tmp_path / "salary_tracker.json"
    monkeypatch.setattr(salary_tracker, "CONFIG_PATH", config_path)
    sessions = [{"id": index} for index in range(105)]
    source = make_tracker(
        hourly_rate=25.5,
        currency="PLN",
        api_key="secret",
        fx_rates={"PLN": 4.0},
        sessions=sessions,
    )

    source.save_config()
    restored = make_tracker()
    restored.load_config()

    assert json.loads(config_path.read_text())["sessions"] == sessions[-100:]
    assert restored.hourly_rate == 25.5
    assert restored.currency == "PLN"
    assert restored.api_key == "secret"
    assert restored.fx_rates == {"PLN": 4.0}
    assert restored.sessions == sessions[-100:]


def test_malformed_config_does_not_crash_or_overwrite_defaults(tmp_path, monkeypatch):
    """Acceptance: malformed configuration is ignored and the app retains defaults."""
    config_path = tmp_path / "salary_tracker.json"
    config_path.write_text("{not valid json")
    monkeypatch.setattr(salary_tracker, "CONFIG_PATH", config_path)
    tracker = make_tracker()

    tracker.load_config()

    assert tracker.hourly_rate == 0.0
    assert tracker.currency == "USD"
    assert tracker.sessions == []


def test_close_records_session_saves_and_destroys_window(monkeypatch):
    """Acceptance: closing saves a tracked session and destroys the application window."""
    tracker = make_tracker(accumulated_seconds=2.0)
    tracker.hourly_rate = 10.0
    saved = []
    monkeypatch.setattr(tracker, "save_config", lambda: saved.append(True))

    tracker._on_close()

    assert len(tracker.sessions) == 1
    assert saved == [True]
    assert tracker.root.destroyed is True
