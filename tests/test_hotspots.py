import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from support import RepositoryTest, PROJECT
from git_analyzer import parse_numstat_log, build_file_hotspots, analyze_git, analyze_hotspots, GitError
from report_generator import render_html, write_reports
from scanner import scan_repository


def log_entry(records, hash="a" * 40, date="2026-01-01T00:00:00+00:00"):
    return f"commit:{hash}\t{date}\0\n" + "\0".join(records) + "\0"


def aggregate(text):
    return build_file_hotspots(parse_numstat_log(text)["commits"])


class ParserTests(unittest.TestCase):
    def test_real_fixture(self):
        result = parse_numstat_log((PROJECT / "tests/fixtures/git_numstat.txt").read_text(encoding="utf-8"))
        self.assertEqual(len(result["commits"]), 1)
        self.assertEqual(result["warnings"], [])
        self.assertIn("src/git_analyzer.py", [r["path"] for r in result["commits"][0]["files"]])

    def test_normal_counts(self):
        row = aggregate(log_entry(["12\t3\tsrc/a.py"]))[0]
        self.assertEqual((row["additions"], row["deletions"], row["churn"]), (12, 3, 15))

    def test_spaces_tabs_newlines_unicode_in_path(self):
        path = "src/中文 file\tpart\nnext.py"
        self.assertEqual(aggregate(log_entry([f"1\t0\t{path}"]))[0]["path"], path)

    def test_multiple_commits(self):
        row = aggregate(log_entry(["2\t1\ta"]) + log_entry(["3\t4\ta"], "b" * 40))[0]
        self.assertEqual((row["commit_count"], row["additions"], row["deletions"], row["churn"]), (2,5,5,10))

    def test_duplicate_record_count_once(self):
        row = aggregate(log_entry(["1\t0\ta", "2\t0\ta"]))[0]
        self.assertEqual(row["commit_count"], 1)
        self.assertEqual(row["churn"], 3)

    def test_latest_by_instant_not_log_order(self):
        row = aggregate(log_entry(["1\t0\ta"], date="2026-01-02T00:30:00+09:00") +
                        log_entry(["1\t0\ta"], "b" * 40, "2026-01-01T23:00:00+00:00"))[0]
        self.assertEqual(row["last_changed_at"], "2026-01-01T23:00:00+00:00")

    def test_binary(self):
        row = aggregate(log_entry(["-\t-\timage.png"]))[0]
        self.assertTrue(row["binary"])
        self.assertIsNone(row["churn"])
        self.assertEqual(row["commit_count"], 1)

    def test_text_binary_transition_unknown(self):
        row = aggregate(log_entry(["10\t2\ta"]) + log_entry(["-\t-\ta"], "b" * 40))[0]
        self.assertEqual(row["commit_count"], 2)
        self.assertIsNone(row["additions"])

    def test_sort_ties(self):
        rows = aggregate(log_entry(["2\t0\tb", "1\t0\tc", "2\t0\ta", "5\t0\tz"]) + log_entry(["1\t0\tc"], "b"*40))
        self.assertEqual([r["path"] for r in rows], ["z","c","a","b"])

    def test_empty(self):
        self.assertEqual(aggregate(""), [])

    def test_corrupt_records_warn_and_continue(self):
        parsed = parse_numstat_log(log_entry(["broken", "-\t2\ta", "1\t0\tgood"]))
        self.assertEqual(len(parsed["warnings"]),2)
        self.assertEqual(build_file_hotspots(parsed["commits"])[0]["path"],"good")

    def test_invalid_header_does_not_attach_to_previous(self):
        parsed = parse_numstat_log(log_entry(["1\t0\ta"]) + "commit:bad\0\n1\t0\tb\0")
        self.assertEqual(len(parsed["warnings"]),2)
        self.assertEqual(len(build_file_hotspots(parsed["commits"])),1)


class HotspotIntegrationTests(RepositoryTest):
    def test_limit_and_empty_commits(self):
        self.init(); self.write("a", "one\n"); self.commit(); self.commit("empty")
        self.write("a", "one\ntwo\n"); self.commit()
        result = analyze_hotspots(self.root, analyze_git(self.root), 2)
        self.assertEqual(result["analyzed_commits"],2)
        self.assertEqual(result["hotspots"][0]["additions"],1)
        self.assertEqual(result["hotspots"][0]["commit_count"],1)

    def test_empty_repository(self):
        self.init()
        self.assertEqual(analyze_hotspots(self.root,analyze_git(self.root))["hotspots"],[])

    def test_real_binary_excluded(self):
        self.init(); self.write("blob",b"\0binary"); self.write("a","one\n"); self.commit()
        result=analyze_hotspots(self.root,analyze_git(self.root))
        self.assertEqual([r["path"] for r in result["hotspots"]],["a"])
        self.assertEqual(result["binary_files"][0]["path"],"blob")

    def test_top_ten_not_commit_limit(self):
        self.init()
        for i in range(12): self.write(f"f{i:02}","line\n")
        self.commit()
        result=analyze_hotspots(self.root,analyze_git(self.root),1)
        self.assertEqual(len(result["hotspots"]),10)
        self.assertEqual(result["analyzed_commits"],1)

    def test_shallow_warning(self):
        self.init(); self.commit()
        self.git("rev-parse","HEAD")
        (self.root/".git/shallow").write_text(self.git("rev-parse","HEAD").stdout,encoding="ascii")
        result=analyze_hotspots(self.root,analyze_git(self.root))
        self.assertIn("Shallow clone",result["warnings"][0])

    def test_error_retains_reason(self):
        with patch("git_analyzer.run_git",side_effect=GitError("Git command failed: damaged")):
            with self.assertRaisesRegex(GitError,"damaged"):
                analyze_hotspots(self.root,{"head":"a"*40,"shallow":False})

    def test_bad_limit_cli(self):
        for value in ("0","-1","abc","1.5"):
            result=subprocess.run([sys.executable,str(PROJECT/"src/main.py"),str(self.root),"--git-limit",value],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("positive integer",result.stderr)

    def test_json_html_same_data_and_escape(self):
        self.init(); self.commit()
        history=analyze_hotspots(self.root,analyze_git(self.root))
        history["hotspots"]=aggregate(log_entry(['3\t2\t<img src=x>&.py']))
        data={"schema_version":1,"repository_name":"test","repository_path":str(self.root),"generated_at":"now",
              "git":analyze_git(self.root),"scan":scan_repository(self.root),"git_history":history}
        output=self.temporary/"report"
        write_reports(data,output)
        saved=json.loads((output/"report.json").read_text(encoding="utf-8"))
        html=(output/"report.html").read_text(encoding="utf-8")
        self.assertEqual(saved["git_history"],history)
        self.assertIn("&lt;img src=x&gt;&amp;.py",html)
        self.assertNotIn("<img src=x>",html)
        self.assertIn("Git文件变更热点",html)

    def test_cli_adds_json_history(self):
        self.init(); self.write("a","one\n"); self.commit()
        output=self.temporary/"out"
        result=subprocess.run([sys.executable,str(PROJECT/"src/main.py"),str(self.root),"--output",str(output),"--git-limit","1"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        history=json.loads((output/"report.json").read_text(encoding="utf-8"))["git_history"]
        self.assertEqual(history["requested_limit"],1)
        self.assertEqual(history["hotspots"][0]["churn"],1)
