import subprocess
from unittest.mock import patch

from support import RepositoryTest
from git_analyzer import GitError, analyze_git, repository_root, run_git


class GitTests(RepositoryTest):
    def test_non_repository(self):
        with self.assertRaisesRegex(GitError, "not a Git"):
            repository_root(self.root)

    def test_empty_repository(self):
        self.init()
        result = analyze_git(self.root)
        self.assertEqual(result["commit_count"], 0)
        self.assertEqual(result["committer_count"], 0)
        self.assertIsNone(result["latest_commit"])

    def test_real_history_latest_ten_and_committers(self):
        self.init()
        for number in range(12):
            self.commit(f"Commit {number} <tag> | detail", person="Example One" if number % 2 else "Example Two")
        result = analyze_git(self.root)
        self.assertEqual(result["commit_count"], 12)
        self.assertEqual(result["committer_count"], 2)
        self.assertEqual(len(result["recent_commits"]), 10)
        self.assertEqual(result["latest_commit"]["subject"], "Commit 11 <tag> | detail")
        self.assertEqual(result["recent_commits"][-1]["subject"], "Commit 2 <tag> | detail")

    def test_subdirectory_resolves_repository_root(self):
        self.init()
        (self.root / "src").mkdir()
        self.assertEqual(repository_root(self.root / "src"), self.root.resolve())

    def test_git_missing(self):
        with patch("git_analyzer.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(GitError, "not installed"):
                run_git(self.root, "status")

    def test_timeout(self):
        with patch("git_analyzer.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            with self.assertRaisesRegex(GitError, "timed out"):
                run_git(self.root, "status")

    def test_git_does_not_use_shell_and_ignores_git_dir(self):
        completed = subprocess.CompletedProcess([], 0, "ok", "")
        with patch.dict("os.environ", {"GIT_DIR": "wrong-repository"}):
            with patch("git_analyzer.subprocess.run", return_value=completed) as mocked:
                run_git(self.root, "rev-parse", "HEAD")
        args, kwargs = mocked.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("shell", kwargs)
        self.assertNotIn("GIT_DIR", kwargs["env"])

    def test_failed_git_command_retains_reason(self):
        completed = subprocess.CompletedProcess([], 128, "", "fatal: damaged history")
        with patch("git_analyzer.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(GitError, "damaged history"):
                run_git(self.root, "log")

    def test_detached_head(self):
        self.init()
        self.commit()
        self.git("checkout", "--detach", "HEAD")
        self.assertEqual(analyze_git(self.root)["commit_count"], 1)
