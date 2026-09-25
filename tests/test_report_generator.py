import json
from html.parser import HTMLParser
from unittest.mock import patch

from support import RepositoryTest
from report_generator import render_html, write_reports
from scanner import scan_repository


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))


class ReportTests(RepositoryTest):
    def sample(self):
        return {"schema_version": 1, "generated_at": "2026-01-01T00:00:00+00:00", "repository_name": "示例",
                "repository_path": str(self.root), "scan": scan_repository(self.root),
                "git": {"commit_count": 0, "committer_count": 0, "latest_commit": None, "recent_commits": [], "head": None, "history_scope": "HEAD", "shallow": False}}

    def test_json_roundtrip(self):
        data = self.sample()
        output = self.root / "reports"
        write_reports(data, output)
        self.assertEqual(json.loads((output / "report.json").read_text(encoding="utf-8")), data)
        self.assertIn("示例", (output / "report.json").read_text(encoding="utf-8"))

    def test_all_untrusted_text_escaped(self):
        payload = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        data = self.sample()
        data["repository_name"] = data["repository_path"] = payload
        data["git"]["recent_commits"] = [{"hash": "ab123", "subject": payload, "committer": payload, "date": payload}]
        data["scan"]["largest_files"] = [{"path": payload, "bytes": 1}]
        data["scan"]["markers"] = [{"marker": "TODO", "path": payload, "line": 1, "excerpt": payload}]
        data["scan"]["extension_counts"] = {payload: 1}
        data["scan"]["file_count"] = 1
        rendered = render_html(data)
        self.assertNotIn(payload, rendered)
        self.assertIn("&lt;script&gt;", rendered)
        parsed = Tags()
        parsed.feed(rendered)
        self.assertFalse(any(tag in {"script", "img"} for tag, _ in parsed.tags))

    def test_empty_report_no_division_by_zero(self):
        rendered = render_html(self.sample())
        self.assertIn("仓库尚无提交", rendered)
        self.assertIn("没有可统计的文件", rendered)

    def test_self_contained_sections(self):
        rendered = render_html(self.sample())
        for section in ("文件类型分布", "工程文件检查", "最近提交", "待办标记", "最大的十个文件", "扫描范围与限制"):
            self.assertIn(section, rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<link", rendered)
        self.assertIn("width=device-width", rendered)

    def test_existing_reports_replaced(self):
        output = self.root / "reports"
        data = self.sample()
        write_reports(data, output)
        data["repository_name"] = "Updated"
        write_reports(data, output)
        self.assertEqual(json.loads((output / "report.json").read_text(encoding="utf-8"))["repository_name"], "Updated")
        self.assertFalse(list(output.glob("*.tmp")))

    def test_write_error_cleanup(self):
        output = self.root / "reports"
        with patch("report_generator.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_reports(self.sample(), output)
        self.assertFalse(list(output.glob("*.tmp")))

    def test_parent_file_error(self):
        file = self.write("file.txt", "data")
        with self.assertRaises(OSError):
            write_reports(self.sample(), file / "reports")
