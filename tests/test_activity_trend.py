import copy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from support import PROJECT, RepositoryTest
from git_analyzer import (analyze_git, analyze_git_history, analyze_hotspots,
                          build_activity_trend, build_file_hotspots, parse_numstat_log, run_git)
from main import format_activity_summary
from report_generator import render_activity


def commit(stamp, files=None, number=1):
    return {"hash": f"{number:040x}", "date": stamp, "files": files or []}


def text(path="a", added=1, deleted=0):
    return {"path": path, "additions": added, "deletions": deleted, "binary": False}


def binary(path="image.png"):
    return {"path": path, "additions": None, "deletions": None, "binary": True}


def trend(*commits, period="day"):
    return build_activity_trend(list(commits), period)["buckets"]


class ActivityTests(unittest.TestCase):
    def test_same_day(self):
        buckets = trend(commit("2026-10-01T01:00:00+00:00"), commit("2026-10-01T23:00:00+00:00", number=2))
        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0]["commit_count"], 2)

    def test_different_utc_dates(self):
        buckets = trend(commit("2026-10-01T23:59:00+00:00"), commit("2026-10-02T00:00:00+00:00", number=2))
        self.assertEqual([b["period_start"] for b in buckets], ["2026-10-01", "2026-10-02"])

    def test_same_instant_different_offsets(self):
        buckets = trend(commit("2026-10-02T00:30:00+08:00"), commit("2026-10-01T16:30:00+00:00", number=2))
        self.assertEqual([(b["period_start"], b["commit_count"]) for b in buckets], [("2026-10-01", 2)])

    def test_negative_offset_moves_forward(self):
        self.assertEqual(trend(commit("2026-10-01T23:30:00-03:00"))[0]["period_start"], "2026-10-02")

    def test_week_monday(self):
        buckets = trend(commit("2026-09-28T00:00:00+00:00"), commit("2026-10-04T23:59:00+00:00", number=2), period="week")
        self.assertEqual([(b["period_start"], b["commit_count"]) for b in buckets], [("2026-09-28", 2)])

    def test_cross_year_week(self):
        self.assertEqual(trend(commit("2021-01-01T00:00:00+00:00"), period="week")[0]["period_start"], "2020-12-28")

    def test_month(self):
        buckets = trend(commit("2026-10-01T00:00:00+00:00"), commit("2026-10-31T23:59:00+00:00", number=2), period="month")
        self.assertEqual([(b["period_start"], b["commit_count"]) for b in buckets], [("2026-10", 2)])

    def test_unsorted_cross_year_months(self):
        buckets = trend(commit("2027-01-01T00:00:00+00:00"), commit("2026-12-01T00:00:00+00:00", number=2), period="month")
        self.assertEqual([b["period_start"] for b in buckets], ["2026-12", "2027-01"])

    def test_missing_days(self):
        buckets = trend(commit("2026-10-01T00:00:00+00:00"), commit("2026-10-03T00:00:00+00:00", number=2))
        self.assertEqual(buckets[1], {"period_start": "2026-10-02", "commit_count": 0, "files_changed": 0,
                                    "additions": 0, "deletions": 0, "churn": 0, "binary_changes": 0})
        self.assertEqual(len(buckets), 3)

    def test_missing_weeks(self):
        buckets = trend(commit("2026-09-14T00:00:00+00:00"), commit("2026-09-28T00:00:00+00:00", number=2), period="week")
        self.assertEqual([b["period_start"] for b in buckets], ["2026-09-14", "2026-09-21", "2026-09-28"])
        self.assertEqual(buckets[1]["commit_count"], 0)

    def test_missing_months_across_year(self):
        buckets = trend(commit("2026-11-30T00:00:00+00:00"), commit("2027-02-01T00:00:00+00:00", number=2), period="month")
        self.assertEqual([b["period_start"] for b in buckets], ["2026-11", "2026-12", "2027-01", "2027-02"])
        self.assertEqual([b["commit_count"] for b in buckets], [1, 0, 0, 1])

    def test_leap_day(self):
        buckets = trend(commit("2024-02-28T00:00:00+00:00"), commit("2024-03-01T00:00:00+00:00", number=2))
        self.assertEqual(buckets[1]["period_start"], "2024-02-29")

    def test_empty_commit(self):
        bucket = trend(commit("2026-10-01T00:00:00+00:00"))[0]
        self.assertEqual((bucket["commit_count"], bucket["churn"], bucket["files_changed"]), (1, 0, 0))

    def test_same_path_deduplicated_but_records_summed(self):
        bucket = trend(commit("2026-10-01T00:00:00+00:00", [text(), text(added=2)]),
                       commit("2026-10-01T01:00:00+00:00", [text(deleted=2)], 2))[0]
        self.assertEqual((bucket["commit_count"], bucket["files_changed"], bucket["additions"], bucket["deletions"], bucket["churn"]), (2, 1, 4, 2, 6))

    def test_same_file_distinct_buckets(self):
        buckets = trend(commit("2026-10-01T00:00:00+00:00", [text()]), commit("2026-10-02T00:00:00+00:00", [text()], 2))
        self.assertEqual([b["files_changed"] for b in buckets], [1, 1])

    def test_text_totals(self):
        bucket = trend(commit("2026-10-01T00:00:00+00:00", [text("a", 9, 4), text("b", 3, 7)]))[0]
        self.assertEqual((bucket["files_changed"], bucket["additions"], bucket["deletions"], bucket["churn"]), (2, 12, 11, 23))

    def test_binary_separate(self):
        bucket = trend(commit("2026-10-01T00:00:00+00:00", [binary(), binary(), text()]))[0]
        self.assertEqual((bucket["binary_changes"], bucket["files_changed"], bucket["churn"]), (2, 2, 1))

    def test_text_binary_transition_keeps_known_text_only(self):
        bucket = trend(commit("2026-10-01T00:00:00+00:00", [text("a", 4, 2), binary("a")]))[0]
        self.assertEqual((bucket["files_changed"], bucket["churn"], bucket["binary_changes"]), (1, 6, 1))

    def test_empty_history(self):
        self.assertEqual(build_activity_trend([]), {"period": "week", "timezone": "UTC", "buckets": []})

    def test_no_mutation(self):
        commits = [commit("2026-10-01T00:00:00+00:00", [text(), binary()])]
        original = copy.deepcopy(commits)
        build_activity_trend(commits)
        self.assertEqual(commits, original)

    def test_invalid_period(self):
        with self.assertRaisesRegex(ValueError, "trend-period"):
            build_activity_trend([], "year")

    def test_naive_date_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            build_activity_trend([commit("2026-10-01T00:00:00")])

    def test_latest_possible_month(self):
        self.assertEqual(trend(commit("9999-12-31T23:59:59+00:00"), period="month")[0]["period_start"], "9999-12")

    def test_corrupt_date_and_numstat_warn(self):
        raw = "commit:" + "a" * 40 + "\tbad\0\n1\t0\torphan\0"
        raw += "commit:" + "b" * 40 + "\t2026-10-01T00:00:00+00:00\0\nbroken\0\n2\t1\ta\0"
        parsed = parse_numstat_log(raw)
        self.assertEqual(len(parsed["warnings"]), 3)
        self.assertEqual(build_activity_trend(parsed["commits"])["buckets"][0]["churn"], 3)

    def test_utc_overflow_warns(self):
        raw = "commit:" + "a" * 40 + "\t0001-01-01T00:00:00+08:00\0"
        parsed = parse_numstat_log(raw)
        self.assertEqual(len(parsed["warnings"]), 1)
        self.assertEqual(parsed["commits"], [])

    def test_utc_z_suffix_supported_on_python310(self):
        raw = "commit:" + "a" * 40 + "\t2026-10-01T00:00:00Z\0\n1\t0\ta\0"
        parsed = parse_numstat_log(raw)
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual(build_activity_trend(parsed["commits"], "day")["buckets"][0]["period_start"], "2026-10-01")
        self.assertEqual(build_file_hotspots(parsed["commits"])[0]["last_changed_at"], "2026-10-01T00:00:00Z")

    def test_terminal_latest_eight(self):
        activity = build_activity_trend([commit("2026-10-01T00:00:00+00:00"), commit("2026-10-15T00:00:00+00:00", number=2)], "day")
        output = format_activity_summary(activity)
        self.assertIn("latest 8 of 15 buckets", output)
        self.assertNotIn("2026-10-07", output)
        self.assertIn("2026-10-08", output)
        self.assertEqual(len(output.splitlines()), 9)

    def test_terminal_empty(self):
        self.assertEqual(format_activity_summary(build_activity_trend([])), "No Git activity in this history window.")

    def test_html_latest_twelve(self):
        activity = build_activity_trend([commit("2026-10-01T00:00:00+00:00"), commit("2026-10-15T00:00:00+00:00", number=2)], "day")
        rendered = render_activity(activity)
        self.assertNotIn("2026-10-03", rendered)
        self.assertIn("2026-10-04", rendered)
        self.assertIn("12 / 15", rendered)
        self.assertEqual(len(activity["buckets"]), 15)

    def test_html_zero_churn(self):
        activity = build_activity_trend([commit("2026-10-01T00:00:00+00:00")])
        self.assertIn("width:0.00%", render_activity(activity))

    def test_html_all_zero_and_empty(self):
        activity = build_activity_trend([commit("2026-10-01T00:00:00+00:00")])
        activity["buckets"][0]["commit_count"] = 0
        self.assertEqual(render_activity(activity).count("width:0.00%"), 2)
        self.assertIn("No Git activity", render_activity(build_activity_trend([])))

    def test_html_escape_and_no_external_resources(self):
        activity = build_activity_trend([commit("2026-10-01T00:00:00+00:00")])
        payload = '<script>alert("x")</script>'
        activity["period"] = activity["timezone"] = activity["buckets"][0]["period_start"] = payload
        rendered = render_activity(activity)
        self.assertNotIn(payload, rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<link", rendered)

    def test_html_width_normalized_to_displayed_maximum(self):
        commits = [commit("2026-10-01T00:00:00+00:00", [text(added=1000)]),
                   commit("2026-10-14T00:00:00+00:00", [text(added=5)], 2),
                   commit("2026-10-15T00:00:00+00:00", [text(added=10)], 3)]
        rendered = render_activity(build_activity_trend(commits, "day"))
        self.assertIn("width:50.00%", rendered)
        self.assertNotIn("2026-10-01", rendered)


class ActivityIntegrationTests(RepositoryTest):
    def dated_history(self):
        self.init()
        self.write("a", "one\n")
        self.git("add", ".")
        self.git("commit", "--date", "2026-09-01T00:00:00+00:00", "-m", "first")
        self.git("commit", "--allow-empty", "--date", "2026-09-15T00:00:00+00:00", "-m", "empty")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(PROJECT / "src/main.py"), str(self.root),
                               "--output", str(self.temporary / "report"), *args], capture_output=True, text=True, encoding="utf-8", timeout=40)

    def test_single_numstat_read_and_parse(self):
        self.dated_history()
        git = analyze_git(self.root)
        with patch("git_analyzer.run_git", wraps=run_git) as run, patch("git_analyzer.parse_numstat_log", wraps=parse_numstat_log) as parse:
            result = analyze_git_history(self.root, git)
        self.assertEqual(run.call_count, 1)
        self.assertIn("--numstat", run.call_args.args)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(sum(b["commit_count"] for b in result["activity"]["buckets"]), 2)

    def test_hotspot_compatibility_golden(self):
        self.dated_history()
        result = analyze_git_history(self.root, analyze_git(self.root), 100, "month")
        golden = copy.deepcopy(result["hotspots"])
        golden[0]["last_changed_at"] = golden[0]["last_changed_at"].replace("Z", "+00:00")
        self.assertEqual(golden, [{"path": "a", "commit_count": 1, "additions": 1,
            "deletions": 0, "churn": 1, "last_changed_at": "2026-09-01T00:00:00+00:00", "binary": False}])
        old = analyze_hotspots(self.root, analyze_git(self.root))
        for key in ("hotspots", "binary_files", "requested_limit", "analyzed_commits", "warnings", "head"):
            self.assertEqual(result[key], old[key])

    def test_limit_shared_by_both_analyses(self):
        self.dated_history()
        result = analyze_git_history(self.root, analyze_git(self.root), 1, "day")
        self.assertEqual(result["analyzed_commits"], 1)
        self.assertEqual(result["hotspots"], [])
        self.assertEqual(len(result["activity"]["buckets"]), 1)
        self.assertEqual(result["activity"]["buckets"][0]["period_start"], "2026-09-15")

    def test_empty_git_does_not_read_log(self):
        self.init()
        git = analyze_git(self.root)
        with patch("git_analyzer.run_git") as run:
            result = analyze_git_history(self.root, git)
        run.assert_not_called()
        self.assertEqual(result["activity"]["buckets"], [])

    def test_warnings_preserved(self):
        raw = "commit:" + "a" * 40 + "\t2026-10-01T00:00:00+00:00\0\nbad\0"
        with patch("git_analyzer.run_git", return_value=subprocess.CompletedProcess([], 0, raw, "git diagnostic")):
            result = analyze_git_history(self.root, {"head": "a" * 40, "shallow": True})
        self.assertEqual(len(result["warnings"]), 3)
        self.assertIn("Shallow clone", result["warnings"][0])
        self.assertEqual(result["activity"]["buckets"][0]["commit_count"], 1)

    def test_cli_invalid_and_case_sensitive_period(self):
        for period in ("year", "Week", "DAY"):
            result = self.cli("--trend-period", period)
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid choice", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_default_week(self):
        self.dated_history()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Git Activity Trend (week, UTC", result.stdout)
        data = json.loads((self.temporary / "report/report.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["git_history"]["activity"]["period"], "week")

    def test_cli_month(self):
        self.dated_history()
        result = self.cli("--trend-period", "month")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2026-09  commits=2", result.stdout)

    def test_json_html_terminal_same_model_and_limits(self):
        self.dated_history()
        result = self.cli("--trend-period", "day")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.temporary / "report"
        data = json.loads((output / "report.json").read_text(encoding="utf-8"))
        activity = data["git_history"]["activity"]
        self.assertEqual(len(activity["buckets"]), 15)
        self.assertIn(format_activity_summary(activity), result.stdout)
        html = (output / "report.html").read_text(encoding="utf-8")
        self.assertIn(render_activity(activity), html)
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("<script", html)
        self.assertLess(html.index("Git文件变更热点"), html.index("Git提交活动趋势"))

    def test_cli_empty_message(self):
        self.init()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No Git activity in this history window.", result.stdout)
