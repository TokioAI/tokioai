#!/usr/bin/env python3
"""
TokioAI v5.2
"""
from __future__ import annotations

import atexit
import json as _json
import os
import platform
import re
import signal
import subprocess as _sp
import sys
import time
from typing import Optional, Set, Callable

_IS_WINDOWS = platform.system() == "Windows"

# ── Silence noisy SDK loggers (httpx/httpcore spam on Windows) ──
import logging
for _noisy in ("httpx", "httpcore", "anthropic", "openai", "google"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Cross-platform readline ─────────────────────────
if _IS_WINDOWS:
    try:
        import pyreadline3 as readline  # type: ignore
    except ImportError:
        try:
            import readline  # type: ignore
        except ImportError:
            readline = None  # type: ignore
else:
    import readline

# ── Cross-platform terminal modules ─────────────────
if _IS_WINDOWS:
    import msvcrt
    select = None; termios = None; tty = None  # type: ignore
else:
    import select, termios, tty


# ═══════════════════════════════════════════════════════
# CLEANUP REGISTRY — Guarantees cleanup on ANY exit
# ═══════════════════════════════════════════════════════

_cleanup_functions: Set[Callable] = set()
_terminal_saved_state = None
_shutting_down = False


def register_cleanup(fn: Callable) -> Callable:
    _cleanup_functions.add(fn)
    return lambda: _cleanup_functions.discard(fn)


def _run_all_cleanups():
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    for fn in list(_cleanup_functions):
        try:
            fn()
        except Exception:
            pass


def _restore_terminal_sync():
    """Synchronous terminal restore — the most critical cleanup."""
    if _IS_WINDOWS:
        return
    try:
        fd = sys.stdin.fileno()
        if _terminal_saved_state and os.isatty(fd):
            termios.tcsetattr(fd, termios.TCSANOW, _terminal_saved_state)
    except Exception:
        pass
    try:
        os.system("stty sane 2>/dev/null")
    except Exception:
        pass
    try:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    except Exception:
        pass


def _signal_handler(signum, frame):
    _restore_terminal_sync()
    _run_all_cleanups()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _sigint_handler(signum, frame):
    """SIGINT (Ctrl+C): raise KeyboardInterrupt instead of killing the process.
    This lets the interactive loop catch it and cancel the current operation
    without closing the session."""
    raise KeyboardInterrupt


if not _IS_WINDOWS:
    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    try:
        signal.signal(signal.SIGHUP, _signal_handler)
    except (AttributeError, OSError):
        pass

atexit.register(_restore_terminal_sync)
atexit.register(_run_all_cleanups)


# ═══════════════════════════════════════════════════════
# SAFE I/O
# ═══════════════════════════════════════════════════════

# Force UTF-8 on stdout/stderr for Windows (fixes emoji/unicode display)
if _IS_WINDOWS:
    try:
        import subprocess as _sp
        _sp.run(["chcp", "65001"], shell=True, capture_output=True)
    except Exception:
        pass
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

def _safe_write(data: str):
    try:
        if sys.stdout.closed:
            return
        sys.stdout.write(data)
        sys.stdout.flush()
    except (BrokenPipeError, IOError, OSError):
        try:
            sys.stdout.close()
        except Exception:
            pass
    except UnicodeEncodeError:
        try:
            # Try UTF-8 encoding explicitly
            sys.stdout.buffer.write(data.encode('utf-8', errors='replace'))
            sys.stdout.buffer.flush()
        except Exception:
            pass


def _safe_print(data: str = "", end: str = "\n"):
    _safe_write(data + end)


# ═══════════════════════════════════════════════════════
# STDIN MANAGEMENT
# ═══════════════════════════════════════════════════════

def _flush_stdin():
    if not sys.stdin.isatty():
        return
    try:
        if _IS_WINDOWS:
            while msvcrt.kbhit():
                msvcrt.getch()
        else:
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        pass


def _drain_stdin():
    """Drain any leftover bytes from stdin (non-blocking).
    Uses a max iteration guard to prevent infinite loops on weird terminal states."""
    if _IS_WINDOWS or not sys.stdin.isatty():
        return
    try:
        fd = sys.stdin.fileno()
        for _ in range(100):  # Safety limit
            rlist, _, _ = select.select([fd], [], [], 0)
            if not rlist:
                break
            os.read(fd, 4096)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
# .env loader
# ═══════════════════════════════════════════════════════

def _load_dotenv():
    # Priority: local .env first (isolated env), then global ~/.tokioai/.env
    env_paths = [
        os.path.join(os.getcwd(), ".env"),             # Local project env (highest priority)
        os.path.expanduser("~/.tokioai/.env"),         # Global config (fallback)
    ]
    loaded_from = None
    for env_path in env_paths:
        real_path = os.path.realpath(env_path) if os.path.islink(env_path) else env_path
        if os.path.isfile(real_path):
            with open(real_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        os.environ.setdefault(k, v)  # setdefault: first file wins
            if loaded_from is None:
                loaded_from = env_path
    os.environ["_TOKIOAI_ENV_SOURCE"] = loaded_from or "none"

_load_dotenv()

from tokioai_cli.ops import (
    TokioOps, MODEL, PROVIDER, VERTEX_PROJECT, VERTEX_REGION,
    MODEL_ALIASES, resolve_model, list_aliases, detect_provider,
    SSH_RASPI, SSH_GCP, RASPI_IP, RASPI_TS, GCP_IP, GCP_USER, ROUTER_IP, RASPI_USER,
)

# ═══════════════════════════════════════════════════════
# Enable ANSI on Windows
# ═══════════════════════════════════════════════════════

if _IS_WINDOWS:
    os.system("")  # enables ANSI escape codes on Windows 10+


# ═══════════════════════════════════════════════════════
# ANSI Colors
# ═══════════════════════════════════════════════════════

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_ITALIC = "\033[3m"
C_UNDERLINE = "\033[4m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_GRAY = "\033[90m"
C_BRIGHT_RED = "\033[91m"
C_BRIGHT_GREEN = "\033[92m"
C_BRIGHT_YELLOW = "\033[93m"
C_BRIGHT_BLUE = "\033[94m"
C_BRIGHT_CYAN = "\033[96m"
C_BRIGHT_WHITE = "\033[97m"
C_CLEAR_LINE = "\033[2K\033[G"
C_BG_GRAY = "\033[48;5;236m"

def c256(n: int) -> str:
    return f"\033[38;5;{n}m"

# Safe line characters — Windows CMD with old codepage can't render box-drawing
_LINE_H = "-" if _IS_WINDOWS else "━"
_LINE_THIN = "-" if _IS_WINDOWS else "─"
_PROMPT_CHAR = ">" if _IS_WINDOWS else "❯"
_BULLET = ["*", "o", "-", "."] if _IS_WINDOWS else ["●", "○", "▸", "▹"]
_BLOCKQUOTE = "|" if _IS_WINDOWS else "▌"
_BOX_TL = "+" if _IS_WINDOWS else "┌"
_BOX_BL = "+" if _IS_WINDOWS else "└"
_BOX_V = "|" if _IS_WINDOWS else "│"
_BOX_H = _LINE_THIN

RL_START = "\001" if not _IS_WINDOWS else ""
RL_END = "\002" if not _IS_WINDOWS else ""


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


# ═══════════════════════════════════════════════════════
# History, Session & Cost Persistence
# ═══════════════════════════════════════════════════════

HISTORY_FILE = os.path.expanduser("~/.tokioai_history")
SESSION_FILE = os.path.expanduser("~/.tokioai_session.json")
COST_FILE = os.path.expanduser("~/.tokioai_costs.json")

# ── Tab Completion ──

_CLI_COMMANDS = [
    "exit", "quit", "help", "reset", "compact", "stats", "model", "models", "clear",
    "unlimited", "persistent", "stop", "config", "dual", "router", "threshold", "force",
    "/status", "/waf", "/health", "/drone", "/threats", "/entity",
    "/sitrep", "/see", "/containers", "/wifi", "/coffee", "/logs", "/ha", "/picar",
    "/gcp", "/diff", "/commit", "/branch",
    "memory", "tasks",
]

# Model aliases for "model <tab>" completion
_MODEL_ALIASES_SHORT = [
    "opus", "sonnet", "haiku", "flash", "flash2", "flash3",
    "gpt4o", "gpt5", "o3", "o4-mini",
    "gemini3", "gemini31",
    "kimi", "kimi-k2", "k2", "moonshot",
    "or-kimi3", "or-k3", "or-kimi", "or-k27", "or-claude", "or-opus",
    "dual", "kimi-dual", "k2k3", "kimi-k2.7", "k27",
    "or-gemini3", "or-gemini31", "or-gpt", "or-deepseek", "or-llama",
]

def _completer(text: str, state: int):
    try:
        # Get the full line buffer
        line = readline.get_line_buffer().strip() if readline else text
    except Exception:
        line = text

    # "model <tab>" → complete model aliases
    if line.lower().startswith("model "):
        model_part = line[6:].lower()
        matches = [f"model {m}" for m in _MODEL_ALIASES_SHORT if m.startswith(model_part)]
        return matches[state] if state < len(matches) else None

    # Normal command completion
    matches = [c for c in _CLI_COMMANDS if c.lower().startswith(text.lower())]
    # Also try fuzzy: if no prefix match, try contains
    if not matches and len(text) >= 2:
        matches = [c for c in _CLI_COMMANDS if text.lower() in c.lower()]
    return matches[state] if state < len(matches) else None


def _load_history():
    if not readline:
        return
    try:
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
        readline.set_completer(_completer)
        readline.set_completer_delims(' \t\n')
        if _IS_WINDOWS:
            # pyreadline3 needs this specific syntax
            readline.parse_and_bind('tab: complete')
            readline.parse_and_bind('"\t": complete')
        else:
            readline.parse_and_bind('tab: complete')
            readline.parse_and_bind('set horizontal-scroll-mode off')
            readline.parse_and_bind('set enable-bracketed-paste on')
            readline.parse_and_bind('set bell-style none')
            readline.parse_and_bind('set show-all-if-ambiguous on')
    except Exception:
        pass


def _save_history():
    if not readline:
        return
    try:
        readline.set_history_length(1000)
        readline.write_history_file(HISTORY_FILE)
    except Exception:
        pass


def _save_session(messages: list):
    try:
        recent = messages[-50:] if messages else []
        state = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": recent,
        }
        with open(SESSION_FILE, "w") as f:
            _json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _load_session():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as f:
                state = _json.load(f)
            ts = state.get("timestamp", "")
            if ts:
                from datetime import datetime, timedelta
                saved = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - saved > timedelta(days=7):
                    return None
            return state
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════
# COST TRACKER — Persistent across restarts
# ═══════════════════════════════════════════════════════

class CostTracker:
    MODEL_COSTS = {
        "claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "claude-opus-4": {"input": 15.0, "output": 75.0},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-5": {"input": 5.0, "output": 20.0},
        "o3": {"input": 10.0, "output": 40.0},
        "gemini-2.5": {"input": 0.15, "output": 0.60},
        "gemini-3": {"input": 0.15, "output": 0.60},
        "gemini-3.1": {"input": 0.15, "output": 0.60},
        # OpenRouter models
        "kimi-k3": {"input": 3.0, "output": 15.0},
        "kimi-k2": {"input": 0.57, "output": 2.30},
        "moonshotai/kimi-k3": {"input": 3.0, "output": 15.0},
        "moonshotai/kimi-k2": {"input": 0.57, "output": 2.30},
        "kimi-k2.7-code": {"input": 0.71, "output": 3.50},
        "moonshotai/kimi-k2.7-code": {"input": 0.71, "output": 3.50},
        "anthropic/claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "anthropic/claude-opus-4": {"input": 15.0, "output": 75.0},
        "google/gemini-3.1-pro": {"input": 2.0, "output": 12.0},
        "google/gemini-3.6-flash": {"input": 1.5, "output": 7.5},
    }

    def __init__(self):
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cost_usd = 0.0
        self.model_usage: dict = {}
        self._restore()

    def add_usage(self, model: str, input_tokens: int, output_tokens: int):
        self.session_input_tokens += input_tokens
        self.session_output_tokens += output_tokens

        costs = None
        for key, val in self.MODEL_COSTS.items():
            if key in model.lower():
                costs = val
                break
        if not costs:
            costs = self.MODEL_COSTS.get("claude-sonnet-4", {"input": 3.0, "output": 15.0})

        cost = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
        self.session_cost_usd += cost

        if model not in self.model_usage:
            self.model_usage[model] = {"input": 0, "output": 0, "cost": 0.0}
        self.model_usage[model]["input"] += input_tokens
        self.model_usage[model]["output"] += output_tokens
        self.model_usage[model]["cost"] += cost
        self._persist()

    def format_cost(self) -> str:
        if self.session_cost_usd < 0.01:
            return f"${self.session_cost_usd:.4f}"
        return f"${self.session_cost_usd:.2f}"

    def estimate_single(self, model: str, input_tokens: int, output_tokens: int) -> str:
        costs = None
        for key, val in self.MODEL_COSTS.items():
            if key in model.lower():
                costs = val
                break
        if not costs:
            costs = {"input": 3.0, "output": 15.0}
        c = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
        return f"${c:.4f}" if c < 0.01 else f"${c:.2f}"

    def _persist(self):
        try:
            data = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "input_tokens": self.session_input_tokens,
                "output_tokens": self.session_output_tokens,
                "cost_usd": self.session_cost_usd,
                "model_usage": self.model_usage,
            }
            with open(COST_FILE, "w") as f:
                _json.dump(data, f, indent=2)
        except Exception:
            pass

    def _restore(self):
        try:
            if os.path.exists(COST_FILE):
                with open(COST_FILE, "r") as f:
                    data = _json.load(f)
                ts = data.get("timestamp", "")
                if ts:
                    from datetime import datetime, timedelta
                    saved = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - saved < timedelta(hours=12):
                        self.session_input_tokens = data.get("input_tokens", 0)
                        self.session_output_tokens = data.get("output_tokens", 0)
                        self.session_cost_usd = data.get("cost_usd", 0.0)
                        self.model_usage = data.get("model_usage", {})
        except Exception:
            pass


_cost_tracker = CostTracker()


# ═══════════════════════════════════════════════════════
# Markdown Renderer
# ═══════════════════════════════════════════════════════

class MarkdownRenderer:
    _BOLD = re.compile(r'\*\*(.+?)\*\*')
    _ITALIC = re.compile(r'(?<!\*)\*([^*]+?)\*(?!\*)')
    _INLINE_CODE = re.compile(r'`([^`\n]+?)`')
    _LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    _STRIKETHROUGH = re.compile(r'~~(.+?)~~')

    @classmethod
    def render(cls, text: str) -> str:
        lines = text.split('\n')
        result = []
        in_code_block = False

        for line in lines:
            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    lang = line.strip()[3:].strip()
                    label = f" {lang}" if lang else ""
                    result.append(f"  {C_DIM}{_BOX_TL}{_LINE_THIN}{label}{_LINE_THIN * max(1, 40 - len(label))}{C_RESET}")
                else:
                    in_code_block = False
                    result.append(f"  {C_DIM}{_BOX_BL}{_LINE_THIN * 42}{C_RESET}")
                continue
            if in_code_block:
                result.append(f"  {C_DIM}{_BOX_V}{C_RESET} {C_BRIGHT_GREEN}{line}{C_RESET}")
                continue
            if line.startswith('### '):
                result.append(f"  {C_BOLD}{C_CYAN}   {line[4:]}{C_RESET}")
                continue
            if line.startswith('## '):
                result.append(f"  {C_BOLD}{C_BRIGHT_CYAN}  {line[3:]}{C_RESET}")
                continue
            if line.startswith('# '):
                result.append(f"  {C_BOLD}{C_BRIGHT_WHITE}{_LINE_H}{_LINE_H} {line[2:]} {_LINE_H}{_LINE_H}{C_RESET}")
                continue
            if re.match(r'^-{3,}$', line.strip()) or re.match(r'^\*{3,}$', line.strip()):
                w = min(_term_width() - 4, 60)
                result.append(f"  {C_DIM}{_LINE_THIN * w}{C_RESET}")
                continue
            m = re.match(r'^(\s*)([-*+])\s+(.+)', line)
            if m:
                indent, _, content = m.groups()
                depth = len(indent) // 2
                bullet = _BULLET[depth % len(_BULLET)]
                color = [C_BRIGHT_CYAN, C_CYAN, C_BLUE, C_DIM][depth % 4]
                rendered = cls._render_inline(content)
                result.append(f"  {' ' * (depth * 2)}{color}{bullet}{C_RESET} {rendered}")
                continue
            m = re.match(r'^(\s*)(\d+)\.\s+(.+)', line)
            if m:
                indent, num, content = m.groups()
                rendered = cls._render_inline(content)
                result.append(f"  {indent}{C_BRIGHT_CYAN}{num}.{C_RESET} {rendered}")
                continue
            if '|' in line and line.strip().startswith('|'):
                cells = [c.strip() for c in line.strip('|').split('|')]
                if all(re.match(r'^[-:]+$', c) for c in cells if c):
                    result.append(f"  {C_DIM}{_LINE_THIN * 50}{C_RESET}")
                    continue
                row_parts = []
                for cell in cells:
                    rendered = cls._render_inline(cell)
                    row_parts.append(f" {rendered:<18}")
                result.append(f"  {C_DIM}{_BOX_V}{C_RESET}{_BOX_V.join(row_parts)}{C_DIM}{_BOX_V}{C_RESET}")
                continue
            if line.startswith('> '):
                rendered = cls._render_inline(line[2:])
                result.append(f"  {C_DIM}{_BLOCKQUOTE}{C_RESET} {C_ITALIC}{rendered}{C_RESET}")
                continue
            rendered = cls._render_inline(line)
            result.append(rendered)

        return '\n'.join(result)

    @classmethod
    def _render_inline(cls, text: str) -> str:
        text = cls._LINK.sub(f'{C_UNDERLINE}{C_BRIGHT_BLUE}\\1{C_RESET}{C_DIM} (\\2){C_RESET}', text)
        text = cls._BOLD.sub(f'{C_BOLD}\\1{C_RESET}', text)
        text = cls._ITALIC.sub(f'{C_ITALIC}\\1{C_RESET}', text)
        text = cls._INLINE_CODE.sub(f'{C_BG_GRAY}{C_BRIGHT_GREEN} \\1 {C_RESET}', text)
        text = cls._STRIKETHROUGH.sub(f'{C_DIM}\\1{C_RESET}', text)
        return text


# ═══════════════════════════════════════════════════════
# Sensitive Data Masking
# ═══════════════════════════════════════════════════════

_SENSITIVE_PATTERNS = [
    # API keys & tokens
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'ghp_[A-Za-z0-9]{36,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'gho_[A-Za-z0-9]{36,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'), '[ANTHROPIC_KEY]'),
    (re.compile(r'sk-or-[A-Za-z0-9_-]{20,}'), '[OPENROUTER_KEY]'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[API_KEY]'),
    (re.compile(r'AIza[A-Za-z0-9_-]{35}'), '[GOOGLE_API_KEY]'),
    (re.compile(r'AKIA[A-Z0-9]{16}'), '[AWS_KEY]'),
    (re.compile(r'xoxb-[A-Za-z0-9\-]{20,}'), '[SLACK_TOKEN]'),
    (re.compile(r'xoxp-[A-Za-z0-9\-]{20,}'), '[SLACK_TOKEN]'),
    # Bearer tokens
    (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.]{20,}'), r'\1[TOKEN]'),
    # JWT tokens (header.payload.signature)
    (re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-]{10,}'), '[JWT_TOKEN]'),
    # Generic long hex/base64 secrets (env var assignments like KEY=abc123...)
    (re.compile(r'((?:PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|AUTH)\s*[=:]\s*)[^\s]{12,}', re.IGNORECASE), r'\1[REDACTED]'),
    # SSH private key content
    (re.compile(r'-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----'), '[PRIVATE_KEY]'),
]

def _mask_sensitive(text: str) -> str:
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# Prefixes that COULD be the start of a sensitive pattern.
# If the buffer ends with one of these, hold it back until more tokens arrive.
_SENSITIVE_PREFIXES = [
    re.compile(r'github_pat_[A-Za-z0-9_]{0,}$'),
    re.compile(r'ghp_[A-Za-z0-9]{0,}$'),
    re.compile(r'gho_[A-Za-z0-9]{0,}$'),
    re.compile(r'sk-ant-[A-Za-z0-9_\-]{0,}$'),
    re.compile(r'sk-or-[A-Za-z0-9_\-]{0,}$'),
    re.compile(r'sk-[A-Za-z0-9_\-]{0,}$'),
    re.compile(r'AIza[A-Za-z0-9_\-]{0,}$'),
    re.compile(r'AKIA[A-Z0-9]{0,}$'),
    re.compile(r'xox[bp]-[A-Za-z0-9\-]{0,}$'),
    re.compile(r'eyJ[A-Za-z0-9_\-]{0,}$'),
    re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{0,}$'),
    re.compile(r'-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*$'),
    # Partial prefix starters (just the first few chars)
    re.compile(r'github_pa$'),
    re.compile(r'github_p$'),
    re.compile(r'github_$'),
    re.compile(r'sk-an$'),
    re.compile(r'sk-a$'),
    re.compile(r'AIz$'),
    re.compile(r'AKI$'),
    re.compile(r'xox$'),
    re.compile(r'eyJ$'),
    re.compile(r'Beare$'),
    re.compile(r'Bear$'),
    # Generic: env var assignment building up (full words and partial suffixes)
    re.compile(r'(?:PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|AUTH)\s*[=:]\s*[^\s]{0,}$', re.IGNORECASE),
    # Partial env var name endings that could become PASSWORD, SECRET, etc.
    re.compile(r'(?:PASSWOR|PASSWO|PASSW|PASS|SECRE|SECR|API_KE|PRIVATE_KE|PRIVATE_K|PRIVATE_)$'),
]

class SecureStreamBuffer:
    """Buffers streaming tokens and masks sensitive data BEFORE printing.

    The problem: during streaming, API keys arrive split across multiple
    tokens (e.g. "AIzaSy" + "CzCFB04" + "QQaaup..."). Per-token masking
    fails because no single token contains the full pattern.

    Solution: accumulate tokens in a buffer. Only flush text to screen
    when we're confident the buffer tail doesn't contain a partial
    sensitive prefix. If it might, hold it back until more tokens arrive
    or flush() is called at end-of-stream.
    """

    def __init__(self, write_fn):
        self._write = write_fn
        self._buf = ""
        self._first = True

    def add(self, token: str):
        """Add a streaming token. Prints safe portion immediately."""
        if self._first:
            self._write("\n")
            self._first = False
        self._buf += token
        self._flush_safe()

    def _flush_safe(self):
        """Flush as much of the buffer as is safe to print."""
        if not self._buf:
            return

        # Check if the tail of the buffer could be a partial sensitive prefix
        hold_from = len(self._buf)  # by default, nothing held back

        # We check the last N chars (max prefix length ~60 is generous)
        tail_check_len = min(len(self._buf), 80)
        tail = self._buf[-tail_check_len:]

        for prefix_re in _SENSITIVE_PREFIXES:
            m = prefix_re.search(tail)
            if m:
                # Found a potential partial match -- hold from its start
                abs_start = len(self._buf) - tail_check_len + m.start()
                hold_from = min(hold_from, abs_start)

        if hold_from > 0:
            safe = self._buf[:hold_from]
            self._buf = self._buf[hold_from:]
            masked = _mask_sensitive(safe)
            self._write(masked)

    def flush(self):
        """Flush everything remaining (end of stream). Mask before printing."""
        if self._buf:
            masked = _mask_sensitive(self._buf)
            self._write(masked)
            self._buf = ""


# ═══════════════════════════════════════════════════════
# Tool Display
# ═══════════════════════════════════════════════════════

if _IS_WINDOWS:
    # ASCII-safe icons — many Windows terminals mangle multi-byte emoji
    TOOL_ICONS = {
        "execute_local": ">", "execute_raspi": ">", "execute_gcp": ">",
        "execute_router": ">", "read_file": "R", "write_file": "W",
        "edit_file": "E", "search_files": "?", "diagnose": "+",
        "ssh_connect": "@",
    }
    _ICON_OK = "+"
    _ICON_FAIL = "x"
    _ICON_TIME = "T"
    _ICON_TOOLS = "#"
    _ICON_STATS = "*"
    _ICON_COST = "$"
else:
    TOOL_ICONS = {
        "execute_local": "⚡", "execute_raspi": "🍓", "execute_gcp": "☁️",
        "execute_router": "📡", "read_file": "📖", "write_file": "✏️",
        "edit_file": "🔧", "search_files": "🔍", "diagnose": "🩺",
        "ssh_connect": "🔑",
    }
    _ICON_OK = "✓"
    _ICON_FAIL = "✗"
    _ICON_TIME = "⏱"
    _ICON_TOOLS = "🔧"
    _ICON_STATS = "📊"
    _ICON_COST = "💰"

_ICON_DEFAULT = "#" if _IS_WINDOWS else "🔧"

def _format_tool_start(name: str, args: dict) -> str:
    icon = TOOL_ICONS.get(name, _ICON_DEFAULT)
    detail = ""
    if "command" in args:
        cmd = _mask_sensitive(str(args["command"])[:100])
        detail = f" {C_GRAY}{cmd}{C_RESET}"
    elif "path" in args:
        detail = f" {C_GRAY}{args['path']}{C_RESET}"
    elif "pattern" in args:
        detail = f" {C_GRAY}'{args['pattern']}'{C_RESET}"
    elif "host" in args:
        user = args.get("username", "")
        cmd = _mask_sensitive(str(args.get("command", ""))[:60])
        detail = f" {C_GRAY}{user}@{args['host']}"
        if cmd:
            detail += f" $ {cmd}"
        detail += f"{C_RESET}"
    return f"  {icon} {C_BOLD}{C_BRIGHT_CYAN}{name}{C_RESET}{detail}"


def _format_tool_result(name: str, output: str) -> str:
    if not output or not output.strip():
        return f"    {C_BRIGHT_GREEN}{_ICON_OK}{C_RESET} {C_GRAY}done{C_RESET}"
    preview = _mask_sensitive(output.strip().replace("\n", " ")[:150])
    truncated = '...' if len(output.strip()) > 150 else ''
    is_error = any(e in output.strip().lower()[:100] for e in ['error', 'traceback', 'exception', 'failed'])
    if is_error:
        return f"    {C_BRIGHT_RED}{_ICON_FAIL}{C_RESET} {C_GRAY}{preview}{truncated}{C_RESET}"
    return f"    {C_BRIGHT_GREEN}{_ICON_OK}{C_RESET} {C_GRAY}{preview}{truncated}{C_RESET}"


# ═══════════════════════════════════════════════════════
# Slash Commands — Instant, no LLM
# ═══════════════════════════════════════════════════════

def _quick_ssh(host, key, user, cmd, timeout=8):
    if not host:
        return ""
    try:
        r = _sp.run(
            ["ssh", "-T", "-i", key, "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "LogLevel=ERROR", "-o", "BatchMode=yes",
             f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=timeout + 5
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _quick_curl(url: str, timeout: int = 5) -> dict:
    try:
        r = _sp.run(["curl", "-s", "--connect-timeout", str(timeout), url],
                     capture_output=True, text=True, timeout=timeout + 3)
        if r.returncode == 0 and r.stdout.strip():
            return _json.loads(r.stdout)
    except Exception:
        pass
    return {}


def _slash_status():
    _safe_print(f"\n  {C_BOLD}🏠 System Status{C_RESET}\n")
    # Entity
    if RASPI_TS or RASPI_IP:
        rip = RASPI_TS or RASPI_IP
        data = _quick_curl(f"http://{rip}:5000/status")
        if data:
            fps = data.get("fps", 0)
            cam = "✅" if data.get("camera_open") else "❌"
            hailo = "✅" if data.get("hailo_available") else "❌"
            persons = data.get("persons_detected", 0)
            _safe_print(f"  {C_BRIGHT_GREEN}✅ Entity{C_RESET}     FPS:{fps:.0f} Cam:{cam} Hailo:{hailo} Persons:{persons}")
        else:
            _safe_print(f"  {C_BRIGHT_RED}❌ Entity{C_RESET}     offline")
    else:
        _safe_print(f"  {C_DIM}⬚ Entity{C_RESET}     not configured")
    # GCP
    if GCP_IP:
        out = _quick_ssh(GCP_IP, SSH_GCP, GCP_USER,
            "sudo docker ps --format '{{.Names}}' 2>/dev/null | wc -l")
        if out and out.strip().isdigit():
            _safe_print(f"  {C_BRIGHT_GREEN}✅ GCP{C_RESET}        {out.strip()} containers running")
        else:
            _safe_print(f"  {C_BRIGHT_RED}❌ GCP{C_RESET}        unreachable")
    else:
        _safe_print(f"  {C_DIM}⬚ GCP{C_RESET}        not configured")
    _safe_print()


def _slash_waf():
    _safe_print(f"\n  {C_BOLD}🔥 WAF Defense{C_RESET}\n")
    if not GCP_IP:
        _safe_print(f"  {C_DIM}GCP not configured{C_RESET}\n")
        return
    out = _quick_ssh(GCP_IP, SSH_GCP, GCP_USER,
        'curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" '
        "-d '{\"username\":\"admin\",\"password\":\"admin\"}' 2>/dev/null")
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF API unreachable{C_RESET}\n")
        return
    try:
        token = _json.loads(out).get("token", "")
    except Exception:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF auth failed{C_RESET}\n")
        return
    out = _quick_ssh(GCP_IP, SSH_GCP, GCP_USER,
        f'curl -s http://127.0.0.1:8000/api/summary -H "Authorization: Bearer {token}" 2>/dev/null')
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF summary failed{C_RESET}\n")
        return
    try:
        d = _json.loads(out)
        total = d.get('total', 0)
        blocked = d.get('blocked', 0)
        rate = (blocked / total * 100) if total > 0 else 0
        _safe_print(f"  Total attacks:   {C_BOLD}{total:,}{C_RESET}")
        _safe_print(f"  Blocked:         {C_BOLD}{blocked:,}{C_RESET} ({rate:.1f}%)")
        _safe_print(f"  Active IP bans:  {C_BOLD}{d.get('active_blocks', 0)}{C_RESET}")
        _safe_print(f"  Unique IPs:      {d.get('unique_ips', 0):,}")
        _safe_print(f"  {C_BRIGHT_RED}Critical{C_RESET}:        {d.get('critical', 0):,}")
        _safe_print(f"  {C_BRIGHT_YELLOW}High{C_RESET}:            {d.get('high', 0):,}")
    except Exception:
        _safe_print(f"  {C_BRIGHT_RED}❌ Parse error{C_RESET}")
    _safe_print()


def _slash_health():
    _safe_print(f"\n  {C_BOLD}❤️ Health Vitals{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/health/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Health monitor offline{C_RESET}\n")
        return
    hr = data.get("heart_rate", "?")
    spo2 = data.get("spo2", "?")
    bp_sys = data.get("bp_sys", data.get("blood_pressure", {}).get("systolic", 0))
    bp_dia = data.get("bp_dia", data.get("blood_pressure", {}).get("diastolic", 0))
    connected = data.get("connected", False)
    battery = data.get("battery", "?")

    status = f"{C_BRIGHT_GREEN}✅ connected{C_RESET}" if connected else f"{C_BRIGHT_YELLOW}⏳ waiting{C_RESET}"
    _safe_print(f"  Watch:       {status} 🔋{battery}%")
    hr_color = C_BRIGHT_RED if isinstance(hr, (int, float)) and (hr > 120 or hr < 45) else C_BOLD
    _safe_print(f"  Heart Rate:  {hr_color}{hr}{C_RESET} bpm")
    spo2_color = C_BRIGHT_RED if isinstance(spo2, (int, float)) and spo2 < 92 else C_BOLD
    _safe_print(f"  SpO2:        {spo2_color}{spo2}{C_RESET}%")
    if bp_sys and bp_dia:
        bp_color = C_BRIGHT_RED if bp_sys > 140 else C_BOLD
        _safe_print(f"  Blood Press: {bp_color}{bp_sys}/{bp_dia}{C_RESET} mmHg")

    lab = _quick_curl(f"http://{rip}:5000/health/db/latest")
    if lab:
        _safe_print(f"\n  {C_BOLD}🔬 Lab (iSaw){C_RESET}")
        for metric, info in lab.items():
            if isinstance(info, dict):
                val = info.get("value", "?")
                unit = info.get("unit", "")
                ts = info.get("timestamp", "")[:10]
                _safe_print(f"  {metric:14s} {C_BOLD}{val}{C_RESET} {unit} {C_DIM}({ts}){C_RESET}")
    _safe_print()


def _slash_threats():
    _safe_print(f"\n  {C_BOLD}⚠️ Threat Level{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/threat/status")
    if not data:
        _safe_print(f"  {C_DIM}Threat engine not responding{C_RESET}\n")
        return
    defcon = data.get("level", data.get("defcon", "?"))
    colors = {"1": C_BRIGHT_RED, "2": C_BRIGHT_RED, "3": C_BRIGHT_YELLOW, "4": C_BRIGHT_BLUE, "5": C_BRIGHT_GREEN}
    names = {"1": "MAXIMUM", "2": "HIGH", "3": "ELEVATED", "4": "GUARDED", "5": "PEACE"}
    color = colors.get(str(defcon), C_DIM)
    name = names.get(str(defcon), "UNKNOWN")
    _safe_print(f"  {color}{C_BOLD}DEFCON {defcon} — {name}{C_RESET}")
    score = data.get("score", data.get("threat_score", 0))
    _safe_print(f"  Threat Score:  {score}")
    actions = data.get("total_actions", data.get("actions", 0))
    _safe_print(f"  Actions taken: {actions}")
    _safe_print()


def _slash_drone():
    _safe_print(f"\n  {C_BOLD}🚁 Drone{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5001/drone/status")
    if not data:
        _safe_print(f"  {C_DIM}Drone proxy offline{C_RESET}\n")
        return
    connected = data.get("connected", False)
    bat = data.get("battery", "?")
    status = f"{C_BRIGHT_GREEN}connected{C_RESET}" if connected else f"{C_DIM}standby{C_RESET}"
    _safe_print(f"  Status:    {status}")
    _safe_print(f"  Battery:   {bat}%")
    _safe_print()


def _slash_containers():
    _safe_print(f"\n  {C_BOLD}🐳 GCP Containers{C_RESET}\n")
    if not GCP_IP:
        _safe_print(f"  {C_DIM}GCP not configured{C_RESET}\n")
        return
    out = _quick_ssh(GCP_IP, SSH_GCP, GCP_USER,
        "sudo docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null")
    if out:
        for line in out.split('\n')[:20]:
            _safe_print(f"  {line}")
    else:
        _safe_print(f"  {C_BRIGHT_RED}❌ Unreachable{C_RESET}")
    _safe_print()


def _slash_entity():
    _safe_print(f"\n  {C_BOLD}🤖 Entity{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Entity offline{C_RESET}\n")
        return
    fps = data.get("fps", 0)
    cam = "✅" if data.get("camera_open") else "❌"
    hailo = "✅" if data.get("hailo_available") else "❌"
    persons = data.get("persons_detected", 0)
    model = data.get("model", "?")
    uptime = data.get("uptime", "?")
    _safe_print(f"  FPS:       {C_BOLD}{fps:.1f}{C_RESET}")
    _safe_print(f"  Camera:    {cam}")
    _safe_print(f"  Hailo AI:  {hailo}")
    _safe_print(f"  Persons:   {persons}")
    _safe_print(f"  Model:     {model}")
    _safe_print(f"  Uptime:    {uptime}")
    _safe_print()


def _slash_wifi():
    _safe_print(f"\n  {C_BOLD}📡 WiFi Defense{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/wifi/status")
    if not data:
        _safe_print(f"  {C_DIM}WiFi defense not responding{C_RESET}\n")
        return
    active = data.get("monitoring", data.get("active", False))
    deauths = data.get("deauth_attacks", data.get("deauths", 0))
    evil = data.get("evil_twins", 0)
    status = f"{C_BRIGHT_GREEN}✅ Active{C_RESET}" if active else f"{C_BRIGHT_RED}❌ Inactive{C_RESET}"
    _safe_print(f"  Monitor:   {status}")
    _safe_print(f"  Deauths:   {deauths}")
    _safe_print(f"  Evil Twin: {evil}")
    _safe_print()


def _slash_coffee():
    _safe_print(f"\n  {C_BOLD}☕ Coffee Machine{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/coffee/status")
    if not data:
        _safe_print(f"  {C_DIM}Coffee machine offline{C_RESET}\n")
        return
    _safe_print(f"  Status: {data.get('status', '?')}")
    _safe_print(f"  Brews today: {data.get('brews_today', 0)}")
    _safe_print()


def _slash_ha():
    _safe_print(f"\n  {C_BOLD}🏠 Home Assistant{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/ha/status")
    if not data:
        _safe_print(f"  {C_DIM}HA not responding{C_RESET}\n")
        return
    status = f"{C_BRIGHT_GREEN}✅ UP{C_RESET}" if data.get("running") else f"{C_BRIGHT_RED}❌ DOWN{C_RESET}"
    _safe_print(f"  Status:   {status}")
    _safe_print(f"  Uptime:   {data.get('uptime', '?')}")
    _safe_print(f"  Entities: {data.get('entities', '?')}")
    _safe_print()


def _slash_picar():
    _safe_print(f"\n  {C_BOLD}🤖 PiCar-X{C_RESET}\n")
    picar_ip = os.getenv("PICAR_IP", "")
    picar_ts = os.getenv("PICAR_TAILSCALE_IP", "")
    data = {}
    if picar_ip:
        data = _quick_curl(f"http://{picar_ip}:5002/status")
    if not data and picar_ts:
        data = _quick_curl(f"http://{picar_ts}:5002/status")
    if not data:
        _safe_print(f"  {C_DIM}PiCar-X offline or not configured{C_RESET}\n")
        return
    bat = data.get("battery_voltage", "?")
    dist = data.get("distance", data.get("ultrasonic", "?"))
    _safe_print(f"  Battery:  {C_BOLD}{bat}V{C_RESET}")
    _safe_print(f"  Distance: {dist} cm")
    _safe_print()


def _slash_logs():
    _safe_print(f"\n  {C_BOLD}📋 Entity Logs (last 15){C_RESET}\n")
    rip = RASPI_IP or RASPI_TS
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    out = _quick_ssh(rip, SSH_RASPI, RASPI_USER,
        "journalctl -u tokio-entity --no-pager -n 15 2>/dev/null || tail -15 /home/*/tokio_raspi/logs/*.log 2>/dev/null")
    if out:
        for line in out.split('\n'):
            if 'error' in line.lower():
                _safe_print(f"  {C_BRIGHT_RED}{line}{C_RESET}")
            elif 'warn' in line.lower():
                _safe_print(f"  {C_BRIGHT_YELLOW}{line}{C_RESET}")
            else:
                _safe_print(f"  {C_GRAY}{line}{C_RESET}")
    else:
        _safe_print(f"  {C_DIM}No logs available{C_RESET}")
    _safe_print()


def _slash_see():
    _safe_print(f"\n  {C_BOLD}👁️ Camera Vision{C_RESET}\n")
    rip = RASPI_TS or RASPI_IP
    if not rip:
        _safe_print(f"  {C_DIM}Raspi not configured{C_RESET}\n")
        return
    data = _quick_curl(f"http://{rip}:5000/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Entity offline{C_RESET}\n")
        return
    persons = data.get("persons_detected", 0)
    faces = data.get("known_faces", [])
    emotion = data.get("emotion", "neutral")
    _safe_print(f"  Persons:  {C_BOLD}{persons}{C_RESET}")
    if faces:
        _safe_print(f"  Faces:    {', '.join(faces)}")
    _safe_print(f"  Emotion:  {emotion}")
    thoughts = data.get("thoughts", data.get("ai_thoughts", ""))
    if thoughts:
        _safe_print(f"  Thoughts: {C_ITALIC}{thoughts}{C_RESET}")
    _safe_print()


def _slash_gcp():
    _safe_print(f"\n  {C_BOLD}☁️ GCP Agent{C_RESET}\n")
    if not GCP_IP:
        _safe_print(f"  {C_DIM}GCP not configured{C_RESET}\n")
        return
    out = _quick_ssh(GCP_IP, SSH_GCP, GCP_USER,
        "curl -s http://127.0.0.1:8000/health 2>/dev/null")
    if out:
        try:
            d = _json.loads(out)
            _safe_print(f"  Status: {C_BRIGHT_GREEN}✅ Healthy{C_RESET}")
            for k, v in d.items():
                if k not in ("status",):
                    _safe_print(f"  {k}: {v}")
        except Exception:
            _safe_print(f"  {C_DIM}{out[:200]}{C_RESET}")
    else:
        _safe_print(f"  {C_BRIGHT_RED}❌ Unreachable{C_RESET}")
    _safe_print()


def _slash_sitrep():
    _safe_print(f"\n  {C_BOLD}📊 SITREP — Full Situation Report{C_RESET}")
    _safe_print(f"  {C_DIM}{time.strftime('%Y-%m-%d %H:%M:%S')}{C_RESET}\n")
    _slash_status()
    _slash_threats()
    _slash_health()
    _slash_wifi()


def _slash_diff():
    """Show git diff of current directory."""
    _safe_print(f"\n  {C_BOLD}Git Diff{C_RESET}\n")
    try:
        r = _sp.run(["git", "diff", "--stat"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            _safe_print(f"  {C_DIM}Not a git repository{C_RESET}\n")
            return
        if not r.stdout.strip():
            _safe_print(f"  {C_DIM}No changes{C_RESET}\n")
            return
        _safe_print(f"  {C_GRAY}{r.stdout.strip()}{C_RESET}")
        # Also show staged
        r2 = _sp.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True, timeout=10)
        if r2.stdout.strip():
            _safe_print(f"\n  {C_BOLD}Staged:{C_RESET}")
            _safe_print(f"  {C_BRIGHT_GREEN}{r2.stdout.strip()}{C_RESET}")
        # Untracked
        r3 = _sp.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, timeout=10)
        if r3.stdout.strip():
            files = r3.stdout.strip().split('\n')[:10]
            _safe_print(f"\n  {C_BOLD}Untracked ({len(r3.stdout.strip().split(chr(10)))}):{C_RESET}")
            for f in files:
                _safe_print(f"  {C_BRIGHT_YELLOW}  {f}{C_RESET}")
    except Exception as e:
        _safe_print(f"  {C_BRIGHT_RED}Error: {e}{C_RESET}")
    _safe_print()


def _slash_commit():
    """Quick git commit — stages all and commits with a message."""
    _safe_print(f"\n  {C_BOLD}Git Commit{C_RESET}\n")
    try:
        r = _sp.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            _safe_print(f"  {C_DIM}Not a git repository{C_RESET}\n")
            return
        if not r.stdout.strip():
            _safe_print(f"  {C_DIM}Nothing to commit{C_RESET}\n")
            return
        # Show what would be committed
        changes = r.stdout.strip().split('\n')
        _safe_print(f"  {C_BOLD}Changes ({len(changes)}):{C_RESET}")
        for c in changes[:15]:
            status = c[:2]
            fname = c[3:]
            color = C_BRIGHT_GREEN if 'A' in status else C_BRIGHT_YELLOW if 'M' in status else C_BRIGHT_RED if 'D' in status else C_DIM
            _safe_print(f"    {color}{status}{C_RESET} {fname}")
        if len(changes) > 15:
            _safe_print(f"    {C_DIM}... and {len(changes) - 15} more{C_RESET}")
        _safe_print()
        try:
            msg = input(f"  {C_BRIGHT_CYAN}Commit message: {C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            _safe_print(f"\n  {C_DIM}Cancelled{C_RESET}")
            return
        if not msg:
            _safe_print(f"  {C_DIM}Cancelled (empty message){C_RESET}")
            return
        # Stage and commit
        _sp.run(["git", "add", "-A"], capture_output=True, timeout=10)
        r2 = _sp.run(["git", "commit", "-m", msg], capture_output=True, text=True, timeout=15)
        if r2.returncode == 0:
            _safe_print(f"  {C_BRIGHT_GREEN}{_ICON_OK} Committed: {msg}{C_RESET}")
        else:
            _safe_print(f"  {C_BRIGHT_RED}{_ICON_FAIL} {r2.stderr.strip() or r2.stdout.strip()}{C_RESET}")
    except Exception as e:
        _safe_print(f"  {C_BRIGHT_RED}Error: {e}{C_RESET}")
    _safe_print()


def _slash_branch():
    """Show current git branch and recent commits."""
    _safe_print(f"\n  {C_BOLD}Git Branch{C_RESET}\n")
    try:
        r = _sp.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            _safe_print(f"  {C_DIM}Not a git repository{C_RESET}\n")
            return
        branch = r.stdout.strip()
        _safe_print(f"  Branch: {C_BRIGHT_CYAN}{branch}{C_RESET}")
        # Recent commits
        r2 = _sp.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True, timeout=5)
        if r2.stdout.strip():
            _safe_print(f"\n  {C_BOLD}Recent commits:{C_RESET}")
            for line in r2.stdout.strip().split('\n'):
                hash_part = line[:7]
                msg_part = line[8:]
                _safe_print(f"    {C_BRIGHT_YELLOW}{hash_part}{C_RESET} {msg_part}")
    except Exception as e:
        _safe_print(f"  {C_BRIGHT_RED}Error: {e}{C_RESET}")
    _safe_print()


_SLASH_COMMANDS = {
    "/status": _slash_status,
    "/waf": _slash_waf,
    "/health": _slash_health,
    "/threats": _slash_threats,
    "/drone": _slash_drone,
    "/containers": _slash_containers,
    "/entity": _slash_entity,
    "/sitrep": _slash_sitrep,
    "/wifi": _slash_wifi,
    "/coffee": _slash_coffee,
    "/ha": _slash_ha,
    "/logs": _slash_logs,
    "/see": _slash_see,
    "/picar": _slash_picar,
    "/gcp": _slash_gcp,
    "/diff": _slash_diff,
    "/commit": _slash_commit,
    "/branch": _slash_branch,
}


# ═══════════════════════════════════════════════════════
# Banner
# ═══════════════════════════════════════════════════════

def show_banner(model: str, provider: str, mode_parts: list[str] | None = None):
    g = [196, 202, 208, 214, 220, 226]

    banner_lines = [
        "████████╗ ██████╗ ██╗  ██╗██╗ ██████╗ ",
        "╚══██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗",
        "   ██║   ██║   ██║█████╔╝ ██║██║   ██║",
        "   ██║   ██║   ██║██╔═██╗ ██║██║   ██║",
        "   ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝",
        "   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝",
    ]

    _safe_print()
    for i, line in enumerate(banner_lines):
        color = c256(g[i % len(g)])
        _safe_print(f"    {color}{line}{C_RESET}")

    mode_str = " + ".join(mode_parts) if mode_parts else "Interactive"

    _safe_print(f"    {C_BOLD}{C_BRIGHT_WHITE}  TokioAI{C_RESET} {C_GRAY}v5.2{C_RESET}")
    if model.startswith("dual:"):
        parts = model[5:].split("+")
        p_name = parts[0].split("/")[-1] if parts else "?"
        s_name = parts[1].split("/")[-1] if len(parts) > 1 else "?"
        _safe_print(f"    {C_BRIGHT_GREEN}  {p_name}{C_GRAY} + {C_BRIGHT_YELLOW}{s_name}{C_GRAY} via {provider} • {mode_str} • {C_BRIGHT_CYAN}DUAL ROUTER{C_RESET}")
    else:
        _safe_print(f"    {C_GRAY}  {model} via {provider} • {mode_str}{C_RESET}")
    _safe_print()
    _safe_print(f"    {C_GRAY}  Type {C_BRIGHT_CYAN}?{C_GRAY} for help • {C_BRIGHT_YELLOW}Tab{C_GRAY} to complete • {C_BRIGHT_YELLOW}Ctrl+C{C_GRAY} to cancel{C_RESET}")
    _safe_print()


# ═══════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════

def show_help():
    w = min(_term_width() - 4, 60)
    groups = list_aliases()
    model_lines = ""
    for group_name, aliases in groups.items():
        if not aliases:
            continue
        items = ", ".join(f"{C_BRIGHT_CYAN}{a}{C_RESET}→{C_GRAY}{m}{C_RESET}" for a, m in aliases[:4])
        model_lines += f"  {C_BOLD}{group_name}:{C_RESET} {items}\n"

    _safe_print(f"""
{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}
{C_BOLD} TokioAI v5.2 — Help{C_RESET}
{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}

{C_BOLD}Commands:{C_RESET}
  {C_BRIGHT_CYAN}exit{C_RESET}, {C_BRIGHT_CYAN}quit{C_RESET}       Exit CLI
  {C_BRIGHT_CYAN}reset{C_RESET}             New conversation
  {C_BRIGHT_CYAN}compact{C_RESET}           Compress old messages (free up context)
  {C_BRIGHT_CYAN}stats{C_RESET}             Show token usage & costs
  {C_BRIGHT_CYAN}model{C_RESET}             Show current model
  {C_BRIGHT_CYAN}model <name>{C_RESET}      Switch model (opus, sonnet, flash3, gpt4o, etc.)
  {C_BRIGHT_CYAN}models{C_RESET}            List all available model aliases
  {C_BRIGHT_CYAN}persistent{C_RESET}        Toggle persistent mode
  {C_BRIGHT_CYAN}unlimited{C_RESET}         Toggle unlimited mode
  {C_BRIGHT_CYAN}stop{C_RESET}              Stop persistent mode
  {C_BRIGHT_CYAN}config{C_RESET}            Show configuration
  {C_BRIGHT_CYAN}clear{C_RESET}             Clear screen
  {C_BRIGHT_CYAN}help{C_RESET}              This help

{C_BOLD}Dual-Model Router:{C_RESET}
  {C_BRIGHT_CYAN}model dual{C_RESET}        Switch to dual mode (K2.7-code 70% + K3 30%)
  {C_BRIGHT_CYAN}dual{C_RESET}              Show router stats & recent routing decisions
  {C_BRIGHT_CYAN}threshold <N>{C_RESET}     Set routing threshold (10-90, default 50)
  {C_BRIGHT_CYAN}force k2.7{C_RESET}        Force all requests to K2.7-code
  {C_BRIGHT_CYAN}force k3{C_RESET}          Force all requests to K3
  {C_BRIGHT_CYAN}force auto{C_RESET}        Resume auto-routing

{C_BOLD}Safety Layer:{C_RESET}
  {C_BRIGHT_CYAN}safety{C_RESET}            Show safety status & last redaction summary
  {C_BRIGHT_CYAN}safety allow <val>{C_RESET}  Add a value to the allow-list

{C_BOLD}Quick Commands (instant, no LLM):{C_RESET}
  {C_BRIGHT_GREEN}/status{C_RESET}           System overview
  {C_BRIGHT_GREEN}/sitrep{C_RESET}           Full situation report
  {C_BRIGHT_GREEN}/waf{C_RESET}              WAF attack stats
  {C_BRIGHT_GREEN}/health{C_RESET}           Health vitals + Lab data
  {C_BRIGHT_GREEN}/threats{C_RESET}          DEFCON threat level
  {C_BRIGHT_GREEN}/drone{C_RESET}            Drone status
  {C_BRIGHT_GREEN}/entity{C_RESET}           Entity vision status
  {C_BRIGHT_GREEN}/containers{C_RESET}       GCP Docker containers
  {C_BRIGHT_GREEN}/see{C_RESET}              Camera snapshot + AI analysis
  {C_BRIGHT_GREEN}/wifi{C_RESET}             WiFi defense status
  {C_BRIGHT_GREEN}/coffee{C_RESET}           Coffee machine status
  {C_BRIGHT_GREEN}/ha{C_RESET}               Home Assistant status
  {C_BRIGHT_GREEN}/picar{C_RESET}            PiCar-X robot status
  {C_BRIGHT_GREEN}/gcp{C_RESET}              GCP agent health
  {C_BRIGHT_GREEN}/logs{C_RESET}             Entity logs (last 15)

{C_BOLD}Git:{C_RESET}
  {C_BRIGHT_GREEN}/diff{C_RESET}             Git diff summary
  {C_BRIGHT_GREEN}/commit{C_RESET}           Quick stage + commit
  {C_BRIGHT_GREEN}/branch{C_RESET}           Current branch + recent commits

{C_BOLD}Arguments:{C_RESET}
  {C_BRIGHT_CYAN}--persistent{C_RESET}, {C_BRIGHT_CYAN}-p{C_RESET}  Keep working until you say 'stop'
  {C_BRIGHT_CYAN}--unlimited{C_RESET}, {C_BRIGHT_CYAN}-u{C_RESET}   No round or time limits
  {C_BRIGHT_CYAN}--model{C_RESET}, {C_BRIGHT_CYAN}-m{C_RESET}       Model override
  {C_BRIGHT_CYAN}--provider{C_RESET}         Provider override
  {C_BRIGHT_CYAN}--setup{C_RESET}            Setup wizard
  {C_BRIGHT_CYAN}--verbose{C_RESET}, {C_BRIGHT_CYAN}-v{C_RESET}     Debug logging

{C_BOLD}Model Aliases:{C_RESET}
{model_lines}
{C_BOLD}Shortcuts:{C_RESET}
  {C_BRIGHT_YELLOW}?{C_RESET} or {C_BRIGHT_YELLOW}h{C_RESET} → help  {C_BRIGHT_YELLOW}s{C_RESET} → stats  {C_BRIGHT_YELLOW}r{C_RESET} → reset  {C_BRIGHT_YELLOW}c{C_RESET} → compact  {C_BRIGHT_YELLOW}m{C_RESET} → models  {C_BRIGHT_YELLOW}q{C_RESET} → quit

{C_BOLD}Tips:{C_RESET}
  {C_GRAY}• End line with \\ for multi-line input{C_RESET}
  {C_GRAY}• Press Tab to autocomplete commands{C_RESET}
  {C_GRAY}• Type {C_BRIGHT_CYAN}model <Tab>{C_GRAY} to see model options{C_RESET}
  {C_GRAY}• Costs tracked per model in stats{C_RESET}
{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}
""")


def show_models():
    w = min(_term_width() - 4, 60)
    groups = list_aliases()
    _safe_print(f"\n{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
    _safe_print(f"{C_BOLD}  Available Models{C_RESET}")
    _safe_print(f"{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
    for group_name, aliases in groups.items():
        if not aliases:
            continue
        _safe_print(f"\n  {C_BOLD}{C_BRIGHT_WHITE}{group_name}:{C_RESET}")
        for alias, model in aliases:
            _safe_print(f"    {C_BRIGHT_CYAN}{alias:<14}{C_RESET} → {C_GRAY}{model}{C_RESET}")
    _safe_print(f"\n  {C_DIM}Switch: model <alias>{C_RESET}")
    _safe_print(f"{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}\n")


def _show_config():
    w = min(_term_width() - 4, 60)
    _safe_print(f"\n{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
    _safe_print(f"{C_BOLD}  Configuration{C_RESET}")
    _safe_print(f"{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
    _safe_print(f"  Provider:  {C_BOLD}{PROVIDER}{C_RESET}")
    _safe_print(f"  Model:     {C_BOLD}{MODEL}{C_RESET}")
    if VERTEX_PROJECT:
        _safe_print(f"  GCP:       {VERTEX_PROJECT} ({VERTEX_REGION})")
    # Show API keys (masked)
    _safe_print(f"\n  {C_BOLD}API Keys:{C_RESET}")
    _key_names = [
        ("Anthropic", "ANTHROPIC_API_KEY"),
        ("OpenAI", "OPENAI_API_KEY"),
        ("Gemini", "GEMINI_API_KEY"),
        ("Google", "GOOGLE_API_KEY"),
        ("Kimi", "KIMI_API_KEY"),
        ("Moonshot", "MOONSHOT_API_KEY"),
        ("OpenRouter", "OPENROUTER_API_KEY"),
    ]
    _any_key = False
    for label, env_name in _key_names:
        val = os.getenv(env_name, "")
        if val:
            _safe_print(f"  {label:12s} {C_GREEN}{_mask_key(val)}{C_RESET}")
            _any_key = True
    if not _any_key:
        _safe_print(f"  {C_GRAY}(none configured — using Vertex SA or run --setup){C_RESET}")
    _safe_print(f"\n  {C_BOLD}Hosts:{C_RESET}")
    _safe_print(f"  Raspi:     {RASPI_IP or '(not set)'} / {RASPI_TS or '(not set)'}")
    _safe_print(f"  GCP:       {GCP_IP or '(not set)'}")
    _safe_print(f"  Router:    {ROUTER_IP or '(not set)'}")
    _safe_print(f"\n  {C_BOLD}SSH Keys:{C_RESET}")
    raspi_ok = "✅" if os.path.isfile(SSH_RASPI) else "❌"
    gcp_ok = "✅" if os.path.isfile(SSH_GCP) else "❌"
    _safe_print(f"  Raspi:     {raspi_ok} {SSH_RASPI}")
    _safe_print(f"  GCP:       {gcp_ok} {SSH_GCP}")
    _safe_print(f"{C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}\n")


# ═══════════════════════════════════════════════════════
# Process Message
# ═══════════════════════════════════════════════════════

def process_message(ops: TokioOps, user_input: str):
    """Process a user message with streaming support."""
    t0 = time.time()
    tool_count = 0

    def on_tool_start(name, args):
        nonlocal tool_count
        tool_count += 1
        _safe_print(_format_tool_start(name, args))

    def on_tool_end(name, result):
        _safe_print(_format_tool_result(name, result))

    text_already_printed = False
    streaming_buffer = []
    secure_stream = SecureStreamBuffer(_safe_write)

    def on_text(text):
        nonlocal text_already_printed
        rendered = MarkdownRenderer.render(_mask_sensitive(text))
        _safe_print(f"\n{rendered}")
        text_already_printed = True

    def on_token(token):
        """Stream tokens through SecureStreamBuffer — masks credentials even when split across tokens."""
        nonlocal text_already_printed
        streaming_buffer.append(token)
        secure_stream.add(token)
        text_already_printed = True

    # Use streaming for Anthropic and OpenAI, fallback for others
    use_stream = ops._client_type in ("anthropic", "openai")

    if not use_stream:
        _safe_print(f"  {C_GRAY}Thinking...{C_RESET}")

    try:
        result = ops.chat(user_input, on_tool_start=on_tool_start,
                          on_tool_end=on_tool_end, on_text=on_text,
                          on_token=on_token if use_stream else None,
                          stream=use_stream)
    except KeyboardInterrupt:
        if streaming_buffer:
            secure_stream.flush()
            _safe_write("\n")
        _safe_print(f"\n  {C_BRIGHT_YELLOW}Cancelled{C_RESET}")
        return
    except Exception as e:
        if streaming_buffer:
            secure_stream.flush()
            _safe_write("\n")
        _safe_print(f"\n  {C_BRIGHT_RED}{_ICON_FAIL} Error: {e}{C_RESET}")
        return

    # End streaming line — flush any held-back buffer (may contain partial key)
    if streaming_buffer:
        secure_stream.flush()
        _safe_write("\n")

    if result and not text_already_printed:
        rendered = MarkdownRenderer.render(_mask_sensitive(result))
        _safe_print(f"\n{rendered}")

    # Stats bar
    elapsed = time.time() - t0
    parts = []
    if elapsed >= 60:
        parts.append(f"{_ICON_TIME} {int(elapsed // 60)}m{int(elapsed % 60)}s")
    else:
        parts.append(f"{_ICON_TIME} {elapsed:.1f}s")
    if tool_count > 0:
        parts.append(f"{_ICON_TOOLS} {tool_count} tools")
    parts.append(f"{_ICON_STATS} {ops.token_usage_str}")

    # Cost tracking — use DELTA tokens, not cumulative total
    input_t = ops._total_input_tokens
    output_t = ops._total_output_tokens
    delta_in = input_t - getattr(ops, '_last_tracked_input', 0)
    delta_out = output_t - getattr(ops, '_last_tracked_output', 0)
    ops._last_tracked_input = input_t
    ops._last_tracked_output = output_t

    # For dual-model routing, track costs under the ACTUAL model used (not "dual:...")
    cost_model = ops.router_active_model if ops.is_dual_mode else ops.model
    if delta_in > 0 or delta_out > 0:
        _cost_tracker.add_usage(cost_model, delta_in, delta_out)
        this_cost = _cost_tracker.estimate_single(cost_model, delta_in, delta_out)
        parts.append(f"{_ICON_COST} ~{this_cost} (session: {_cost_tracker.format_cost()})")

    # Show which model was used in dual mode
    if ops.is_dual_mode:
        badge = ops.router_badge
        badge_color = C_BRIGHT_GREEN if badge == "K2.7" else C_BRIGHT_YELLOW
        parts.insert(0, f"{badge_color}[{badge}]{C_GRAY}")

    _safe_print(f"\n  {C_GRAY}{f' {_BOX_V} '.join(parts)}{C_RESET}")


# ═══════════════════════════════════════════════════════
# Multi-line input
# ═══════════════════════════════════════════════════════

def _read_multiline(first_line: str) -> str:
    if not first_line.endswith('\\'):
        return first_line
    lines = [first_line[:-1]]
    while True:
        try:
            continuation = input(f"  {C_DIM}...{C_RESET} ")
            if continuation.endswith('\\'):
                lines.append(continuation[:-1])
            else:
                lines.append(continuation)
                break
        except (EOFError, KeyboardInterrupt):
            break
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
# Main Loop
# ═══════════════════════════════════════════════════════

def run_interactive(
    max_rounds: int = 25,
    max_time: int = 600,
    persistent: bool = False,
    provider_override: str = None,
    model_override: str = None,
):
    """Run the interactive CLI loop. ZERO terminal manipulation."""
    global _terminal_saved_state
    _load_history()

    current_provider = provider_override or PROVIDER
    current_model = model_override or MODEL

    # Validate minimum config
    if current_provider in ("anthropic-vertex", "claude-vertex", "vertex") and not VERTEX_PROJECT:
        _safe_print(f"\n{C_BRIGHT_RED}ERROR: Vertex AI project not configured{C_RESET}")
        _safe_print(f"\n  Run: {C_BRIGHT_CYAN}tokioai --setup{C_RESET}\n")
        return

    # Build mode display
    mode_parts = ["Interactive"]
    if max_rounds == 0:
        mode_parts.append("Unlimited")
    if persistent:
        mode_parts.append("Persistent")

    show_banner(current_model, current_provider, mode_parts)

    # Save clean terminal state
    if not _IS_WINDOWS and sys.stdin.isatty():
        try:
            _terminal_saved_state = termios.tcgetattr(sys.stdin)
        except Exception:
            pass

    try:
        ops = TokioOps(provider=current_provider, model=current_model)
    except SystemExit:
        return
    except Exception as e:
        _safe_print(f"\n  {C_BRIGHT_RED}✗ Failed to initialize: {e}{C_RESET}")
        return

    _safe_print(f"  {C_BRIGHT_GREEN}✓{C_RESET} Connected ({C_BRIGHT_CYAN}{current_model}{C_RESET} via {C_GRAY}{current_provider}{C_RESET})")

    ops._max_rounds = max_rounds
    ops._max_time = max_time
    _persistent_mode = persistent

    if max_rounds == 0:
        _safe_print(f"  {C_BRIGHT_YELLOW}∞ Unlimited mode{C_RESET}")
    if _persistent_mode:
        _safe_print(f"  {C_BRIGHT_YELLOW}🔄 Persistent mode — will keep working until 'stop'{C_RESET}")

    # Session restore
    prev = _load_session()
    if prev and prev.get("messages"):
        _safe_print(f"\n  {C_BRIGHT_YELLOW}📋 Previous session found ({prev.get('timestamp', '?')}){C_RESET}")
        for msg in prev["messages"][-4:]:
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:100]
            icon = f"{C_BRIGHT_CYAN}▸{C_RESET}" if role == "user" else f"{C_BRIGHT_GREEN}◂{C_RESET}"
            _safe_print(f"    {icon} {C_GRAY}{content}{'…' if len(str(msg.get('content', ''))) > 100 else ''}{C_RESET}")
        _safe_print(f"  {C_GRAY}Enter = resume │ 'new' = fresh session{C_RESET}")
        try:
            choice = input(f"  ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        if choice not in ("new", "nueva", "n"):
            ops._messages = prev["messages"]
            _safe_print(f"  {C_BRIGHT_GREEN}✓ Session restored{C_RESET}")
        else:
            _safe_print(f"  {C_GRAY}New session.{C_RESET}")

    # Show active tasks and memory status on startup
    from .ops import _load_tasks, _load_memory
    active_tasks = [t for t in _load_tasks() if t.get("status") != "done"]
    mem_size = len(_load_memory())
    if active_tasks or mem_size:
        _safe_print()
        if mem_size:
            _safe_print(f"  {C_GRAY}📝 Memory: {mem_size} chars loaded{C_RESET}")
        if active_tasks:
            _safe_print(f"  {C_GRAY}📋 Active tasks:{C_RESET}")
            for t in active_tasks[-5:]:
                status = t.get("status", "pending")
                icon = {"pending": "○", "in_progress": "◉", "blocked": "⊘"}.get(status, "○")
                _safe_print(f"    {C_GRAY}{icon} #{t['id']} {t['task'][:60]} ({status}){C_RESET}")

    _safe_print()

    while True:
        # Restore terminal to clean state before every prompt
        if _terminal_saved_state and not _IS_WINDOWS:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _terminal_saved_state)
            except Exception:
                pass
        _flush_stdin()

        try:
            prompt = f"\n{RL_START}{C_BOLD}{C_BRIGHT_CYAN}{RL_END}{_PROMPT_CHAR}{RL_START}{C_RESET}{RL_END} "
            user_input = input(prompt).strip()
        except KeyboardInterrupt:
            # Ctrl+C at prompt: cancel current input, NOT exit session
            _safe_print(f"\n  {C_GRAY}(interrupted — press Ctrl+C again quickly to exit){C_RESET}")
            # Track rapid double Ctrl+C to exit
            now = time.time()
            if hasattr(run_interactive, '_last_ctrlc') and (now - run_interactive._last_ctrlc) < 1.5:
                _safe_print(f"\n{C_GRAY}Bye!{C_RESET}")
                break
            run_interactive._last_ctrlc = now
            continue
        except EOFError:
            _safe_print(f"\n{C_GRAY}Bye!{C_RESET}")
            break
        except UnicodeDecodeError:
            _safe_print(f"  {C_BRIGHT_YELLOW}Input encoding error — try again{C_RESET}")
            continue

        if not user_input:
            continue

        user_input = _read_multiline(user_input)
        _save_history()

        # ── Built-in commands ──
        lower = user_input.lower().strip()

        if lower in ("exit", "quit", "q"):
            _safe_print(f"{C_GRAY}Bye!{C_RESET}")
            break

        # ── Shortcuts ──
        if lower in ("?", "h"):
            lower = "help"
        elif lower == "s":
            lower = "stats"
        elif lower == "r":
            lower = "reset"
        elif lower == "c":
            lower = "compact"
        elif lower == "m":
            lower = "models"

        if lower == "help":
            show_help()
            continue

        if lower == "models":
            show_models()
            continue

        if lower == "reset":
            ops.reset()
            _safe_print(f"  {C_BRIGHT_GREEN}✓ Conversation reset{C_RESET}")
            continue

        if lower == "compact":
            before = len(ops._messages)
            if before < 6:
                _safe_print(f"  {C_GRAY}Nothing to compact ({before} messages){C_RESET}")
            else:
                ops._compact_messages(on_text=lambda t: _safe_print(f"  {C_BRIGHT_YELLOW}{t.strip()}{C_RESET}"))
                after = len(ops._messages)
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Compacted: {before} → {after} messages{C_RESET}")
            continue

        if lower == "clear":
            os.system("cls" if _IS_WINDOWS else "clear")
            continue

        if lower == "config":
            _show_config()
            continue

        if lower == "stats":
            w = min(_term_width() - 4, 50)
            _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
            _safe_print(f"  {C_BOLD}Statistics{C_RESET}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}")
            if ops.is_dual_mode:
                _safe_print(f"  Mode:      {C_BOLD}{C_BRIGHT_YELLOW}DUAL-MODEL ROUTER{C_RESET}")
                _safe_print(f"  Primary:   {C_BRIGHT_GREEN}{ops.router.primary_model}{C_RESET}")
                _safe_print(f"  Secondary: {C_BRIGHT_YELLOW}{ops.router.secondary_model}{C_RESET}")
                _safe_print(f"  Threshold: score >= {ops.router.threshold} -> secondary")
            else:
                _safe_print(f"  Model:     {C_BOLD}{ops.model}{C_RESET}")
            _safe_print(f"  Provider:  {ops.provider}")
            est = ops._estimate_tokens() if hasattr(ops, '_estimate_tokens') else 0
            _safe_print(f"  Messages:  {len(ops._messages)} (~{est:,} tokens, compacted {ops._compaction_count}x)")
            _safe_print(f"  Tokens:    {ops.token_usage_str}")
            _safe_print(f"  Cost:      {_cost_tracker.format_cost()}")
            if _cost_tracker.model_usage:
                _safe_print(f"\n  {C_BOLD}Per model:{C_RESET}")
                for m, u in _cost_tracker.model_usage.items():
                    short_name = m.split("/")[-1] if "/" in m else m
                    c = f"${u['cost']:.4f}" if u['cost'] < 0.01 else f"${u['cost']:.2f}"
                    _safe_print(f"    {short_name}: {u['input']:,}in/{u['output']:,}out = {c}")
            # Show dual-model router stats
            if ops.is_dual_mode and ops.router:
                rs = ops.router.stats
                if rs.total_calls > 0:
                    _safe_print(f"\n  {C_BOLD}Router Stats:{C_RESET}")
                    _safe_print(f"    K2.7-code: {rs.primary_calls} calls ({rs.primary_ratio*100:.0f}%) = ${rs.primary_cost:.4f}")
                    _safe_print(f"    K3:        {rs.secondary_calls} calls ({(1-rs.primary_ratio)*100:.0f}%) = ${rs.secondary_cost:.4f}")
                    if rs.savings_estimate > 0:
                        _safe_print(f"    {C_BRIGHT_GREEN}Saved: ${rs.savings_estimate:.4f} vs all-K3{C_RESET}")
                    if rs.last_decisions:
                        _safe_print(f"\n  {C_BOLD}Recent routing:{C_RESET}")
                        for d in rs.last_decisions[-5:]:
                            color = C_BRIGHT_GREEN if d["model"] == "K2.7" else C_BRIGHT_YELLOW
                            _safe_print(f"    [{d['time']}] {color}{d['model']}{C_RESET} (score={d['score']}) {C_GRAY}{d['query'][:45]}{C_RESET}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{_LINE_THIN * w}{C_RESET}\n")
            continue

        # Dual-model router command
        if lower == "dual" or lower == "router":
            if not ops.is_dual_mode:
                _safe_print(f"  {C_GRAY}Not in dual-model mode. Switch with: model dual{C_RESET}")
            else:
                _safe_print(f"\n{ops.router.format_stats()}")
            continue

        if lower.startswith("dual threshold ") or lower.startswith("threshold "):
            if ops.is_dual_mode:
                try:
                    val = int(lower.split()[-1])
                    if 10 <= val <= 90:
                        ops.router.threshold = val
                        _safe_print(f"  {C_BRIGHT_GREEN}OK{C_RESET} Threshold = {val} (lower = more K3, higher = more K2.7)")
                    else:
                        _safe_print(f"  {C_GRAY}Threshold must be 10-90 (current: {ops.router.threshold}){C_RESET}")
                except ValueError:
                    _safe_print(f"  {C_GRAY}Usage: threshold <10-90>{C_RESET}")
            else:
                _safe_print(f"  {C_GRAY}Not in dual-model mode.{C_RESET}")
            continue

        if lower.startswith("force "):
            if ops.is_dual_mode:
                arg = lower[6:].strip()
                if arg in ("auto", "none", "off"):
                    ops.router.force(None)
                    _safe_print(f"  {C_BRIGHT_GREEN}OK{C_RESET} Router back to auto mode")
                elif arg in ("k2.7", "k27", "primary", "code", "cheap"):
                    ops.router.force(ops.router.primary_model)
                    _safe_print(f"  {C_BRIGHT_GREEN}OK{C_RESET} Forced to K2.7-code (type 'force auto' to restore)")
                elif arg in ("k3", "secondary", "smart", "pro"):
                    ops.router.force(ops.router.secondary_model)
                    _safe_print(f"  {C_BRIGHT_YELLOW}OK{C_RESET} Forced to K3 (type 'force auto' to restore)")
                else:
                    _safe_print(f"  {C_GRAY}Usage: force k2.7 | force k3 | force auto{C_RESET}")
            else:
                _safe_print(f"  {C_GRAY}Not in dual-model mode.{C_RESET}")
            continue

        # Safety layer commands
        if lower == "safety":
            report = getattr(ops, '_last_safety_report', None)
            _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}Safety Layer{C_RESET}")
            _safe_print(f"  Status: {'paranoid' if ops._guard.paranoid else 'normal'}")
            _safe_print(f"  Patterns: {len(ops._guard.patterns)}")
            _safe_print(f"  Allow-list: {len(ops._guard.allow_list)} value(s)")
            if report:
                _safe_print(f"  Last: {report.summary()}")
                if report.redactions:
                    cats = report.redacted_categories
                    _safe_print(f"  Redacted categories: {', '.join(f'{k}={v}' for k, v in sorted(cats.items()))}")
            else:
                _safe_print(f"  Last: no API call yet")
            _safe_print(f"  {C_GRAY}Tip: 'safety allow <value>' to bypass redaction for a known-safe value{C_RESET}")
            continue

        if lower.startswith("safety allow "):
            val = user_input[13:].strip()
            if val:
                ops._guard.add_allow(val)
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Added to safety allow-list{C_RESET}")
            else:
                _safe_print(f"  {C_GRAY}Usage: safety allow <value>{C_RESET}")
            continue

        # Model switch
        if lower == "model":
            _safe_print(f"\n  {C_BRIGHT_CYAN}🧠{C_RESET} {ops.model} ({ops.provider})")
            _safe_print(f"  {C_GRAY}Switch: model <name>  |  List: models{C_RESET}")
            continue

        if lower.startswith("model "):
            new_model_name = lower[6:].strip()
            new_model = resolve_model(new_model_name)
            old_model = ops.model
            new_provider = current_provider
            need_new_client = False

            # ── Dual-model router mode ──
            if new_model.startswith("dual:"):
                or_key = os.getenv("OPENROUTER_API_KEY")
                if not or_key:
                    _safe_print(f"  {C_BRIGHT_YELLOW}!{C_RESET}  Dual mode requires OPENROUTER_API_KEY. Run: tokioai --setup")
                    continue
                try:
                    old_msgs = ops._messages
                    ops = TokioOps(provider="openrouter", model=new_model)
                    ops._messages = old_msgs
                    ops._max_rounds = max_rounds
                    ops._max_time = max_time
                    current_provider = "openrouter"
                    current_model = new_model
                    parts = new_model[5:].split("+")
                    p_name = parts[0].split("/")[-1] if parts else "?"
                    s_name = parts[1].split("/")[-1] if len(parts) > 1 else "?"
                    _safe_print(f"  {C_BRIGHT_GREEN}OK{C_RESET} {old_model} -> {C_BRIGHT_GREEN}{p_name}{C_RESET} + {C_BRIGHT_YELLOW}{s_name}{C_RESET} (DUAL ROUTER)")
                    _safe_print(f"  {C_GRAY}Auto-routes: simple -> K2.7-code, complex -> K3{C_RESET}")
                    _safe_print(f"  {C_GRAY}Commands: dual (stats), threshold N, force k2.7/k3/auto{C_RESET}")
                except Exception as e:
                    _safe_print(f"  {C_BRIGHT_RED}!{C_RESET} Failed: {e}")
                continue

            # OpenRouter models contain "/" (e.g., moonshotai/kimi-k3, anthropic/claude-sonnet-4)
            if "/" in new_model and current_provider != "openrouter":
                or_key = os.getenv("OPENROUTER_API_KEY")
                if or_key:
                    new_provider = "openrouter"
                    need_new_client = True
                else:
                    _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  OpenRouter models require OPENROUTER_API_KEY. Run: tokioai --setup")
                    continue
            elif "/" in new_model:
                pass  # already on openrouter, just switch model
            elif "gemini" in new_model and (current_provider not in ("gemini", "google", "gemini-vertex")
                                         or (any(x in new_model for x in ("gemini-3", "gemini-3.")) and current_provider == "gemini-vertex")
                                         or (not any(x in new_model for x in ("gemini-3", "gemini-3.")) and current_provider == "gemini")):
                # Gemini 3.x MUST use API key (not Vertex AI — gives 404)
                is_gemini3 = any(x in new_model for x in ("gemini-3", "gemini-3."))
                if is_gemini3 and (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                    new_provider = "gemini"
                    need_new_client = True
                elif not is_gemini3:
                    # Gemini 2.x — prefer gemini-vertex if SA credentials exist
                    sa_gemini = os.getenv("GEMINI_SA_PATH", "")
                    _gvp = os.getenv("GEMINI_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT") or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
                    if _gvp or (sa_gemini and os.path.isfile(sa_gemini)):
                        new_provider = "gemini-vertex"
                        need_new_client = True
                    elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
                        new_provider = "gemini"
                        need_new_client = True
                    else:
                        _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  Gemini requires credentials. Run: tokioai --setup")
                        continue
                elif not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                    _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  Gemini 3.x requires GEMINI_API_KEY (not Vertex). Run: tokioai --setup")
                    continue
            elif "gpt" in new_model or new_model in ("o1", "o3", "o3-mini"):
                if os.getenv("OPENAI_API_KEY") and current_provider != "openai":
                    new_provider = "openai"
                    need_new_client = True
                elif not os.getenv("OPENAI_API_KEY"):
                    _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  OpenAI requires OPENAI_API_KEY. Run: tokioai --setup")
                    continue
            elif ("kimi" in new_model or "moonshot" in new_model) and current_provider not in ("kimi", "moonshot"):
                kimi_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
                if kimi_key:
                    new_provider = "kimi"
                    need_new_client = True
                else:
                    _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  Kimi K2 requires KIMI_API_KEY. Get it at: https://platform.moonshot.cn/")
                    continue
            elif "claude" in new_model and current_provider not in ("anthropic", "anthropic-vertex", "vertex"):
                if VERTEX_PROJECT:
                    new_provider = "anthropic-vertex"
                    need_new_client = True
                elif os.getenv("ANTHROPIC_API_KEY"):
                    new_provider = "anthropic"
                    need_new_client = True
                else:
                    _safe_print(f"  {C_BRIGHT_YELLOW}⚠{C_RESET}  Claude requires credentials. Run: tokioai --setup")
                    continue

            try:
                if need_new_client:
                    # Swap credentials when switching between Claude and Gemini
                    if new_provider == "gemini-vertex":
                        gemini_sa = os.getenv("GEMINI_SA_PATH", "")
                        if gemini_sa and os.path.isfile(gemini_sa):
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gemini_sa
                    elif new_provider == "anthropic-vertex":
                        claude_sa = os.getenv("CLAUDE_SA_PATH", os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""))
                        if claude_sa and os.path.isfile(claude_sa):
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = claude_sa
                    old_msgs = ops._messages
                    ops = TokioOps(provider=new_provider, model=new_model)
                    ops._messages = old_msgs
                    current_provider = new_provider
                else:
                    ops.switch_model(new_model)
                ops._max_rounds = max_rounds
                ops._max_time = max_time
                current_model = new_model
                label = f" (via {new_provider})" if need_new_client else ""
                _safe_print(f"  {C_BRIGHT_GREEN}✓{C_RESET} {old_model} → {C_BRIGHT_CYAN}{new_model}{C_RESET}{label}")
            except Exception as e:
                _safe_print(f"  {C_BRIGHT_RED}✗{C_RESET} Failed: {e}")
            continue

        # Unlimited toggle
        if lower == "unlimited":
            if max_rounds == 0:
                ops._max_rounds = 25
                ops._max_time = 600
                max_rounds = 25
                max_time = 600
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Normal mode: 25 rounds, 10min max{C_RESET}")
            else:
                ops._max_rounds = 0
                ops._max_time = 0
                max_rounds = 0
                max_time = 0
                _safe_print(f"  {C_BRIGHT_YELLOW}∞ Unlimited mode{C_RESET}")
            continue

        # Persistent toggle
        if lower == "persistent":
            _persistent_mode = not _persistent_mode
            if _persistent_mode:
                ops._max_rounds = 0
                ops._max_time = 0
                max_rounds = 0
                max_time = 0
                _safe_print(f"  {C_BRIGHT_YELLOW}🔄 Persistent ON — works until 'stop'{C_RESET}")
            else:
                ops._max_rounds = 25
                ops._max_time = 600
                max_rounds = 25
                max_time = 600
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Persistent OFF — 25 rounds{C_RESET}")
            continue

        if lower == "stop" and _persistent_mode:
            _persistent_mode = False
            ops._max_rounds = 25
            ops._max_time = 600
            max_rounds = 25
            max_time = 600
            _safe_print(f"  {C_BRIGHT_GREEN}✓ Stopped. Normal mode.{C_RESET}")
            continue

        # ── Slash commands ──
        if lower in _SLASH_COMMANDS:
            _SLASH_COMMANDS[lower]()
            continue

        # ── Process with AI ──
        process_message(ops, user_input)

        # Save session after each exchange
        _save_session(ops._messages)

        # Flush leftover input
        _flush_stdin()

        # Persistent mode loop — fully autonomous
        if _persistent_mode:
            while _persistent_mode:
                # Restore terminal before waiting for input
                if _terminal_saved_state and not _IS_WINDOWS:
                    try:
                        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _terminal_saved_state)
                    except Exception:
                        pass
                _flush_stdin()

                # Wait for next instruction — blocking prompt (user controls the pace)
                try:
                    _safe_print(f"\n  {C_GRAY}[persistent] Waiting for next task... (type 'stop' or Ctrl+C to halt){C_RESET}")
                    follow_up = input(
                        f"  {RL_START}{C_GRAY}{RL_END}[persistent]{RL_START}{C_RESET}{RL_END} "
                        f"{RL_START}{C_BOLD}{C_BRIGHT_CYAN}{RL_END}{_PROMPT_CHAR}{RL_START}{C_RESET}{RL_END} "
                    ).strip()
                except KeyboardInterrupt:
                    _persistent_mode = False
                    _safe_print(f"\n  {C_BRIGHT_GREEN}✓ Persistent stopped.{C_RESET}")
                    break
                except EOFError:
                    _persistent_mode = False
                    _safe_print(f"\n  {C_BRIGHT_GREEN}✓ Persistent stopped.{C_RESET}")
                    break

                if not follow_up:
                    continue
                if follow_up.lower() in ("stop", "parar", "detener", "exit", "done"):
                    _persistent_mode = False
                    ops._max_rounds = 25
                    ops._max_time = 600
                    max_rounds = 25
                    max_time = 600
                    _safe_print(f"  {C_BRIGHT_GREEN}✓ Persistent stopped.{C_RESET}")
                    break
                follow_up = _read_multiline(follow_up)
                _save_history()
                process_message(ops, follow_up)
                _save_session(ops._messages)
                _flush_stdin()

    _save_history()
    _save_session(ops._messages)


def run_single(query: str, provider: str = None, model: str = None):
    """Run a single command and exit."""
    ops = TokioOps(provider=provider or PROVIDER, model=model or MODEL)
    _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}{_PROMPT_CHAR}{C_RESET} {query}\n")
    process_message(ops, query)


# ═══════════════════════════════════════════════════════
# Setup Wizard
# ═══════════════════════════════════════════════════════

def _mask_key(key: str) -> str:
    """Mask an API key for display: show first 8 + last 4 chars."""
    if not key or len(key) < 16:
        return "***"
    return f"{key[:8]}...{key[-4:]}"


def _input_safe(prompt: str, default: str = "", secret: bool = False) -> str:
    """Input with Ctrl+C handling. If secret=True, hides input like a password."""
    try:
        if secret:
            import getpass
            val = getpass.getpass(prompt).strip()
        else:
            val = input(prompt).strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt


def run_setup():
    """Interactive setup wizard — creates .env (local or global)"""
    w = min(_term_width() - 4, 60)

    # Determine where to write: if NOT in main install dir, write LOCAL .env
    global_env_dir = os.path.expanduser("~/.tokioai")
    global_env_path = os.path.join(global_env_dir, ".env")

    cwd = os.path.realpath(os.getcwd())
    home_tokioai = os.path.realpath(os.path.expanduser("~/tokioai"))

    # Isolated env: different dir AND has tokioai_cli (it's a separate clone)
    is_isolated = (cwd != home_tokioai and
                   os.path.exists(os.path.join(os.getcwd(), "tokioai_cli")))

    if is_isolated:
        env_dir = os.getcwd()
        env_path = os.path.join(env_dir, ".env")
    else:
        env_dir = global_env_dir
        env_path = global_env_path

    existing_config = {}
    # Follow symlinks to read real file
    real_env = os.path.realpath(env_path) if os.path.exists(env_path) else env_path
    if os.path.exists(real_env):
        with open(real_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing_config[k.strip()] = v.strip()

    _safe_print(f"""
{C_BOLD}{C_BRIGHT_CYAN}{'=' * w}{C_RESET}
{C_BOLD}  TokioAI v5.2 — Setup{C_RESET}
{C_BOLD}{C_BRIGHT_CYAN}{'=' * w}{C_RESET}
""")

    if existing_config:
        cur_provider = existing_config.get("TOKIOAI_PROVIDER", "?")
        cur_model = existing_config.get("TOKIOAI_MODEL", "?")
        _safe_print(f"  {C_GRAY}Current config: {cur_provider} / {cur_model}{C_RESET}")
        _safe_print(f"  {C_GRAY}File: {env_path}{C_RESET}\n")

    _safe_print(f"""Choose your AI provider:

  {C_BRIGHT_CYAN}1{C_RESET}) Claude via Vertex AI  {C_GRAY}(GCP service account — recommended for teams){C_RESET}
  {C_BRIGHT_CYAN}2{C_RESET}) Claude via API key    {C_GRAY}(console.anthropic.com){C_RESET}
  {C_BRIGHT_CYAN}3{C_RESET}) OpenAI GPT            {C_GRAY}(platform.openai.com){C_RESET}
  {C_BRIGHT_CYAN}4{C_RESET}) Google Gemini          {C_GRAY}(aistudio.google.com — free tier! Gemini 2.5/3.x){C_RESET}
  {C_BRIGHT_CYAN}5{C_RESET}) Kimi K2 (Moonshot AI)  {C_GRAY}(platform.moonshot.cn — latest Chinese model){C_RESET}
  {C_BRIGHT_CYAN}6{C_RESET}) OpenRouter             {C_GRAY}(openrouter.ai — 200+ models){C_RESET}
  {C_BRIGHT_CYAN}7{C_RESET}) Ollama (local)         {C_GRAY}(free, runs on your machine){C_RESET}
  {C_BRIGHT_CYAN}8{C_RESET}) Multi-provider         {C_GRAY}(configure multiple providers — switch with 'model' command){C_RESET}
""")

    try:
        choice = _input_safe(f"  {C_BOLD}Select [1-8]:{C_RESET} ")
    except KeyboardInterrupt:
        _safe_print(f"\n{C_GRAY}Cancelled.{C_RESET}")
        return

    env_lines = ["# TokioAI Configuration", f"# Generated {time.strftime('%Y-%m-%d %H:%M')}", ""]

    try:
        if choice == "1":
            _safe_print(f"\n  {C_BOLD}Claude via Vertex AI (GCP){C_RESET}")
            _safe_print(f"  {C_GRAY}Requires a GCP service account JSON with Vertex AI permissions.{C_RESET}\n")
            project = _input_safe(f"  GCP Project ID: ")
            if not project:
                _safe_print(f"\n  {C_BRIGHT_RED}Project ID is required.{C_RESET}")
                return
            sa_path = _input_safe(f"  Service Account JSON path [{C_GRAY}press Enter to use gcloud default{C_RESET}]: ")
            if sa_path:
                sa_path = os.path.expanduser(sa_path)
                if not os.path.exists(sa_path):
                    _safe_print(f"\n  {C_BRIGHT_RED}File not found: {sa_path}{C_RESET}")
                    return
                env_lines.append(f"GOOGLE_APPLICATION_CREDENTIALS={sa_path}")
            region = _input_safe(f"  Region [{C_GRAY}global{C_RESET}]: ", "global")
            _safe_print(f"\n  {C_BOLD}Available Claude models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}opus{C_RESET}      → Claude Opus 4       {C_GRAY}(most capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}sonnet{C_RESET}    → Claude Sonnet 4     {C_GRAY}(fast + smart){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}haiku{C_RESET}     → Claude Haiku 3.5    {C_GRAY}(fastest + cheapest){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}opus{C_RESET}]: ", "opus")
            env_lines += [
                "TOKIOAI_PROVIDER=anthropic-vertex",
                f"VERTEX_PROJECT={project}",
                f"ANTHROPIC_VERTEX_PROJECT_ID={project}",
                f"VERTEX_REGION={region}",
                f"ANTHROPIC_VERTEX_REGION={region}",
                f"TOKIOAI_MODEL={model}",
                "CLAUDE_CODE_USE_VERTEX=1",
            ]

        elif choice == "2":
            _safe_print(f"\n  {C_BOLD}Claude via API key{C_RESET}")
            _safe_print(f"  {C_GRAY}Get your key at: https://console.anthropic.com/settings/keys{C_RESET}\n")
            api_key = _input_safe(f"  Anthropic API key (sk-ant-...): ", secret=True)
            if not api_key:
                _safe_print(f"\n  {C_BRIGHT_RED}API key is required.{C_RESET}")
                return
            _safe_print(f"\n  {C_BOLD}Available Claude models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}opus{C_RESET}      → Claude Opus 4       {C_GRAY}(most capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}sonnet{C_RESET}    → Claude Sonnet 4     {C_GRAY}(fast + smart){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}haiku{C_RESET}     → Claude Haiku 3.5    {C_GRAY}(fastest + cheapest){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}opus{C_RESET}]: ", "opus")
            env_lines += [
                "TOKIOAI_PROVIDER=anthropic",
                f"ANTHROPIC_API_KEY={api_key}",
                f"TOKIOAI_MODEL={model}",
            ]
            _safe_print(f"\n  {C_GRAY}Key: {_mask_key(api_key)}{C_RESET}")

        elif choice == "3":
            _safe_print(f"\n  {C_BOLD}OpenAI GPT{C_RESET}")
            _safe_print(f"  {C_GRAY}Get your key at: https://platform.openai.com/api-keys{C_RESET}\n")
            api_key = _input_safe(f"  OpenAI API key (sk-...): ", secret=True)
            if not api_key:
                _safe_print(f"\n  {C_BRIGHT_RED}API key is required.{C_RESET}")
                return
            _safe_print(f"\n  {C_BOLD}Available models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}gpt4o{C_RESET}     → GPT-4o             {C_GRAY}(recommended){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}o3{C_RESET}        → o3                  {C_GRAY}(reasoning){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}o3-mini{C_RESET}   → o3-mini             {C_GRAY}(fast reasoning){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}gpt4o{C_RESET}]: ", "gpt4o")
            env_lines += [
                "TOKIOAI_PROVIDER=openai",
                f"OPENAI_API_KEY={api_key}",
                f"TOKIOAI_MODEL={model}",
            ]
            _safe_print(f"\n  {C_GRAY}Key: {_mask_key(api_key)}{C_RESET}")

        elif choice == "4":
            _safe_print(f"\n  {C_BOLD}Google Gemini{C_RESET}")
            _safe_print(f"  {C_GRAY}Get your FREE key at: https://aistudio.google.com/apikey{C_RESET}\n")
            api_key = _input_safe(f"  Gemini API key (AIza...): ", secret=True)
            if not api_key:
                _safe_print(f"\n  {C_BRIGHT_RED}API key is required.{C_RESET}")
                return
            _safe_print(f"\n  {C_BOLD}Available models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}gemini31{C_RESET}  → Gemini 3.1 Pro Preview  {C_GRAY}(latest, most capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}flash3{C_RESET}    → Gemini 3 Flash Preview   {C_GRAY}(fast + capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}pro{C_RESET}       → Gemini 2.5 Pro           {C_GRAY}(very capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}flash{C_RESET}     → Gemini 2.5 Flash         {C_GRAY}(fast + cheap){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}gemini31{C_RESET}]: ", "gemini31")
            env_lines += [
                "TOKIOAI_PROVIDER=gemini",
                f"GEMINI_API_KEY={api_key}",
                f"TOKIOAI_MODEL={model}",
            ]
            _safe_print(f"\n  {C_GRAY}Key: {_mask_key(api_key)}{C_RESET}")

        elif choice == "5":
            _safe_print(f"\n  {C_BOLD}Kimi K2 (Moonshot AI){C_RESET}")
            _safe_print(f"  {C_GRAY}Get your key at: https://platform.moonshot.cn/{C_RESET}\n")
            api_key = _input_safe(f"  Kimi API key (sk-...): ", secret=True)
            if not api_key:
                _safe_print(f"\n  {C_BRIGHT_RED}API key is required.{C_RESET}")
                return
            _safe_print(f"\n  {C_BOLD}Available models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}kimi{C_RESET}      → Kimi K2 0711 Preview  {C_GRAY}(latest, most capable){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}moonshot{C_RESET}  → Moonshot v1 Auto       {C_GRAY}(auto-select){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}kimi{C_RESET}]: ", "kimi")
            from tokioai_cli.ops import resolve_model as _resolve
            resolved = _resolve(model)
            # Guard: models with "/" are OpenRouter format, not Kimi direct
            if "/" in resolved:
                _safe_print(f"\n  {C_BRIGHT_YELLOW}!{C_RESET} Model '{resolved}' is an OpenRouter model (contains '/').")
                _safe_print(f"  {C_GRAY}Redirecting to OpenRouter setup...{C_RESET}")
                if api_key.startswith("sk-or-"):
                    # Key is already OpenRouter, auto-configure
                    env_lines += [
                        "TOKIOAI_PROVIDER=openrouter",
                        f"OPENROUTER_API_KEY={api_key}",
                        f"TOKIOAI_MODEL={resolved}",
                        f"OPENROUTER_MODEL={resolved}",
                    ]
                    _safe_print(f"\n  {C_BRIGHT_GREEN}*{C_RESET} Auto-configured as OpenRouter (detected sk-or- key)")
                else:
                    _safe_print(f"  {C_BRIGHT_RED}!{C_RESET} Your key doesn't look like an OpenRouter key (should start with sk-or-).")
                    _safe_print(f"  {C_GRAY}Use option 6 (OpenRouter) with your OpenRouter key, or use a Kimi-native model (kimi, moonshot).{C_RESET}")
                    return
            else:
                env_lines += [
                    "TOKIOAI_PROVIDER=kimi",
                    f"KIMI_API_KEY={api_key}",
                    f"TOKIOAI_MODEL={model}",
                    f"KIMI_MODEL={resolved}",
                ]
            _safe_print(f"\n  {C_GRAY}Key: {_mask_key(api_key)}{C_RESET}")

        elif choice == "6":
            _safe_print(f"\n  {C_BOLD}OpenRouter{C_RESET}")
            _safe_print(f"  {C_GRAY}Get your key at: https://openrouter.ai/keys{C_RESET}\n")
            api_key = _input_safe(f"  OpenRouter API key (sk-or-...): ", secret=True)
            if not api_key:
                _safe_print(f"\n  {C_BRIGHT_RED}API key is required.{C_RESET}")
                return
            _safe_print(f"\n  {C_BOLD}Available models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_GREEN}dual{C_RESET}        → {C_BRIGHT_GREEN}K2.7-code{C_RESET}+{C_BRIGHT_YELLOW}K3{C_RESET} auto-router {C_GRAY}(SMART: cheap 70% + smart 30%){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}kimi-k3{C_RESET}     → Kimi K3             {C_GRAY}(1M ctx, $3/$15 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}k27{C_RESET}         → Kimi K2.7-code      {C_GRAY}(131K ctx, $0.71/$3.5 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-gemini31{C_RESET} → Gemini 3.1 Pro       {C_GRAY}(1M ctx, $2/$12 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-gemini3{C_RESET}  → Gemini 3.6 Flash     {C_GRAY}(1M ctx, $1.5/$7.5 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-claude{C_RESET}   → Claude Sonnet 4      {C_GRAY}(1M ctx, $3/$15 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-opus{C_RESET}     → Claude Opus 4        {C_GRAY}(200K ctx, $15/$75 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-gpt{C_RESET}      → GPT-4.1              {C_GRAY}(1M ctx, $2/$8 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-kimi{C_RESET}     → Kimi K2              {C_GRAY}(131K ctx, $0.57/$2.3 per 1M tok){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-deepseek{C_RESET} → DeepSeek R1          {C_GRAY}(reasoning){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}or-llama{C_RESET}    → Llama 3.1 405B       {C_GRAY}(open source){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}or-claude{C_RESET}]: ", "or-claude")
            # Resolve alias to full model name for OpenRouter
            from tokioai_cli.ops import resolve_model as _resolve
            resolved = _resolve(model)
            env_lines += [
                "TOKIOAI_PROVIDER=openrouter",
                f"OPENROUTER_API_KEY={api_key}",
                f"TOKIOAI_MODEL={resolved}",
                f"OPENROUTER_MODEL={resolved}",
            ]
            _safe_print(f"\n  {C_GRAY}Key: {_mask_key(api_key)}{C_RESET}")

        elif choice == "7":
            _safe_print(f"\n  {C_BOLD}Ollama (local){C_RESET}")
            _safe_print(f"  {C_GRAY}Install Ollama: https://ollama.com/download{C_RESET}\n")
            host = _input_safe(f"  Ollama URL [{C_GRAY}http://localhost:11434{C_RESET}]: ", "http://localhost:11434")
            _safe_print(f"\n  {C_BOLD}Available models:{C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}llama{C_RESET}       → Llama 3.1 8B         {C_GRAY}(general purpose){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}codellama{C_RESET}   → CodeLlama 13B        {C_GRAY}(code generation){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}mistral{C_RESET}     → Mistral 7B           {C_GRAY}(fast){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}deepseek{C_RESET}    → DeepSeek Coder V2    {C_GRAY}(code + reasoning){C_RESET}")
            _safe_print(f"    {C_BRIGHT_CYAN}qwen{C_RESET}        → Qwen 2.5 Coder 14B  {C_GRAY}(multilingual code){C_RESET}")
            model = _input_safe(f"\n  Model [{C_GRAY}llama{C_RESET}]: ", "llama")
            from tokioai_cli.ops import resolve_model as _resolve
            resolved = _resolve(model)
            env_lines += [
                "TOKIOAI_PROVIDER=ollama",
                f"OLLAMA_HOST={host}",
                f"TOKIOAI_MODEL={model}",
                f"OLLAMA_MODEL={resolved}",
            ]
            _safe_print(f"\n  {C_BRIGHT_YELLOW}⚠{C_RESET}  Make sure to pull the model: {C_BRIGHT_CYAN}ollama pull {model}{C_RESET}")

        elif choice == "8":
            _safe_print(f"\n  {C_BOLD}Multi-provider setup{C_RESET}")
            _safe_print(f"  {C_GRAY}Configure multiple providers, switch with 'model' command at runtime.{C_RESET}\n")

            # Primary provider
            _safe_print(f"  {C_BOLD}Primary provider (default at startup):{C_RESET}")
            primary = _input_safe(f"  Provider (anthropic-vertex/anthropic/gemini/openai/ollama): ", "gemini")
            env_lines.append(f"TOKIOAI_PROVIDER={primary}")

            # Claude via Vertex
            _safe_print(f"\n  {C_BOLD}Claude via Vertex AI {C_GRAY}(Enter to skip){C_RESET}")
            vx_project = _input_safe(f"  GCP Project ID: ")
            if vx_project:
                vx_sa = _input_safe(f"  Service Account JSON path: ")
                vx_region = _input_safe(f"  Region [{C_GRAY}global{C_RESET}]: ", "global")
                env_lines += [
                    f"VERTEX_PROJECT={vx_project}",
                    f"ANTHROPIC_VERTEX_PROJECT_ID={vx_project}",
                    f"VERTEX_REGION={vx_region}",
                    f"ANTHROPIC_VERTEX_REGION={vx_region}",
                    "CLAUDE_CODE_USE_VERTEX=1",
                ]
                if vx_sa:
                    vx_sa = os.path.expanduser(vx_sa)
                    env_lines.append(f"GOOGLE_APPLICATION_CREDENTIALS={vx_sa}")

            # Gemini
            _safe_print(f"\n  {C_BOLD}Google Gemini {C_GRAY}(Enter to skip){C_RESET}")
            gem_key = _input_safe(f"  Gemini API key (AIza...): ", secret=True)
            if gem_key:
                env_lines.append(f"GEMINI_API_KEY={gem_key}")

            # Gemini via Vertex (separate SA)
            gem_sa = _input_safe(f"  Gemini Vertex SA JSON path (for 2.5 models, Enter to skip): ")
            if gem_sa:
                gem_sa = os.path.expanduser(gem_sa)
                env_lines.append(f"GEMINI_SA_PATH={gem_sa}")

            # OpenAI
            _safe_print(f"\n  {C_BOLD}OpenAI {C_GRAY}(Enter to skip){C_RESET}")
            oai_key = _input_safe(f"  OpenAI API key (sk-...): ", secret=True)
            if oai_key:
                env_lines.append(f"OPENAI_API_KEY={oai_key}")

            # Default model
            _safe_print(f"\n  {C_BOLD}Default model:{C_RESET}")
            _safe_print(f"    opus, sonnet, gemini31, flash, gpt4o, llama...")
            model = _input_safe(f"  Model [{C_GRAY}opus{C_RESET}]: ", "opus")
            env_lines.append(f"TOKIOAI_MODEL={model}")

            _safe_print(f"\n  {C_GRAY}Switch models at runtime: model opus | model gemini31 | model flash{C_RESET}")

        else:
            _safe_print(f"\n  {C_BRIGHT_RED}Invalid choice. Use 1-7.{C_RESET}")
            return

        # Optional: SSH hosts
        _safe_print(f"\n{C_BOLD}  Optional — Remote hosts {C_GRAY}(press Enter to skip each){C_RESET}")
        raspi = _input_safe(f"  Raspberry Pi IP: ")
        if raspi:
            env_lines.append(f"RASPI_IP={raspi}")
            raspi_user = _input_safe(f"  Raspi SSH user [{C_GRAY}pi{C_RESET}]: ", "pi")
            env_lines.append(f"RASPI_SSH_USER={raspi_user}")
            raspi_ts = _input_safe(f"  Raspi Tailscale IP (optional): ")
            if raspi_ts:
                env_lines.append(f"RASPI_TAILSCALE_IP={raspi_ts}")
        gcp = _input_safe(f"  GCP VM IP: ")
        if gcp:
            env_lines.append(f"GCP_SSH_HOST={gcp}")
            gcp_user = _input_safe(f"  GCP SSH user [{C_GRAY}user{C_RESET}]: ", "user")
            env_lines.append(f"GCP_SSH_USER={gcp_user}")
        router = _input_safe(f"  Router IP: ")
        if router:
            env_lines.append(f"ROUTER_IP={router}")

    except KeyboardInterrupt:
        _safe_print(f"\n\n{C_GRAY}Setup cancelled.{C_RESET}")
        return

    # ── Smart preservation: keep keys from OTHER providers + all non-provider keys ──
    # Keys grouped by provider — when switching TO a provider, we DON'T re-add
    # that provider's keys from old config (the setup just wrote fresh ones).
    # Keys from OTHER providers are preserved so multi-provider switching works.
    _provider_keys = {
        "anthropic-vertex": {
            "VERTEX_PROJECT", "ANTHROPIC_VERTEX_PROJECT_ID", "VERTEX_REGION",
            "ANTHROPIC_VERTEX_REGION", "GOOGLE_APPLICATION_CREDENTIALS",
            "CLAUDE_CODE_USE_VERTEX", "CLAUDE_SA_PATH", "GOOGLE_CLOUD_PROJECT",
            "VERTEX_MODEL",
        },
        "anthropic": {"ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"},
        "openai": {"OPENAI_API_KEY", "OPENAI_MODEL"},
        "gemini": {
            "GEMINI_API_KEY", "GEMINI_SA_PATH", "GEMINI_VERTEX_PROJECT",
            "GEMINI_VERTEX_REGION", "GEMINI_MODEL", "GOOGLE_API_KEY",
        },
        "kimi": {"KIMI_API_KEY", "MOONSHOT_API_KEY", "KIMI_MODEL", "MOONSHOT_MODEL"},
        "openrouter": {"OPENROUTER_API_KEY", "OPENROUTER_MODEL"},
        "ollama": {"OLLAMA_HOST", "OLLAMA_MODEL"},
    }

    # Determine which provider was just configured
    chosen_provider = ""
    for line in env_lines:
        if line.startswith("TOKIOAI_PROVIDER="):
            chosen_provider = line.split("=", 1)[1].strip()
            break

    # Collect keys that the setup just wrote
    new_keys = set()
    for line in env_lines:
        if "=" in line and not line.startswith("#"):
            new_keys.add(line.split("=", 1)[0].strip())

    # Keys that belong to the CHOSEN provider — never preserve these (setup wrote fresh ones)
    chosen_keys = _provider_keys.get(chosen_provider, set())

    # Meta keys that setup always writes — never duplicate
    _meta_keys = {"TOKIOAI_PROVIDER", "TOKIOAI_MODEL"}

    preserved = []
    for ekey, evalue in existing_config.items():
        # Skip if already written by setup
        if ekey in new_keys:
            continue
        # Skip meta keys (provider, model) — setup owns these
        if ekey in _meta_keys:
            continue
        # Skip keys that belong to the chosen provider (stale from old config)
        if ekey in chosen_keys:
            continue
        # Keep everything else (other provider keys, SSH hosts, custom keys)
        preserved.append(f"{ekey}={evalue}")

    if preserved:
        env_lines.append("")
        env_lines.append("# \u2500\u2500 Preserved from previous config \u2500\u2500")
        env_lines.extend(preserved)

    # Backup before overwriting
    os.makedirs(env_dir, exist_ok=True)
    real_env_write = os.path.realpath(env_path) if os.path.exists(env_path) else env_path
    if os.path.exists(real_env_write):
        import shutil
        backup_path = real_env_write + f".backup.{int(time.time())}"
        shutil.copy2(real_env_write, backup_path)
        _safe_print(f"\n  {C_GRAY}Backup: {backup_path}{C_RESET}")

    # Write to local path for isolated, real path for global
    write_target = env_path if is_isolated else real_env_write
    with open(write_target, "w") as f:
        f.write("\n".join(env_lines) + "\n")

    if is_isolated:
        _safe_print(f"\n  {C_BRIGHT_GREEN}✓{C_RESET} Config saved to {C_BRIGHT_CYAN}{env_path}{C_RESET} {C_GRAY}(isolated environment){C_RESET}")
        _safe_print(f"  {C_GRAY}Global config at ~/.tokioai/.env is UNTOUCHED.{C_RESET}")
    else:
        _safe_print(f"\n  {C_BRIGHT_GREEN}✓{C_RESET} Config saved to {C_BRIGHT_CYAN}{env_path}{C_RESET}")

    # Show summary
    from tokioai_cli.ops import resolve_model
    resolved = resolve_model(model)
    _safe_print(f"\n  {C_BOLD}Summary:{C_RESET}")
    _safe_print(f"    Provider:  {C_BRIGHT_CYAN}{env_lines[3].split('=',1)[1] if len(env_lines) > 3 else primary}{C_RESET}")
    _safe_print(f"    Model:     {C_BRIGHT_CYAN}{resolved}{C_RESET}")
    _safe_print(f"    Config:    {C_GRAY}{env_path}{C_RESET}")
    _safe_print(f"\n  {C_GRAY}Run {C_BRIGHT_CYAN}tokioai{C_GRAY} to start. Switch models anytime with {C_BRIGHT_CYAN}model <name>{C_GRAY}.{C_RESET}\n")


# ═══════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════

def main():
    import argparse
    import logging

    parser = argparse.ArgumentParser(
        description="TokioAI — Cybersecurity, DevOps, Engineering.",
    )
    parser.add_argument("query", nargs="*", help="Query (omit for interactive)")
    parser.add_argument("--model", "-m", default=None,
                        help="Model (opus, sonnet, flash3, gpt4o, llama, etc.)")
    parser.add_argument("--provider", default=None,
                        help="Provider (anthropic-vertex, anthropic, openai, gemini, openrouter, ollama)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument("--max-rounds", type=int, default=25,
                        help="Max tool rounds (0=unlimited, default: 25)")
    parser.add_argument("--max-time", type=int, default=600,
                        help="Max seconds per message (0=unlimited, default: 600)")
    parser.add_argument("--unlimited", "-u", action="store_true",
                        help="No limits on rounds or time")
    parser.add_argument("--persistent", "-p", action="store_true",
                        help="Keep working until you say 'stop'")
    parser.add_argument("--setup", action="store_true",
                        help="Run interactive setup wizard")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.setup:
        run_setup()
        return

    model_override = None
    if args.model:
        model_override = resolve_model(args.model)

    provider_override = args.provider

    max_rounds = 0 if args.unlimited else args.max_rounds
    max_time = 0 if args.unlimited else args.max_time
    persistent = args.persistent
    if persistent:
        max_rounds = 0
        max_time = 0

    try:
        if args.query:
            run_single(" ".join(args.query), provider_override, model_override)
        else:
            run_interactive(max_rounds, max_time, persistent, provider_override, model_override)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
