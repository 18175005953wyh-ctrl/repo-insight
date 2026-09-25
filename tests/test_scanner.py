from unittest.mock import patch

from support import RepositoryTest
from scanner import MAX_TEXT_BYTES, scan_repository


class ScannerTests(RepositoryTest):
    def test_counts_and_nonempty_lines(self):
        self.write("src/main.C", "int main() {}\n\n// comment\n")
        self.write("README.md", "Title\n")
        result = scan_repository(self.root)
        self.assertEqual((result["file_count"], result["directory_count"], result["nonempty_lines"]), (2, 1, 3))
        self.assertEqual(result["extension_counts"], {".c": 1, ".md": 1})

    def test_prunes_excluded_directories_recursively(self):
        for name in (".git", "build", "node_modules", ".venv", "venv", "__pycache__", "out", ".vs"):
            self.write(f"src/{name}/deep/ignored.py", "TODO")
        self.write("src/real.py", "pass")
        result = scan_repository(self.root)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["directory_count"], 1)
        self.assertEqual(len(result["skipped_directories"]), 8)

    def test_output_directory_excluded(self):
        self.write("reports/report.html", "old report TODO")
        self.write("main.py", "pass")
        result = scan_repository(self.root, (self.root / "reports",))
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["directory_count"], 0)

    def test_binary_and_decode_error(self):
        self.write("fake.py", b"\x00TODO")
        self.write("bad.txt", b"\xff\xfe")
        self.write("normal.unknown", "Readable\n")
        result = scan_repository(self.root)
        self.assertEqual(result["file_count"], 3)
        self.assertEqual(result["text_file_count"], 1)
        self.assertEqual(result["nonempty_lines"], 1)
        self.assertEqual({item["reason"] for item in result["skipped_text"]}, {"binary", "decode_error"})

    def test_empty_and_bom(self):
        self.write("empty", "")
        self.write("bom.txt", b"\xef\xbb\xbf\nhello\r\n \r\n")
        result = scan_repository(self.root)
        self.assertEqual(result["nonempty_lines"], 1)
        self.assertEqual(result["text_file_count"], 2)
        self.assertEqual(result["extension_counts"]["[no extension]"], 1)

    def test_size_limit(self):
        self.write("large.txt", b"a" * (MAX_TEXT_BYTES + 1))
        result = scan_repository(self.root)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["skipped_text"][0]["reason"], "over_size_limit")

    def test_markers_word_boundaries_and_repeated_matches(self):
        self.write("a.py", "# TODO todo FIXME BUG debug BUGFIX\n# bug\n")
        result = scan_repository(self.root)
        self.assertEqual(result["marker_counts"], {"TODO": 2, "FIXME": 1, "BUG": 2})
        self.assertEqual(result["markers"][-1]["line"], 2)

    def test_marker_details_are_bounded(self):
        self.write("a.txt", "TODO\n" * 1005)
        result = scan_repository(self.root)
        self.assertEqual(result["marker_counts"]["TODO"], 1005)
        self.assertEqual(len(result["markers"]), 1000)
        self.assertTrue(result["marker_details_truncated"])

    def test_largest_ten_sorted(self):
        for index in range(12):
            self.write(f"{index:02}.txt", "x" * index)
        result = scan_repository(self.root)
        self.assertEqual([item["bytes"] for item in result["largest_files"]], list(range(11, 1, -1)))

    def test_engineering_check_and_test_alternative(self):
        self.write("README.md", "")
        self.write("LICENSE", "")
        self.write(".gitignore", "")
        (self.root / "test").mkdir()
        self.assertTrue(all(scan_repository(self.root)["engineering_files"].values()))

    def test_missing_engineering_files(self):
        self.write("src/README.md", "not at root")
        self.assertFalse(any(scan_repository(self.root)["engineering_files"].values()))

    def test_link_exclusion_without_requiring_windows_symlink_privilege(self):
        self.write("external/file.txt", "outside")
        self.write("linked.txt", "outside")
        with patch("scanner.is_link", side_effect=lambda p: p.name in {"external", "linked.txt"}):
            result = scan_repository(self.root)
        self.assertEqual(result["file_count"], 0)
        self.assertEqual(result["directory_count"], 0)
        self.assertEqual(len(result["skipped_links"]), 2)

    def test_read_failure_keeps_size_count_and_warning(self):
        path = self.write("denied.txt", "x")
        with patch("scanner.inspect_text", side_effect=PermissionError(13, "denied", str(path))):
            result = scan_repository(self.root)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["text_file_count"], 0)
        self.assertEqual(result["warnings"][0]["reason"], "PermissionError")

    def test_empty_directory_counts(self):
        (self.root / "empty").mkdir()
        result = scan_repository(self.root)
        self.assertEqual((result["file_count"], result["directory_count"]), (0, 1))

    def test_git_file_worktree_metadata_excluded(self):
        self.write(".git", "gitdir: elsewhere")
        self.assertEqual(scan_repository(self.root)["file_count"], 0)
