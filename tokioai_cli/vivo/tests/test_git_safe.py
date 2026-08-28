"""
Tests for GitSafeGuard - the safety layer for autonomous Git operations.
Tests branch isolation, pre-commit checks, commit pipeline, push safety,
and auto-rollback.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tokioai_cli.vivo.git_safe import GitSafeGuard, CommitPolicy, PreCommitResult
from tokioai_cli.vivo.git_ops import GitOps
from tokioai_cli.vivo.test_runner import TestRunner


class TestCommitPolicy(unittest.TestCase):
    """Test CommitPolicy defaults and configuration."""

    def test_defaults(self):
        p = CommitPolicy()
        self.assertEqual(p.branch_prefix, "vivo/")
        self.assertIn("main", p.protected_branches)
        self.assertIn("master", p.protected_branches)
        self.assertTrue(p.require_tests_pass)
        self.assertTrue(p.require_syntax_check)
        self.assertTrue(p.auto_rollback_on_test_failure)
        self.assertEqual(p.max_files_per_commit, 10)

    def test_custom_policy(self):
        p = CommitPolicy(
            branch_prefix="ai/",
            require_tests_pass=False,
            max_files_per_commit=5,
        )
        self.assertEqual(p.branch_prefix, "ai/")
        self.assertFalse(p.require_tests_pass)
        self.assertEqual(p.max_files_per_commit, 5)

    def test_protected_paths(self):
        p = CommitPolicy()
        self.assertTrue(any(".env" in pat for pat in p.protected_paths))
        self.assertTrue(any(".key" in pat for pat in p.protected_paths))


class TestPreCommitResult(unittest.TestCase):
    """Test PreCommitResult aggregation."""

    def test_empty_passes(self):
        r = PreCommitResult()
        self.assertTrue(r.passed)
        self.assertEqual(len(r.checks), 0)

    def test_add_passing_check(self):
        r = PreCommitResult()
        r.add_check("test1", True, "ok")
        self.assertTrue(r.passed)
        self.assertEqual(len(r.checks), 1)

    def test_add_failing_check(self):
        r = PreCommitResult()
        r.add_check("test1", True, "ok")
        r.add_check("test2", False, "syntax error")
        self.assertFalse(r.passed)
        self.assertEqual(len(r.blocking_errors), 1)

    def test_warnings_dont_fail(self):
        r = PreCommitResult()
        r.add_check("test1", True, "ok")
        r.add_warning("size", "file too large")
        self.assertTrue(r.passed)
        self.assertEqual(len(r.warnings), 1)

    def test_summary(self):
        r = PreCommitResult()
        r.add_check("syntax", True, "all clear")
        r.add_check("tests", False, "2 failures")
        s = r.summary()
        self.assertIn("PASS", s)
        self.assertIn("FAIL", s)
        self.assertIn("syntax", s)
        self.assertIn("tests", s)


class TestGitSafeGuardBranch(unittest.TestCase):
    """Test branch isolation with a real temporary git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="tokio_gitsafe_test_")
        # Init git repo
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"],
                       cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=self.tmpdir, capture_output=True)
        # Create initial file and commit
        (Path(self.tmpdir) / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.tmpdir, capture_output=True)

        self.git = GitOps(workdir=self.tmpdir, enabled=True)
        self.test_runner = TestRunner(workdir=self.tmpdir)
        self.messages = []
        self.guard = GitSafeGuard(
            git_ops=self.git,
            test_runner=self.test_runner,
            policy=CommitPolicy(require_tests_pass=False),  # No tests in test repo
            output_fn=lambda x: self.messages.append(x),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_on_main_creates_vivo_branch(self):
        ok, msg = self.guard.ensure_safe_branch()
        self.assertTrue(ok)
        branch = self.guard.get_current_branch()
        self.assertTrue(branch.startswith("vivo/"), f"Expected vivo/* branch, got: {branch}")

    def test_protected_branch_detection(self):
        # We started on main, ensure_safe_branch moved us
        self.guard.ensure_safe_branch()
        self.assertFalse(self.guard.is_on_protected_branch())

    def test_already_on_vivo_branch(self):
        # First call creates vivo branch
        self.guard.ensure_safe_branch()
        # Second call should be fine
        ok, msg = self.guard.ensure_safe_branch()
        self.assertTrue(ok)
        self.assertIn("on safe branch", msg)

    def test_safe_commit_creates_branch_and_commits(self):
        # Write a file
        test_file = Path(self.tmpdir) / "test.py"
        test_file.write_text("print('hello')\n")

        ok, msg = self.guard.safe_commit([str(test_file)], "test: add test.py", skip_tests=True)
        self.assertTrue(ok, f"Safe commit failed: {msg}")
        self.assertIn("committed" if "committed" in msg.lower() else "Safe commit", msg)

        # Verify we're on a vivo branch
        branch = self.guard.get_current_branch()
        self.assertTrue(branch.startswith("vivo/"))

    def test_safe_commit_blocks_syntax_error(self):
        policy = CommitPolicy(require_tests_pass=False, require_syntax_check=True)
        guard = GitSafeGuard(
            git_ops=self.git,
            test_runner=self.test_runner,
            policy=policy,
            output_fn=lambda x: None,
        )
        guard.ensure_safe_branch()

        # Write a file with syntax error
        bad_file = Path(self.tmpdir) / "bad.py"
        bad_file.write_text("def foo(\n  # missing close paren\n")
        subprocess.run(["git", "add", str(bad_file)], cwd=self.tmpdir, capture_output=True)

        ok, msg = guard.safe_commit([str(bad_file)], "test: bad syntax")
        self.assertFalse(ok, "Should block commit with syntax error")
        self.assertIn("syntax", msg.lower())


class TestGitSafeGuardProtectedPaths(unittest.TestCase):
    """Test protected path enforcement."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="tokio_gitsafe_paths_")
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"],
                       cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=self.tmpdir, capture_output=True)
        (Path(self.tmpdir) / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.tmpdir, capture_output=True)

        self.git = GitOps(workdir=self.tmpdir, enabled=True)
        self.test_runner = TestRunner(workdir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_immutable_git_dir_blocked(self):
        policy = CommitPolicy()
        guard = GitSafeGuard(self.git, self.test_runner, policy)
        result = guard._check_protected_paths([".git/config"])
        self.assertFalse(result.passed)

    def test_normal_file_allowed(self):
        policy = CommitPolicy()
        guard = GitSafeGuard(self.git, self.test_runner, policy)
        result = guard._check_protected_paths(["src/main.py", "tests/test_main.py"])
        self.assertTrue(result.passed)

    def test_env_file_blocked_without_review(self):
        policy = CommitPolicy(require_diff_review=False)
        guard = GitSafeGuard(self.git, self.test_runner, policy)
        result = guard._check_protected_paths([".env"])
        self.assertFalse(result.passed)


class TestGitSafeGuardPush(unittest.TestCase):
    """Test push safety."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="tokio_gitsafe_push_")
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"],
                       cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=self.tmpdir, capture_output=True)
        (Path(self.tmpdir) / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.tmpdir, capture_output=True)

        self.git = GitOps(workdir=self.tmpdir, enabled=True)
        self.test_runner = TestRunner(workdir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_push_blocked_on_main(self):
        policy = CommitPolicy()
        guard = GitSafeGuard(self.git, self.test_runner, policy)
        ok, msg = guard.safe_push()
        self.assertFalse(ok)
        self.assertIn("BLOCKED", msg)

    def test_push_blocked_without_remote(self):
        policy = CommitPolicy(require_remote_configured=True)
        guard = GitSafeGuard(self.git, self.test_runner, policy)
        guard.ensure_safe_branch()
        ok, msg = guard.safe_push()
        self.assertFalse(ok)
        self.assertIn("BLOCKED", msg)


class TestGitSafeGuardSessionStats(unittest.TestCase):
    """Test session stats tracking."""

    def test_initial_stats(self):
        tmpdir = tempfile.mkdtemp(prefix="tokio_gitsafe_stats_")
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"],
                       cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=tmpdir, capture_output=True)
        (Path(tmpdir) / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True)

        git = GitOps(workdir=tmpdir, enabled=True)
        tr = TestRunner(workdir=tmpdir)
        guard = GitSafeGuard(git, tr)

        stats = guard.get_session_stats()
        self.assertEqual(stats["total_commits"], 0)
        self.assertEqual(stats["rollbacks"], 0)

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestGitSafeCommitSize(unittest.TestCase):
    """Test commit size limits."""

    def test_too_many_files_blocked(self):
        tmpdir = tempfile.mkdtemp(prefix="tokio_gitsafe_size_")
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"],
                       cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=tmpdir, capture_output=True)
        (Path(tmpdir) / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True)

        git = GitOps(workdir=tmpdir, enabled=True)
        tr = TestRunner(workdir=tmpdir)
        policy = CommitPolicy(max_files_per_commit=2)
        guard = GitSafeGuard(git, tr, policy)

        # Check with 5 files
        files = [f"file{i}.py" for i in range(5)]
        result = guard._check_commit_size(files)
        self.assertFalse(result.passed)

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
