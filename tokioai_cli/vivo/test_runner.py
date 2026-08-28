"""
TokioAI Vivo v3 - Test Runner
Runs tests (pytest, unittest, custom scripts), captures results,
provides structured feedback for the LLM auto-fix loop.

Flow: write code -> run_tests -> parse failures -> fix code -> run_tests -> repeat
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class TestResult:
    """Structured test result."""
    def __init__(self, passed: bool, total: int = 0, failures: int = 0,
                 errors: int = 0, output: str = "", failed_tests: list = None,
                 duration: float = 0.0):
        self.passed = passed
        self.total = total
        self.failures = failures
        self.errors = errors
        self.output = output
        self.failed_tests = failed_tests or []
        self.duration = duration

    def to_dict(self) -> dict:
        return {
            "passed": self.passed, "total": self.total,
            "failures": self.failures, "errors": self.errors,
            "duration": self.duration,
            "failed_tests": self.failed_tests[:10],
            "output_snippet": self.output[:3000],
        }

    def summary(self) -> str:
        if self.passed:
            return f"ALL PASSED ({self.total} tests in {self.duration:.1f}s)"
        return f"FAILED: {self.failures} failures, {self.errors} errors out of {self.total} tests"


class TestRunner:
    """Run tests and return structured results for LLM consumption."""

    def __init__(self, workdir: Optional[str] = None):
        self.workdir = workdir or os.getcwd()
        self._history: List[Dict] = []

    def _run(self, cmd: str, timeout: int = 120, cwd: Optional[str] = None) -> Tuple[int, str]:
        """Run command, return (exit_code, output)."""
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd or self.workdir
            )
            out = r.stdout + "\n" + r.stderr
            return r.returncode, out.strip()[:8000]
        except subprocess.TimeoutExpired:
            return -1, f"[timeout after {timeout}s]"
        except Exception as e:
            return -1, str(e)

    def detect_test_framework(self, path: Optional[str] = None) -> str:
        """Auto-detect which test framework to use."""
        p = Path(path or self.workdir)

        # Check for pytest
        if (p / "pytest.ini").exists() or (p / "pyproject.toml").exists() or (p / "setup.cfg").exists():
            return "pytest"
        # Check for test files
        test_files = list(p.rglob("test_*.py")) + list(p.rglob("*_test.py"))
        if test_files:
            return "pytest"
        # Check for package.json (node)
        if (p / "package.json").exists():
            return "npm"
        # Check for Cargo.toml (rust)
        if (p / "Cargo.toml").exists():
            return "cargo"
        # Check for go.mod
        if (p / "go.mod").exists():
            return "go"
        # Check for Makefile with test target
        if (p / "Makefile").exists():
            content = (p / "Makefile").read_text(errors="replace")
            if "test:" in content:
                return "make"

        return "pytest"  # default

    def run_pytest(self, target: str = "", extra_args: str = "",
                   timeout: int = 120, cwd: Optional[str] = None) -> TestResult:
        """Run pytest and parse results."""
        cmd = f"python -m pytest {target} -v --tb=short --no-header -q {extra_args}"
        start = time.time()
        code, output = self._run(cmd.strip(), timeout=timeout, cwd=cwd)
        duration = time.time() - start

        # Parse pytest output
        total, failures, errors = 0, 0, 0
        failed_tests = []

        # Look for summary line: "X passed, Y failed, Z error"
        summary_match = re.search(
            r'(\d+)\s+passed(?:.*?(\d+)\s+failed)?(?:.*?(\d+)\s+error)?',
            output
        )
        if summary_match:
            passed_count = int(summary_match.group(1))
            fail_count = int(summary_match.group(2) or 0)
            err_count = int(summary_match.group(3) or 0)
            total = passed_count + fail_count + err_count
            failures = fail_count
            errors = err_count

        # Alternative: "X failed" only
        if total == 0:
            fail_match = re.search(r'(\d+)\s+failed', output)
            if fail_match:
                failures = int(fail_match.group(1))
                total = failures

        # Parse individual failed test names
        for m in re.finditer(r'FAILED\s+(\S+)', output):
            failed_tests.append(m.group(1))

        # Parse error messages for each failure
        error_blocks = re.findall(
            r'_{3,}\s+(\S+)\s+_{3,}\n(.*?)(?=_{3,}|={3,}|\Z)',
            output, re.DOTALL
        )
        for test_name, block in error_blocks[:5]:
            failed_tests.append(f"{test_name}: {block.strip()[:200]}")

        passed = code == 0 and failures == 0 and errors == 0

        result = TestResult(
            passed=passed, total=total, failures=failures,
            errors=errors, output=output, failed_tests=failed_tests,
            duration=duration
        )

        self._history.append({
            "ts": time.time(), "framework": "pytest",
            "result": result.to_dict(), "cmd": cmd.strip()
        })

        return result

    def run_script(self, script: str, timeout: int = 60,
                   cwd: Optional[str] = None) -> TestResult:
        """Run any script and check exit code."""
        start = time.time()
        code, output = self._run(script, timeout=timeout, cwd=cwd)
        duration = time.time() - start

        passed = code == 0
        errors_found = []
        if not passed:
            # Extract key error lines
            for line in output.split("\n"):
                line_lower = line.lower()
                if any(kw in line_lower for kw in ["error", "exception", "traceback", "failed", "fatal"]):
                    errors_found.append(line.strip()[:200])

        result = TestResult(
            passed=passed, total=1, failures=0 if passed else 1,
            errors=0, output=output, failed_tests=errors_found[:5],
            duration=duration
        )

        self._history.append({
            "ts": time.time(), "framework": "script",
            "result": result.to_dict(), "cmd": script
        })

        return result

    def run_syntax_check(self, filepath: str) -> TestResult:
        """Check Python file for syntax errors without running it."""
        start = time.time()
        code, output = self._run(f"python -c \"import ast; ast.parse(open('{filepath}').read())\"")
        duration = time.time() - start

        if code == 0:
            return TestResult(passed=True, total=1, output="Syntax OK", duration=duration)

        return TestResult(
            passed=False, total=1, failures=1,
            output=output, failed_tests=[f"Syntax error in {filepath}"],
            duration=duration
        )

    def run_import_check(self, module: str, cwd: Optional[str] = None) -> TestResult:
        """Check if a module can be imported."""
        start = time.time()
        code, output = self._run(f"python -c \"import {module}; print('OK')\"", cwd=cwd)
        duration = time.time() - start

        if code == 0:
            return TestResult(passed=True, total=1, output=f"{module} imports OK", duration=duration)

        return TestResult(
            passed=False, total=1, failures=1,
            output=output, failed_tests=[f"Import failed: {module}"],
            duration=duration
        )

    def run_auto(self, target: str = "", timeout: int = 120,
                 cwd: Optional[str] = None) -> TestResult:
        """Auto-detect test framework and run tests."""
        framework = self.detect_test_framework(cwd or self.workdir)

        if framework == "pytest":
            return self.run_pytest(target=target, timeout=timeout, cwd=cwd)
        elif framework == "npm":
            return self.run_script("npm test", timeout=timeout, cwd=cwd)
        elif framework == "cargo":
            return self.run_script("cargo test", timeout=timeout, cwd=cwd)
        elif framework == "go":
            return self.run_script("go test ./...", timeout=timeout, cwd=cwd)
        elif framework == "make":
            return self.run_script("make test", timeout=timeout, cwd=cwd)
        else:
            return self.run_pytest(target=target, timeout=timeout, cwd=cwd)

    def get_history(self, n: int = 5) -> List[Dict]:
        """Get recent test history."""
        return self._history[-n:]

    def last_result(self) -> Optional[Dict]:
        """Get last test result."""
        return self._history[-1] if self._history else None

    def get_failure_context(self, result: TestResult, max_chars: int = 2000) -> str:
        """Get a concise failure context string for LLM auto-fix."""
        if result.passed:
            return "All tests passed."

        lines = [f"TEST FAILURE: {result.summary()}"]
        lines.append("")

        if result.failed_tests:
            lines.append("Failed tests:")
            for ft in result.failed_tests[:5]:
                lines.append(f"  - {ft}")
            lines.append("")

        # Extract the most relevant error from output
        output_lines = result.output.split("\n")
        error_section = []
        in_error = False
        for line in output_lines:
            if any(kw in line.lower() for kw in ["error", "assert", "failed", "traceback"]):
                in_error = True
            if in_error:
                error_section.append(line)
            if len(error_section) > 30:
                break

        if error_section:
            lines.append("Error details:")
            lines.extend(error_section[:30])

        result_str = "\n".join(lines)
        return result_str[:max_chars]
