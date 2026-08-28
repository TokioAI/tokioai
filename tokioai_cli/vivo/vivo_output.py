"""
TokioAI Vivo v3.0 - Output Manager
Completely isolated output that NEVER touches sys.stdout.
All vivo output goes through this class to:
  1. A dedicated log file (always)
  2. stderr (if interactive terminal, so it never mixes with CLI stdout)
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

# ANSI
C_RESET = "\033[0m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_MAGENTA = "\033[35m"
C_WHITE = "\033[97m"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


class VivoOutput:
    """
    Isolated output channel for Vivo.
    
    Key design: NEVER replaces sys.stdout. Instead writes to:
    - A log file (plain text, ANSI stripped) -- always
    - sys.stderr (with ANSI) when running in a terminal (foreground)
    - The log file with ANSI preserved when running as daemon (--bg)
    
    This guarantees vivo output never mixes with normal CLI output,
    readline prompts, or any other stdout consumer.
    """

    def __init__(self, log_path: Path, is_daemon: bool = False):
        self._log_path = log_path
        self._is_daemon = is_daemon
        self._is_tty = sys.stderr.isatty() and not is_daemon
        
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate log for fresh sessions, append for daemon restarts
        self._logfile = open(log_path, "a", encoding="utf-8", buffering=1)

    def write(self, text: str):
        """Write text to the output channel."""
        if self._is_tty:
            # Foreground: write colored to stderr (isolated from stdout!)
            try:
                sys.stderr.write(text)
                sys.stderr.flush()
            except Exception:
                pass
            # Also write clean version to log
            try:
                clean = _ANSI_RE.sub("", text)
                self._logfile.write(clean)
                self._logfile.flush()
            except Exception:
                pass
        else:
            # Daemon mode: write with ANSI to log (for --vivo-follow colors)
            try:
                self._logfile.write(text)
                self._logfile.flush()
            except Exception:
                pass

    def line(self, text: str = ""):
        """Write a line (adds newline)."""
        self.write(text + "\n")

    def blank(self):
        """Write a blank line."""
        self.write("\n")

    def close(self):
        try:
            self._logfile.close()
        except Exception:
            pass

    @property
    def log_path(self) -> Path:
        return self._log_path
