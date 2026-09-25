import json
import subprocess
import sys

from support import PROJECT, RepositoryTest


class CliTests(RepositoryTest):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(PROJECT / "src/main.py"), *map(str, args)], capture_output=True, text=True, encoding="utf-8", cwd=self.root, timeout=40)

    def test_missing_path(self):
        result = self.run_cli(self.root / "absent")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_file_as_target(self):
        result = self.run_cli(self.write("plain.txt", "x"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a directory", result.stderr)

    def test_non_git_directory(self):
        result = self.run_cli(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a Git", result.stderr)

    def test_real_repository_and_repeat_stability(self):
        self.init()
        self.write("README.md", "Title\n\nTODO one\n")
        self.commit("Real example")
        result = self.run_cli(".")
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads((self.root / "reports/report.json").read_text(encoding="utf-8"))
        self.assertEqual(first["scan"]["file_count"], 1)
        self.assertEqual(first["git"]["commit_count"], 1)
        self.assertEqual(self.run_cli(".").returncode, 0)
        second = json.loads((self.root / "reports/report.json").read_text(encoding="utf-8"))
        for key in ("file_count", "directory_count", "nonempty_lines", "extension_counts", "marker_counts"):
            self.assertEqual(first["scan"][key], second["scan"][key])

    def test_output_errors(self):
        self.init()
        result = self.run_cli(".", "--output", self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("separate directory", result.stderr)
        result = self.run_cli(".", "--output", self.root / ".git/reports")
        self.assertEqual(result.returncode, 1)

    def test_empty_git_repository(self):
        self.init()
        result = self.run_cli(".")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Commits: 0", result.stdout)

    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--output", result.stdout)
