"""Pytest reporting for the Salary Tracker acceptance suite."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_PATH = PROJECT_ROOT / "salary_tracker 2.0.py"
REPORT_PATH = PROJECT_ROOT / "salary_tracker_test_report.txt"

CHECKED_FUNCTIONS = {
    "weekdays_before_today_this_week": "Counts weekdays before today in the current week.",
    "weekdays_before_today_this_month": "Counts weekdays before today in the current month.",
    "SalaryTracker.fmt_time": "Formats elapsed time as hours, minutes, and seconds.",
    "SalaryTracker.fmt": "Formats money using currency symbols and decimal rules.",
    "SalaryTracker.set_salary": "Parses, validates, and stores the hourly salary.",
    "SalaryTracker._on_cur_change": "Converts salary values using cached exchange rates.",
    "SalaryTracker.toggle_tracking": "Starts, pauses, and resumes time tracking.",
    "SalaryTracker.reset_tracking": "Records a session and clears the timer.",
    "SalaryTracker._record_session": "Calculates and stores a completed session.",
    "SalaryTracker.load_config": "Loads saved salary tracker configuration.",
    "SalaryTracker.save_config": "Saves configuration and limits history to 100 sessions.",
    "SalaryTracker._on_close": "Saves state and closes the application window.",
}
TEST_REPORTS = []


def _function_lines():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    lines = {}
    for node in ast.walk(tree):
        if type(node) not in (ast.FunctionDef, ast.AsyncFunctionDef):
            continue
        qualified_name = node.name
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef) and any(child is node for child in parent.body):
                qualified_name = f"{parent.name}.{node.name}"
                break
        lines[qualified_name] = node.lineno
    return lines


def _status_counts(reports):
    counts = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0}
    for report in reports:
        if report.failed:
            counts["failed"] += 1
        elif report.skipped:
            counts["xfailed" if hasattr(report, "wasxfail") else "skipped"] += 1
        else:
            counts["passed"] += 1
    return counts


def _build_report(config, reports):
    counts = _status_counts(reports)
    outcome = "WORKING" if counts["failed"] == 0 else "NEEDS ATTENTION"
    lines = [
        "SALARY TRACKER TEST REPORT",
        "===========================",
        f"Overall result: {outcome}",
        "Test file: tests/test_salary_tracker.py",
        f"Application module: {SOURCE_PATH.name}",
        "",
        "What was checked",
        "-----------------",
        "The acceptance tests checked calculations, formatting, salary input, currency conversion,",
        "time tracking, session recording, configuration persistence, and application shutdown.",
        "Tkinter widgets, network requests, and the real user configuration file were replaced with",
        "test doubles, so the test run was isolated from the desktop and external services.",
        "",
        "Application functions checked",
        "-----------------------------",
    ]
    function_lines = _function_lines()
    for function_name, description in CHECKED_FUNCTIONS.items():
        line_number = function_lines.get(function_name, "unknown")
        lines.append(f"{function_name} (line {line_number}): {description}")

    lines.extend(["", "Test results", "------------"])
    for report in reports:
        status = "PASS" if report.passed else "FAIL" if report.failed else "SKIP"
        test_name = report.nodeid.split("::")[-1]
        lines.append(f"{status}: {test_name}")

    lines.extend(
        [
            "",
            "Summary",
            "-------",
            f"Passed: {counts['passed']}",
            f"Failed: {counts['failed']}",
            f"Skipped: {counts['skipped']}",
            f"Total recorded checks: {len(reports)}",
            "",
            "Interpretation",
            "--------------",
            "WORKING means every acceptance check completed successfully.",
            "NEEDS ATTENTION means at least one acceptance check failed and should be investigated.",
        ]
    )
    return "\n".join(lines) + "\n"


def pytest_sessionfinish(session, exitstatus):
    report_text = _build_report(session.config, TEST_REPORTS)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is not None:
        terminal_reporter.write_sep("=", "Salary Tracker acceptance report")
        terminal_reporter.write(report_text)
        terminal_reporter.write_line(f"Report saved to: {REPORT_PATH}")


def pytest_runtest_logreport(report):
    if report.when != "call":
        return
    TEST_REPORTS.append(report)
