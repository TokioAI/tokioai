#!/usr/bin/env python3
"""
TokioAI Ops — Multi-provider AI operations engine.

Based on the production tokio_ops.py from tokioai-v2.
Supports: Claude Vertex AI, Claude API, OpenAI, Gemini (API key), OpenRouter, Ollama.

Configuration via ~/.tokioai/.env or environment variables.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Model aliases — human-friendly names → real model IDs
# ---------------------------------------------------------------------------

MODEL_ALIASES = {
    # ── Claude (Anthropic) ──
    "opus": "claude-opus-4-6",
    "opus4": "claude-opus-4-6",
    "opus-4": "claude-opus-4-6",
    "opus46": "claude-opus-4-6",
    "opus-4.6": "claude-opus-4-6",
    "claude-opus-4": "claude-opus-4-6",
    "opus3": "claude-3-opus-20240229",
    "sonnet": "claude-sonnet-4-6",
    "sonnet4": "claude-sonnet-4-6",
    "sonnet-4": "claude-sonnet-4-6",
    "sonnet46": "claude-sonnet-4-6",
    "claude-sonnet-4": "claude-sonnet-4-6",
    "sonnet37": "claude-3-7-sonnet-20250219",
    "sonnet35": "claude-3-5-sonnet-20241022",
    "haiku": "claude-3-5-haiku-20241022",
    "haiku35": "claude-3-5-haiku-20241022",
    # ── OpenAI ──
    "gpt4o": "gpt-4o",
    "gpt4": "gpt-4o",
    "gpt": "gpt-4o",
    "o1": "o1",
    "o3": "o3",
    "o3-mini": "o3-mini",
    "gpt5": "gpt-5",
    # ── Gemini ──
    "flash": "gemini-2.5-flash",
    "gemini-flash": "gemini-2.5-flash",
    "flash3": "gemini-3-flash-preview",
    "gemini3": "gemini-3-flash-preview",
    "gemini-3": "gemini-3-flash-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini31": "gemini-3.1-pro-preview",
    "gemini-3.1": "gemini-3.1-pro-preview",
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini-pro": "gemini-2.5-pro",
    "pro": "gemini-2.5-pro",
    "pro-preview": "gemini-2.5-pro-preview-06-05",
    "gemini": "gemini-2.5-flash",
    # ── Ollama (local) ──
    "llama": "llama3.1:8b",
    "llama3": "llama3.1:8b",
    "codellama": "codellama:13b",
    "mistral": "mistral:7b",
    "deepseek": "deepseek-coder-v2:16b",
    "qwen": "qwen2.5-coder:14b",
    # ── OpenRouter ──
    "or-claude": "anthropic/claude-sonnet-4",
    "or-gpt": "openai/gpt-4o",
    "or-gemini": "google/gemini-2.5-flash-preview",
    "or-llama": "meta-llama/llama-3.1-405b-instruct",
    "or-deepseek": "deepseek/deepseek-r1",
}


def resolve_model(name: str) -> str:
    """Resolve model alias to full model name."""
    return MODEL_ALIASES.get(name.lower().strip(), name)


def list_aliases() -> dict[str, list[str]]:
    """Group aliases by provider for display."""
    groups = {
        "Claude": [], "OpenAI": [], "Gemini": [],
        "Ollama": [], "OpenRouter": [],
    }
    seen = set()
    for alias, model in MODEL_ALIASES.items():
        if model in seen:
            continue
        seen.add(model)
        if "claude" in model:
            groups["Claude"].append((alias, model))
        elif "gpt" in model or model in ("o1", "o3", "o3-mini"):
            groups["OpenAI"].append((alias, model))
        elif "gemini" in model:
            groups["Gemini"].append((alias, model))
        elif ":" in model:
            groups["Ollama"].append((alias, model))
        elif "/" in model:
            groups["OpenRouter"].append((alias, model))
    return groups


# ---------------------------------------------------------------------------
# Provider detection — auto-detect from env vars
# ---------------------------------------------------------------------------

def detect_provider() -> str:
    """Auto-detect the best available provider from env vars."""
    explicit = os.getenv("TOKIOAI_PROVIDER", "").lower().strip()
    if explicit:
        return explicit

    # Vertex AI credentials → anthropic-vertex
    if os.getenv("VERTEX_PROJECT") or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID"):
        return "anthropic-vertex"

    # Direct Anthropic API key
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"

    # OpenAI
    if os.getenv("OPENAI_API_KEY"):
        return "openai"

    # Gemini (API key)
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"

    # OpenRouter
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"

    # Ollama
    if os.getenv("OLLAMA_HOST"):
        return "ollama"

    return "anthropic-vertex"  # default


def detect_model() -> str:
    """Get the configured model, resolved from aliases."""
    raw = (
        os.getenv("TOKIOAI_MODEL")
        or os.getenv("VERTEX_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("CLAUDE_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("GEMINI_MODEL")
        or ""
    )
    if raw:
        return resolve_model(raw)

    # Default per provider — opus is the most capable model
    provider = detect_provider()
    defaults = {
        "anthropic-vertex": "claude-opus-4-6",
        "anthropic": "claude-opus-4-6",
        "openai": "gpt-4o",
        "gemini": "gemini-2.5-flash",
        "gemini-vertex": "gemini-3.1-pro-preview",
        "openrouter": "anthropic/claude-opus-4",
        "ollama": os.getenv("OLLAMA_MODEL", "qwen2.5:32b"),
    }
    return defaults.get(provider, "claude-opus-4-6")


# Export for interactive.py — these are set AFTER .env is loaded
PROVIDER = detect_provider()
MODEL = detect_model()
VERTEX_PROJECT = os.getenv("VERTEX_PROJECT") or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID", "")
VERTEX_REGION = os.getenv("VERTEX_REGION") or os.getenv("ANTHROPIC_VERTEX_REGION") or os.getenv("CLOUD_ML_REGION", "global")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16384"))

# SSH keys (optional — for remote execution)
SSH_RASPI = os.path.expanduser(os.getenv("SSH_KEY_RASPI", "~/.ssh/id_rsa"))
SSH_GCP = os.path.expanduser(os.getenv("SSH_KEY_GCP", "~/.ssh/google_compute_engine"))

# Hosts (optional)
RASPI_IP = os.getenv("RASPI_IP", "")
RASPI_TS = os.getenv("RASPI_TAILSCALE_IP", "")
RASPI_USER = os.getenv("RASPI_SSH_USER", "pi")
GCP_IP = os.getenv("GCP_SSH_HOST", "")
GCP_USER = os.getenv("GCP_SSH_USER", "user")
ROUTER_IP = os.getenv("ROUTER_IP", "")


# Load SOUL.md if it exists — persistent context about infrastructure
_SOUL_CONTEXT = ""
for _soul_path in [
    os.path.expanduser("~/.tokioai/SOUL.md"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SOUL.md"),
    "SOUL.md",
]:
    if os.path.isfile(_soul_path):
        try:
            with open(_soul_path, "r") as _f:
                _SOUL_CONTEXT = "\n\n## Infrastructure Context (from SOUL.md)\n" + _f.read()
        except Exception:
            pass
        break

# Load persistent memory — survives across sessions
MEMORY_DIR = os.path.expanduser("~/.tokioai")
MEMORY_FILE = os.path.join(MEMORY_DIR, "memory.md")
TASKS_FILE = os.path.join(MEMORY_DIR, "tasks.json")

def _load_memory() -> str:
    if os.path.isfile(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                content = f.read().strip()
            if content:
                return content
        except Exception:
            pass
    return ""

def _save_memory(content: str):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w") as f:
        f.write(content)

def _load_tasks() -> list:
    if os.path.isfile(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r") as f:
                return json.loads(f.read())
        except Exception:
            pass
    return []

def _save_tasks(tasks: list):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        f.write(json.dumps(tasks, indent=2, ensure_ascii=False))

def _build_memory_context() -> str:
    """Build rich context from memory and tasks -- injected into system prompt on EVERY turn."""
    parts = []
    mem = _load_memory()
    if mem:
        parts.append("\n\n## Persistent Memory (~/.tokioai/memory.md)\n" + mem)
    tasks = _load_tasks()
    active = [t for t in tasks if t.get("status") != "done"]
    if active:
        tlines = []
        for t in active[-10:]:
            status = t.get("status", "pending")
            icon = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "blocked": "[!]"}.get(status, "[ ]")
            line = "%s #%s: %s (%s)" % (icon, t.get("id", "?"), t.get("task", "?"), status)
            if t.get("plan"):
                line += "\n    Plan: " + t["plan"]
            if t.get("current_step"):
                line += "\n    >>> CURRENT STEP: " + t["current_step"]
            if t.get("steps_done"):
                line += "\n    Done: " + ", ".join(t["steps_done"][-5:])
            if t.get("notes"):
                line += "\n    Last note: " + str(t["notes"][-1])
            tlines.append(line)
        parts.append("\n\n## Active Tasks (~/.tokioai/tasks.json)\n"
                     "IMPORTANT: Check these tasks. Update current_step as you progress.\n"
                     + "\n".join(tlines))
    return "".join(parts)

# ---------------------------------------------------------------------------
# System prompt — TokioAI personality
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """You are TokioAI — specialized in cybersecurity, hacking, engineering, DevOps, and creative problem solving.

You execute commands, fix bugs, deploy infrastructure, audit security, and build solutions. You have full access to the user's terminal.

## Your Expertise
- **Cybersecurity**: Penetration testing, vulnerability assessment, network security, OSINT, forensics, incident response, WAF/IDS/IPS, hardening
- **Hacking**: Ethical hacking, CTF, reverse engineering, exploit development, social engineering awareness
- **Engineering**: Full-stack development, system architecture, API design, database optimization, algorithms
- **DevOps**: CI/CD, Docker, Kubernetes, Terraform, Ansible, cloud infrastructure (GCP/AWS/Azure), monitoring
- **Networking**: TCP/IP, DNS, firewalls, VPN, SDN, wireless security, packet analysis
- **Creative**: Unconventional solutions, automation, scripting, tool building

## Available Tools
- **execute_local**: Run any shell command on the user's machine
- **execute_raspi**: SSH to Raspberry Pi (if configured)
- **execute_gcp**: SSH to GCP VM (if configured)
- **execute_router**: SSH to router (if configured)
- **ssh_connect**: SSH to ANY server with username/password — ask the user for IP, user, and password if not provided. Use this for ad-hoc server connections. The password is used only for the connection and never stored.
- **read_file / write_file / edit_file**: File operations (local or remote via raspi:/gcp: prefix)
- **search_files**: grep across files
- **diagnose**: System health check

## Your Approach
1. Understand the request — ask only if truly ambiguous
2. Diagnose first — read logs, check status, gather info
3. Act — fix, build, deploy, configure
4. Verify — confirm the fix works
5. Report — concise summary of what you did

## Rules
- Be DIRECT. Act first, explain after.
- NEVER give up. If something fails, try alternatives.
- Show results, not just descriptions.
- When fixing something: diagnose → root cause → fix → verify.
- When building something: plan → implement → test → deliver.
- Always mask credentials in output.
- Use Spanish if the user speaks Spanish, English otherwise.
- Be creative. Think like a hacker. Find elegant solutions.
- NEVER use emojis in your responses. Use plain text only — emojis render as broken characters on some terminals.

## Persistent Memory
You have persistent memory at ~/.tokioai/memory.md that survives across sessions.
Use the `memory` tool to read/write/append/clear your memory.
- When you learn something important about the user's setup, preferences, or ongoing work — save it.
- When the user says "remember this" or "don't forget" — always save it.
- When starting a new task, check memory first for relevant context.
- Keep memory concise: facts, not conversations.

## Task Tracking (CRITICAL FOR CONTINUITY)
You have a persistent task list at ~/.tokioai/tasks.json.
Use the `task` tool to add/update/list/remove tasks.

RULES -- follow these ALWAYS to avoid losing track:
1. BEFORE starting any non-trivial work: create a task with a plan field listing numbered steps.
2. As you complete each step: update current_step to the NEXT step.
3. If context gets compacted or you feel lost: call task list to see where you are.
4. NEVER skip updating current_step -- it is your lifeline after compaction.
5. When done: update status to done with a summary note.

## Sensitive Data
NEVER output raw passwords, API keys, tokens, or private keys.
Always mask them: show first 4 and last 4 chars with *** in between.
Example: ghp_LRsA****2QVVMa""" + _SOUL_CONTEXT

def _build_system_prompt() -> str:
    """Rebuild system prompt with FRESH memory and task context on every call."""
    return _SYSTEM_PROMPT_BASE + _build_memory_context()

# Keep backward compat for any code that reads the module-level var
SYSTEM_PROMPT = _build_system_prompt()



# ---------------------------------------------------------------------------
# Tool definitions for Claude/OpenAI/Gemini native tool use
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "execute_local",
        "description": "Execute a shell command on the local machine. Use for any system operation: install packages, check processes, network scans, file operations, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute (bash)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "execute_raspi",
        "description": "Execute a command on the Raspberry Pi via SSH. Uses LAN IP, falls back to Tailscale.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run on Raspi"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "execute_gcp",
        "description": "Execute a command on the GCP VM via SSH.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run on GCP"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "execute_router",
        "description": "Execute a command on the router via SSH (root).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run on router as root"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from local or remote systems. Use raspi:/path or gcp:/path for remote.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path. Use raspi:/path or gcp:/path for remote"},
                "lines": {"type": "integer", "description": "Max lines to read (default: all)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Prefix with raspi: or gcp: for remote.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path. Use raspi:/path or gcp:/path for remote"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace a specific string in a file. old_text must be unique in the file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path. Use raspi:/path or gcp:/path for remote"},
                "old_text": {"type": "string", "description": "Exact text to find (must be unique)"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for text patterns across files. Like grep -rn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regex pattern to search"},
                "path": {"type": "string", "description": "Directory to search (default: cwd). Use raspi:/path or gcp:/path"},
                "glob": {"type": "string", "description": "File filter glob (e.g., '*.py')"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "diagnose",
        "description": "Run system health diagnostics on local, raspi, gcp, or all targets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target: local, raspi, gcp, router, all",
                    "enum": ["local", "raspi", "gcp", "router", "all"],
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "ssh_connect",
        "description": "Connect to a remote server via SSH with username and password (no key required). Use this to execute commands on any server. The connection is non-interactive — runs a command and returns the output. If no command is given, runs 'hostname && uname -a && uptime' to test the connection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "IP address or hostname of the server"},
                "username": {"type": "string", "description": "SSH username"},
                "password": {"type": "string", "description": "SSH password"},
                "command": {"type": "string", "description": "Command to execute on the remote server. Default: 'hostname && uname -a && uptime'"},
                "port": {"type": "integer", "description": "SSH port (default: 22)"},
                "timeout": {"type": "integer", "description": "Connection timeout in seconds (default: 10)"},
            },
            "required": ["host", "username", "password"],
        },
    },
    {
        "name": "memory",
        "description": "Persistent memory that survives across sessions. Use to remember user preferences, project context, ongoing work, learned facts. Actions: read (show all memory), write (overwrite all), append (add a note), clear (erase all).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "read, write, append, or clear",
                    "enum": ["read", "write", "append", "clear"],
                },
                "content": {"type": "string", "description": "Content to write/append (ignored for read/clear)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "task",
        "description": "Persistent task tracker across sessions. Use to track what you're working on so the user can resume later. Actions: add (new task), update (change status), list (show all), remove (delete), clear_done (remove completed).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "add, update, list, remove, clear_done",
                    "enum": ["add", "update", "list", "remove", "clear_done"],
                },
                "task": {"type": "string", "description": "Task description (for add)"},
                    "plan": {"type": "string", "description": "Numbered plan steps"},
                    "current_step": {"type": "string", "description": "Which step you are currently on"},
                "id": {"type": "integer", "description": "Task ID (for update/remove)"},
                "status": {
                    "type": "string",
                    "description": "New status (for update)",
                    "enum": ["pending", "in_progress", "done", "blocked"],
                },
                "note": {"type": "string", "description": "Optional note to add to task"},
            },
            "required": ["action"],
        },
    },
]


# ---------------------------------------------------------------------------
# Command execution — safe, never touches terminal
# ---------------------------------------------------------------------------

def _run_cmd(cmd: str, timeout: int = 30) -> str:
    """Execute a local command. stdin=DEVNULL so it NEVER competes with readline."""
    try:
        r = subprocess.run(
            cmd, shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=min(timeout, 120),
        )
        out = (r.stdout + r.stderr).strip()
        return out[:16000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s — the command took too long. Try a different approach, break it into smaller steps, or inform the user."
    except Exception as e:
        return f"ERROR: {e}"


def _ssh_cmd(host: str, key: str, user: str, cmd: str, timeout: int = 30) -> str:
    """Run a command via SSH. -T and BatchMode=yes to NEVER touch the terminal."""
    if not host:
        return "ERROR: Host not configured. Set the corresponding env var in ~/.tokioai/.env"
    # Quote key path for Windows paths with spaces
    key_quoted = f'"{key}"' if " " in key else key
    ssh = (
        f'ssh -T -i {key_quoted} -o ConnectTimeout=5 -o StrictHostKeyChecking=no '
        f'-o UserKnownHostsFile=/dev/null -o LogLevel=ERROR '
        f'-o BatchMode=yes {user}@{host} "{cmd}"'
    )
    return _run_cmd(ssh, timeout)


def _raspi_cmd(cmd: str, timeout: int = 30) -> str:
    if RASPI_IP:
        result = _ssh_cmd(RASPI_IP, SSH_RASPI, RASPI_USER, cmd, timeout)
        if not result.startswith("ERROR") and not result.startswith("TIMEOUT"):
            return result
    if RASPI_TS:
        return _ssh_cmd(RASPI_TS, SSH_RASPI, RASPI_USER, cmd, timeout)
    return "ERROR: Raspi not configured. Set RASPI_IP or RASPI_TAILSCALE_IP in ~/.tokioai/.env"


def _gcp_cmd(cmd: str, timeout: int = 30) -> str:
    return _ssh_cmd(GCP_IP, SSH_GCP, GCP_USER, cmd, timeout)


def _ssh_password_cmd(host: str, username: str, password: str, cmd: str,
                      port: int = 22, timeout: int = 10) -> str:
    """SSH with username/password using paramiko. Falls back to sshpass if paramiko unavailable."""
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, port=port, username=username, password=password,
                          timeout=timeout, allow_agent=False, look_for_keys=False)
            stdin, stdout, stderr = client.exec_command(cmd, timeout=max(timeout, 30))
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            client.close()
            result = (out + err).strip()
            if exit_code != 0:
                result = f"[exit code {exit_code}]\n{result}"
            return result[:16000] if result else "(no output)"
        except paramiko.AuthenticationException:
            return f"ERROR: Authentication failed for {username}@{host} — wrong username or password"
        except paramiko.SSHException as e:
            return f"ERROR: SSH error connecting to {host}: {e}"
        except Exception as e:
            client.close()
            return f"ERROR: {e}"
    except ImportError:
        # Fallback: sshpass (Linux only)
        sshpass_cmd = (
            f'sshpass -p "{password}" ssh -T -p {port} '
            f'-o ConnectTimeout={timeout} -o StrictHostKeyChecking=no '
            f'-o UserKnownHostsFile=/dev/null -o LogLevel=ERROR '
            f'{username}@{host} "{cmd}"'
        )
        result = _run_cmd(sshpass_cmd, timeout + 5)
        if "sshpass" in result.lower() and "not found" in result.lower():
            return (
                "ERROR: paramiko not installed and sshpass not available.\n"
                "Install paramiko: pip install paramiko\n"
                "Or install sshpass: sudo apt install sshpass"
            )
        return result


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return the result string."""
    timeout = input_data.get("timeout", 30)

    if name == "execute_local":
        return _run_cmd(input_data["command"], timeout)

    elif name == "execute_raspi":
        return _raspi_cmd(input_data["command"], timeout)

    elif name == "execute_gcp":
        return _gcp_cmd(input_data["command"], timeout)

    elif name == "execute_router":
        cmd = input_data["command"]
        if ROUTER_IP:
            return _raspi_cmd(
                f'ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@{ROUTER_IP} "{cmd}"'
            )
        return "ERROR: Router not configured. Set ROUTER_IP in ~/.tokioai/.env"

    elif name == "read_file":
        path = input_data["path"]
        max_lines = input_data.get("lines", 0)
        tail = f" | head -n {max_lines}" if max_lines else ""
        if path.startswith("raspi:"):
            return _raspi_cmd(f"cat {path[6:]}{tail}")
        elif path.startswith("gcp:"):
            return _gcp_cmd(f"cat {path[4:]}{tail}")
        else:
            try:
                with open(path, "r") as f:
                    content = f.read()
                if max_lines:
                    content = "\n".join(content.split("\n")[:max_lines])
                return content[:16000]
            except Exception as e:
                return f"ERROR: {e}"

    elif name == "write_file":
        path = input_data["path"]
        content = input_data["content"]
        if path.startswith("raspi:"):
            remote_path = path[6:]
            tmp = f"/tmp/tokio_deploy_{int(time.time())}"
            with open(tmp, "w") as f:
                f.write(content)
            result = _run_cmd(f"scp -i {SSH_RASPI} -o StrictHostKeyChecking=no {tmp} {RASPI_USER}@{RASPI_IP}:{remote_path}")
            os.unlink(tmp)
            return result if result.startswith("ERROR") else f"Written to raspi:{remote_path}"
        elif path.startswith("gcp:"):
            remote_path = path[4:]
            tmp = f"/tmp/tokio_deploy_{int(time.time())}"
            with open(tmp, "w") as f:
                f.write(content)
            _run_cmd(f"scp -i {SSH_GCP} -o StrictHostKeyChecking=no {tmp} {GCP_USER}@{GCP_IP}:/tmp/_deploy_tmp")
            result = _gcp_cmd(f"sudo cp /tmp/_deploy_tmp {remote_path}")
            os.unlink(tmp)
            return result if result.startswith("ERROR") else f"Written to gcp:{remote_path}"
        else:
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                return f"Written to {path}"
            except Exception as e:
                return f"ERROR: {e}"

    elif name == "edit_file":
        path = input_data["path"]
        old_text = input_data["old_text"]
        new_text = input_data["new_text"]
        if path.startswith("raspi:") or path.startswith("gcp:"):
            content = execute_tool("read_file", {"path": path})
            if content.startswith("ERROR"):
                return content
            count = content.count(old_text)
            if count == 0:
                return f"ERROR: old_text not found in {path}"
            if count > 1:
                return f"ERROR: old_text appears {count} times — must be unique"
            new_content = content.replace(old_text, new_text, 1)
            return execute_tool("write_file", {"path": path, "content": new_content})
        else:
            try:
                with open(path, "r") as f:
                    content = f.read()
                count = content.count(old_text)
                if count == 0:
                    return f"ERROR: old_text not found in {path}"
                if count > 1:
                    return f"ERROR: old_text appears {count} times — must be unique"
                new_content = content.replace(old_text, new_text, 1)
                with open(path, "w") as f:
                    f.write(new_content)
                return f"Edited {path} (replaced 1 occurrence)"
            except Exception as e:
                return f"ERROR: {e}"

    elif name == "search_files":
        pattern = input_data["pattern"]
        path = input_data.get("path", os.getcwd())
        glob_filter = input_data.get("glob", "")
        include = f"--include='{glob_filter}'" if glob_filter else ""
        if path.startswith("raspi:"):
            return _raspi_cmd(f"grep -rn {include} '{pattern}' {path[6:] or '/home'} | head -30")
        elif path.startswith("gcp:"):
            return _gcp_cmd(f"grep -rn {include} '{pattern}' {path[4:] or '/home'} | head -30")
        else:
            return _run_cmd(f"grep -rn {include} '{pattern}' {path} | head -50")

    elif name == "diagnose":
        target = input_data["target"]
        results = []
        if target in ("local", "all"):
            results.append("\n=== LOCAL ===")
            results.append(_run_cmd("uname -a"))
            results.append(_run_cmd("uptime && free -h | head -2"))
            results.append(_run_cmd("df -h / | tail -1"))
            results.append(_run_cmd("docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo 'Docker not available'"))
        if target in ("raspi", "all"):
            results.append("\n=== RASPBERRY PI ===")
            results.append(_raspi_cmd("uptime && free -h | head -2"))
            results.append(_raspi_cmd("df -h / | tail -1"))
            results.append(_raspi_cmd("docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo 'No docker'"))
        if target in ("gcp", "all"):
            results.append("\n=== GCP ===")
            results.append(_gcp_cmd("uptime && free -h | head -2"))
            results.append(_gcp_cmd("df -h / | tail -1"))
            results.append(_gcp_cmd("sudo docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo 'No docker'"))
        if target in ("router", "all"):
            results.append("\n=== ROUTER ===")
            if ROUTER_IP:
                results.append(_raspi_cmd(f'ssh -o ConnectTimeout=5 root@{ROUTER_IP} "uptime; free | head -2"'))
            else:
                results.append("Router not configured")
        return "\n".join(results)

    elif name == "ssh_connect":
        host = input_data["host"]
        username = input_data["username"]
        password = input_data["password"]
        command = input_data.get("command", "hostname && uname -a && uptime")
        port = input_data.get("port", 22)
        timeout = input_data.get("timeout", 10)
        return _ssh_password_cmd(host, username, password, command, port, timeout)

    elif name == "memory":
        action = input_data["action"]
        content = input_data.get("content", "")
        if action == "read":
            mem = _load_memory()
            return mem if mem else "(memory is empty — use append to add notes)"
        elif action == "write":
            _save_memory(content)
            return f"Memory saved ({len(content)} chars)"
        elif action == "append":
            existing = _load_memory()
            timestamp = time.strftime("%Y-%m-%d")
            new_entry = f"\n\n## {timestamp}\n{content}" if existing else f"## {timestamp}\n{content}"
            _save_memory(existing + new_entry)
            return f"Appended to memory. Total: {len(existing) + len(new_entry)} chars"
        elif action == "clear":
            _save_memory("")
            return "Memory cleared"
        return "Unknown memory action"

    elif name == "task":
        action = input_data["action"]
        tasks = _load_tasks()
        if action == "add":
            task_desc = input_data.get("task", "Untitled task")
            new_id = max([t.get("id", 0) for t in tasks], default=0) + 1
            tasks.append({
                "id": new_id,
                "task": input_data.get("description", input_data.get("task", "unnamed")),
                "status": "pending",
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "plan": input_data.get("plan", ""),
                "current_step": input_data.get("current_step", ""),
                "steps_done": [],
                "notes": [],
            })
            _save_tasks(tasks)
            return f"Task #{new_id} created: {task_desc}"
        elif action == "update":
            tid = input_data.get("id", 0)
            for t in tasks:
                if t.get("id") == tid:
                    if "status" in input_data:
                        t["status"] = input_data["status"]
                    if "plan" in input_data:
                        t["plan"] = input_data["plan"]
                    if "current_step" in input_data:
                        old_step = t.get("current_step", "")
                        if old_step and old_step != input_data["current_step"]:
                            t.setdefault("steps_done", []).append(old_step)
                        t["current_step"] = input_data["current_step"]
                    if input_data.get("note"):
                        t.setdefault("notes", []).append(input_data["note"])
                    t["updated"] = time.strftime("%Y-%m-%d %H:%M")
                    _save_tasks(tasks)
                    return f"Task #{tid} updated: {t['status']}"
            return f"Task #{tid} not found"
        elif action == "list":
            if not tasks:
                return "No tasks."
            lines = []
            for t in tasks:
                status = t.get("status", "pending")
                icon = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "blocked": "[!]"}.get(status, "[ ]")
                line = "%s #%s: %s (%s)" % (icon, t["id"], t["task"], status)
                if t.get("plan"):
                    line += "\n       Plan: " + t["plan"]
                if t.get("current_step"):
                    line += "\n       >>> CURRENT: " + t["current_step"]
                if t.get("steps_done"):
                    line += "\n       Completed: " + ", ".join(t["steps_done"][-5:])
                if t.get("notes"):
                    line += "\n       Last note: " + str(t["notes"][-1])[:100]
                lines.append(line)
            return "\n".join(lines)
        elif action == "remove":
            tid = input_data.get("id", 0)
            tasks = [t for t in tasks if t.get("id") != tid]
            _save_tasks(tasks)
            return f"Task #{tid} removed"
        elif action == "clear_done":
            before = len(tasks)
            tasks = [t for t in tasks if t.get("status") != "done"]
            _save_tasks(tasks)
            return f"Cleared {before - len(tasks)} completed tasks"
        return "Unknown task action"

    return f"ERROR: Unknown tool '{name}'"


# ---------------------------------------------------------------------------
# Client initialization — one function, all providers
# ---------------------------------------------------------------------------

def init_client(provider: str):
    """Initialize AI client. Returns (client, client_type)."""
    provider = provider.lower().strip()

    if provider in ("anthropic-vertex", "claude-vertex", "vertex"):
        project = VERTEX_PROJECT
        region = VERTEX_REGION
        if not project:
            print("\033[31mERROR: Vertex AI project not configured.\033[0m")
            print("Set VERTEX_PROJECT or ANTHROPIC_VERTEX_PROJECT_ID in ~/.tokioai/.env")
            print("Then run: gcloud auth application-default login")
            sys.exit(1)
        # Auto-detect credentials
        sa_paths = [
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
        ]
        for sa_path in sa_paths:
            if sa_path and os.path.isfile(sa_path):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
                break
        try:
            from anthropic import AnthropicVertex
            client = AnthropicVertex(region=region, project_id=project)
            return client, "anthropic"
        except ImportError:
            print("\033[31mERROR: anthropic[vertex] not installed\033[0m")
            print("Run: pip install 'anthropic[vertex]'")
            sys.exit(1)

    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("\033[31mERROR: ANTHROPIC_API_KEY not set\033[0m")
            print("Get your key at: https://console.anthropic.com/")
            sys.exit(1)
        try:
            from anthropic import Anthropic
            return Anthropic(api_key=api_key), "anthropic"
        except ImportError:
            print("\033[31mERROR: anthropic not installed. Run: pip install anthropic\033[0m")
            sys.exit(1)

    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            print("\033[31mERROR: OPENAI_API_KEY not set\033[0m")
            print("Get your key at: https://platform.openai.com/api-keys")
            sys.exit(1)
        try:
            from openai import OpenAI
            return OpenAI(api_key=api_key), "openai"
        except ImportError:
            print("\033[31mERROR: openai not installed. Run: pip install openai\033[0m")
            sys.exit(1)

    elif provider == "gemini-vertex":
        project = os.getenv("GEMINI_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT") or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        region = os.getenv("GEMINI_VERTEX_REGION") or os.getenv("CLOUD_ML_REGION", "us-central1")
        if not project:
            print("\033[31mERROR: Gemini Vertex project not configured.\033[0m")
            print("Set GEMINI_VERTEX_PROJECT in ~/.tokioai/.env")
            sys.exit(1)
        # Use Gemini-specific SA (different from Claude SA)
        sa_paths = [
            os.getenv("GEMINI_SA_PATH", ""),
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
        ]
        sa_file = ""
        for p in sa_paths:
            if p and os.path.isfile(p):
                sa_file = p
                break
        try:
            from google import genai
            if sa_file:
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(
                    sa_file, scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                client = genai.Client(vertexai=True, project=project, location=region, credentials=creds)
            else:
                client = genai.Client(vertexai=True, project=project, location=region)
            return client, "gemini"
        except ImportError:
            print("\033[31mERROR: google-genai not installed. Run: pip install google-genai\033[0m")
            sys.exit(1)

    elif provider in ("gemini", "google"):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            print("\033[31mERROR: GEMINI_API_KEY or GOOGLE_API_KEY not set\033[0m")
            print("Get your key at: https://aistudio.google.com/apikey")
            sys.exit(1)
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            return client, "gemini"
        except ImportError:
            print("\033[31mERROR: google-genai not installed. Run: pip install google-genai\033[0m")
            sys.exit(1)

    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            print("\033[31mERROR: OPENROUTER_API_KEY not set\033[0m")
            print("Get your key at: https://openrouter.ai/keys")
            sys.exit(1)
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
            return client, "openai"  # OpenRouter uses OpenAI-compatible API
        except ImportError:
            print("\033[31mERROR: openai not installed. Run: pip install openai\033[0m")
            sys.exit(1)

    elif provider in ("ollama", "local"):
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=f"{host}/v1",
                api_key="ollama",
            )
            return client, "openai"
        except ImportError:
            print("\033[31mERROR: openai not installed. Run: pip install openai\033[0m")
            sys.exit(1)

    else:
        print(f"\033[31mERROR: Unknown provider '{provider}'\033[0m")
        print("Available: anthropic-vertex, anthropic, openai, gemini, openrouter, ollama")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Convert tools to OpenAI function calling format
# ---------------------------------------------------------------------------

def _tools_to_openai(tools: list) -> list:
    """Convert Anthropic-style tools to OpenAI function calling format."""
    result = []
    for tool in tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        })
    return result


# ---------------------------------------------------------------------------
# Retry with exponential backoff + jitter (Claude Code pattern)
# ---------------------------------------------------------------------------

_RETRYABLE_ERRORS = (
    "overloaded", "rate_limit", "rate limit", "429", "503", "502",
    "server_error", "internal_error", "temporarily unavailable",
    "capacity", "too many requests", "service unavailable",
    "connection", "timeout", "timed out",
)

def _should_retry(error_str: str) -> bool:
    """Check if an API error is retryable."""
    lower = error_str.lower()
    return any(k in lower for k in _RETRYABLE_ERRORS)

def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter: min(cap, base * 2^attempt) * random(0.5, 1.0)"""
    delay = min(cap, base * (2 ** attempt))
    return delay * random.uniform(0.5, 1.0)

MAX_API_RETRIES = 4  # up to 4 retries (5 total attempts)


# ---------------------------------------------------------------------------
# TokioOps — Main engine
# ---------------------------------------------------------------------------

class TokioOps:
    """TokioAI Operations engine with native tool use."""

    # Auto-compact: triggers on message count OR estimated token size
    COMPACT_THRESHOLD = 40        # keep more context before compacting
    COMPACT_KEEP_RECENT = 16      # keep last N messages intact
    COMPACT_TOKEN_LIMIT = 100000  # compact if estimated tokens exceed this
    MAX_TOOL_RESULT = 12000       # truncate tool results beyond this
    # Cheap model for summarization (Sonnet = ~5x cheaper than Opus)
    COMPACT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, provider: str = None, model: str = None):
        self._provider_name = provider or PROVIDER
        # If provider was explicitly passed but model wasn't, use correct default for that provider
        if provider and not model:
            defaults = {
                "anthropic-vertex": "claude-opus-4-6",
                "anthropic": "claude-opus-4-6",
                "openai": "gpt-4o",
                "gemini": "gemini-2.5-flash",
                "gemini-vertex": "gemini-3.1-pro-preview",
                "openrouter": "anthropic/claude-opus-4",
                "ollama": os.getenv("OLLAMA_MODEL", "qwen2.5:32b"),
                "local": os.getenv("OLLAMA_MODEL", "qwen2.5:32b"),
            }
            self._model = defaults.get(provider, MODEL)
        else:
            self._model = model or MODEL
        self._client, self._client_type = init_client(self._provider_name)
        self._messages: list[dict] = []
        self._gemini_history: list = []  # Persistent Gemini contents
        self._max_turns = 25  # default tool rounds per request
        self._max_rounds = 25
        self._max_time = 600
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._last_tracked_input = 0
        self._last_tracked_output = 0
        self._compaction_count = 0
        self._compact_failures = 0  # circuit breaker for compact
        self._state = "idle"  # state machine: idle → thinking → tool_exec → done
        self._hooks: dict[str, list[Callable]] = {}  # event → [callbacks]

    @property
    def state(self) -> str:
        return self._state

    def on(self, event: str, callback: Callable):
        """Register a hook callback. Events: pre_tool, post_tool, pre_api, post_api, state_change."""
        self._hooks.setdefault(event, []).append(callback)

    def _emit(self, event: str, **kwargs):
        """Emit a hook event to all registered callbacks."""
        for cb in self._hooks.get(event, []):
            try:
                cb(**kwargs)
            except Exception:
                pass

    def _set_state(self, new_state: str):
        old = self._state
        self._state = new_state
        self._emit("state_change", old_state=old, new_state=new_state)

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    @property
    def provider(self) -> str:
        return self._provider_name

    @property
    def token_usage_str(self) -> str:
        return f"{self._total_input_tokens:,} in / {self._total_output_tokens:,} out"

    def switch_model(self, new_model: str, new_provider: str = None):
        """Switch to a different model (and optionally provider) at runtime."""
        if new_provider and new_provider != self._provider_name:
            self._provider_name = new_provider
            self._client, self._client_type = init_client(new_provider)
        self._model = new_model

    def _extract_text(self, msg: dict) -> str:
        """Extract readable text from a message for summarization."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return content[:500]
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", "")[:200])
                    elif item.get("type") == "tool_result":
                        parts.append(f"[tool_result: {str(item.get('content', ''))[:100]}]")
                    elif item.get("type") == "tool_use":
                        parts.append(f"[tool: {item.get('name', '?')}]")
                elif hasattr(item, "text"):
                    parts.append(str(item.text)[:200] if item.text else "")
                elif hasattr(item, "type") and item.type == "tool_use":
                    parts.append(f"[tool: {getattr(item, 'name', '?')}]")
            return " ".join(parts)[:500]
        return str(content)[:500]

    def _has_tool_use(self, msg: dict) -> bool:
        """Check if a message contains tool_use blocks (assistant) or tool_result blocks (user)."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return False
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    t = item.get("type", "")
                    if t in ("tool_use", "tool_result"):
                        return True
                elif hasattr(item, "type") and item.type in ("tool_use", "tool_result"):
                    return True
        return False

    def _fix_orphaned_tool_use(self):
        """Scan messages and inject missing tool_result blocks to prevent API errors."""
        i = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
                i += 1
                continue
            tool_use_ids = [
                item["id"] if isinstance(item, dict) else item.id
                for item in msg["content"]
                if (isinstance(item, dict) and item.get("type") == "tool_use") or
                   (hasattr(item, "type") and getattr(item, "type", "") == "tool_use")
            ]
            if not tool_use_ids:
                i += 1
                continue
            dummy = [{"type": "tool_result", "tool_use_id": uid,
                      "content": "[Result unavailable — history recovered]"}
                     for uid in tool_use_ids]
            if i + 1 < len(self._messages):
                nxt = self._messages[i + 1]
                if nxt.get("role") == "user" and isinstance(nxt.get("content"), list):
                    result_ids = {
                        item.get("tool_use_id", "") if isinstance(item, dict) else ""
                        for item in nxt["content"]
                        if isinstance(item, dict) and item.get("type") == "tool_result"
                    }
                    missing = [uid for uid in tool_use_ids if uid not in result_ids]
                    if missing:
                        for uid in missing:
                            nxt["content"].append({"type": "tool_result", "tool_use_id": uid,
                                                   "content": "[Result unavailable — history recovered]"})
                    i += 2
                    continue
                if nxt.get("role") == "user" and isinstance(nxt.get("content", ""), str):
                    nxt["content"] = dummy + [{"type": "text", "text": nxt["content"]}]
                    i += 2
                    continue
            self._messages.insert(i + 1, {"role": "user", "content": dummy})
            i += 2
            continue

    def _find_safe_cut(self, target_keep: int) -> int:
        """Find a safe index to cut messages so we don't split tool_use/tool_result pairs.
        Returns the index where recent messages start (everything before gets summarized)."""
        n = len(self._messages)
        # Start from the target cut point and scan backwards to find a safe boundary
        # A safe boundary is: after an assistant text-only message, or after a user text-only message
        cut = max(0, n - target_keep)
        # Scan forward from cut to find the first safe point
        for i in range(cut, n):
            msg = self._messages[i]
            # Safe if this is a user message with plain text (not tool_results)
            # and previous message (if any) is assistant with plain text (not tool_use)
            if not self._has_tool_use(msg):
                if msg.get("role") == "user" and isinstance(msg.get("content", ""), str):
                    return i
                if msg.get("role") == "assistant" and i + 1 < n:
                    next_msg = self._messages[i + 1]
                    if next_msg.get("role") == "user" and not self._has_tool_use(next_msg):
                        return i + 1
        # Fallback: keep more messages to be safe
        return n  # don't compact if no safe cut found

    def _estimate_tokens(self) -> int:
        """Rough estimate of total tokens in messages (~4 chars per token)."""
        total = 0
        for msg in self._messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        total += len(str(item.get("content", "") or item.get("text", ""))) // 4
                    elif hasattr(item, "text") and item.text:
                        total += len(item.text) // 4
            else:
                total += len(str(content)) // 4
        return total

    def _compact_messages(self, on_text=None):
        """Auto-compact old messages into a summary when conversation gets too long."""
        if self._compact_failures >= 3:
            return  # circuit breaker — stop trying after 3 failures
        est_tokens = self._estimate_tokens()
        needs_compact = (len(self._messages) >= self.COMPACT_THRESHOLD or
                         est_tokens > self.COMPACT_TOKEN_LIMIT)
        if not needs_compact:
            return
        if on_text:
            on_text(f"\n[Auto-compacting context: {len(self._messages)} messages, ~{est_tokens} tokens]\n")

        cut_idx = self._find_safe_cut(self.COMPACT_KEEP_RECENT)
        if cut_idx <= 2:
            return  # nothing to compact

        old_msgs = self._messages[:cut_idx]
        recent_msgs = self._messages[cut_idx:]

        # Build a digest of old messages for summarization
        digest_lines = []
        for msg in old_msgs:
            role = msg.get("role", "?")
            text = self._extract_text(msg)
            if text.strip():
                digest_lines.append(f"[{role}] {text}")

        digest = "\n".join(digest_lines)
        # Limit digest size — Sonnet processes this, keep it small and cheap
        if len(digest) > 8000:
            digest = digest[:8000] + "\n... (truncated)"

        _active_tasks_ctx = ""
        try:
            _tasks_for_compact = _load_tasks()
            _active_for_compact = [t for t in _tasks_for_compact if t.get("status") != "done"]
            if _active_for_compact:
                _task_lines = []
                for t in _active_for_compact:
                    _tl = "- [%s] %s" % (t.get("status", "?"), t.get("task", "?"))
                    if t.get("plan"):
                        _tl += " | Plan: " + t["plan"]
                    if t.get("current_step"):
                        _tl += " | Current step: " + t["current_step"]
                    if t.get("notes"):
                        _tl += " | Notes: " + str(t["notes"][-1])
                    _task_lines.append(_tl)
                _active_tasks_ctx = "\nACTIVE TASKS (MUST PRESERVE):\n" + "\n".join(_task_lines)
        except Exception:
            pass

        summary_prompt = (
            "Summarize the following conversation history. This summary will REPLACE "
            "the original messages and be the ONLY context available to continue working. "
            "Be thorough.\n\n"
            "YOU MUST PRESERVE:\n"
            "1. The CURRENT TASK and what step we are on\n"
            "2. The PLAN: what has been done and what remains\n"
            "3. Key DECISIONS made and WHY\n"
            "4. Important RESULTS: IPs, paths, configs, command outputs\n"
            "5. Any ERRORS encountered and how they were resolved\n"
            "6. The user INTENT: what they want to achieve\n\n"
            "DROP: verbose tool outputs, repeated attempts, routine logs.\n\n"
            + f"CONVERSATION:\n{digest}"
            + f"{_active_tasks_ctx}"
        )

        summary = None
        # Always try Gemini Flash first — cheapest option (~$0.0001 per compact)
        try:
            from google import genai
            from google.genai import types as _gtypes
            _compact_project = (os.getenv("GEMINI_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT")
                                or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID") or "")
            if _compact_project:
                _gc = genai.Client(vertexai=True, project=_compact_project, location="global")
                _gr = _gc.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=summary_prompt,
                    config=_gtypes.GenerateContentConfig(
                        system_instruction="Summarize concisely. Keep: decisions, commands, results, errors, paths, IPs, pending tasks. Drop: verbose logs.",
                        max_output_tokens=1024,
                    ),
                )
                summary = _gr.text
        except Exception:
            pass

        # Fallback: use the main model's own client (works with any provider: Opus, Ollama, OpenAI, etc.)
        if not summary:
            try:
                if self._client_type == "anthropic":
                    resp = self._client.messages.create(
                        model=self._model,
                        max_tokens=1024,
                        system="Summarize concisely. Keep: decisions, commands, results, errors, paths, IPs, pending tasks.",
                        messages=[{"role": "user", "content": summary_prompt}],
                        timeout=30.0,
                    )
                    summary = "".join(b.text for b in resp.content if hasattr(b, "text"))
                    if hasattr(resp, "usage"):
                        self._total_input_tokens += getattr(resp.usage, "input_tokens", 0)
                        self._total_output_tokens += getattr(resp.usage, "output_tokens", 0)
                elif self._client_type == "openai":
                    resp = self._client.chat.completions.create(
                        model=self._model,  # uses current model (works with Ollama, OpenAI, OpenRouter)
                        messages=[
                            {"role": "system", "content": "Summarize concisely. Keep: decisions, commands, results, errors, paths, IPs, pending tasks."},
                            {"role": "user", "content": summary_prompt},
                        ],
                        max_tokens=1024,
                        timeout=30.0,
                    )
                    summary = resp.choices[0].message.content or ""
            except Exception:
                pass

        # Last resort: raw truncation
        if not summary:
            summary = digest[:3000]

        # Replace old messages with the summary
        self._messages = [
            {"role": "user", "content": f"[Previous conversation summary]\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from our previous conversation. Let's continue."},
        ] + recent_msgs

        self._compaction_count += 1

        # POST-COMPACTION RECOVERY: inject fresh task context
        try:
            _recovery_parts = []
            _rtasks = _load_tasks()
            _ractive = [t for t in _rtasks if t.get("status") != "done"]
            if _ractive:
                _rlines = []
                for _rt in _ractive:
                    _rl = "- [%s] %s" % (_rt.get("status", "?"), _rt.get("task", "?"))
                    if _rt.get("current_step"):
                        _rl += " >>> CURRENTLY ON: " + _rt["current_step"]
                    if _rt.get("plan"):
                        _rl += " | Plan: " + _rt["plan"]
                    _rlines.append(_rl)
                _recovery_parts.append("ACTIVE TASKS:\n" + "\n".join(_rlines))
            _rmem = _load_memory()
            if _rmem and len(_rmem) < 3000:
                _recovery_parts.append("MEMORY SNAPSHOT:\n" + _rmem[:2000])
            if _recovery_parts:
                _recovery_msg = "[CONTEXT RECOVERY after compaction]\n" + "\n\n".join(_recovery_parts)
                self._messages.insert(0, {"role": "user", "content": _recovery_msg})
                self._messages.insert(1, {"role": "assistant", "content": "I have full context. I know my active tasks and where I left off. Continuing."})
        except Exception:
            pass

        if on_text:
            on_text("\n[Context compacted: %d msgs summarized, keeping %d recent]\n" % (len(old_msgs), len(recent_msgs)))

    def chat(self, user_input: str, on_tool_start=None, on_tool_end=None,
             on_text=None, on_token=None, stream=False) -> str:
        """Process a user request with tool use.

        Args:
            on_token: Called with each text token during streaming (token: str).
                      If provided and stream=True, tokens are emitted incrementally.
            stream: Enable streaming mode (token-by-token output).
        """
        if self._client_type == "anthropic":
            if stream and on_token:
                return self._chat_anthropic_stream(user_input, on_tool_start, on_tool_end, on_text, on_token)
            return self._chat_anthropic(user_input, on_tool_start, on_tool_end, on_text)
        elif self._client_type == "openai":
            if stream and on_token:
                return self._chat_openai_stream(user_input, on_tool_start, on_tool_end, on_text, on_token)
            return self._chat_openai(user_input, on_tool_start, on_tool_end, on_text)
        elif self._client_type == "gemini":
            return self._chat_gemini(user_input, on_tool_start, on_tool_end, on_text)
        else:
            return f"ERROR: Unknown client type {self._client_type}"

    # ── Anthropic (Claude — direct API or Vertex) ─────────

    def _chat_anthropic(self, user_input, on_tool_start, on_tool_end, on_text) -> str:
        self._compact_messages(on_text)
        # After compaction, prepend active task context to help LLM orient
        if self._compaction_count > 0 and len(self._messages) <= 4:
            try:
                _task_check = _load_tasks()
                _active_check = [t for t in _task_check if t.get("status") != "done"]
                if _active_check:
                    _ctx_lines = ["[AUTO-CONTEXT: Active tasks after compaction]"]
                    for _tc in _active_check:
                        _tcl = "- [%s] %s" % (_tc.get("status", "?"), _tc.get("task", "?"))
                        if _tc.get("current_step"):
                            _tcl += " | Current step: " + _tc["current_step"]
                        _ctx_lines.append(_tcl)
                    user_input = "\n".join(_ctx_lines) + "\n\nUser message: " + user_input
            except Exception:
                pass
        self._messages.append({"role": "user", "content": user_input})
        effective_limit = self._max_rounds if self._max_rounds > 0 else 999999

        for turn in range(effective_limit):
            self._fix_orphaned_tool_use()
            self._set_state("thinking")
            self._emit("pre_api", model=self._model, turn=turn)
            # API call with exponential backoff on retryable errors
            response = None
            for attempt in range(MAX_API_RETRIES + 1):
                try:
                    response = self._client.messages.create(
                        model=self._model,
                        max_tokens=MAX_TOKENS,
                        system=_build_system_prompt(),
                        tools=TOOLS,
                        messages=self._messages,
                        timeout=120.0,
                    )
                    break  # success
                except Exception as e:
                    err_str = str(e)
                    # Context length errors — compact and retry (no backoff needed)
                    if any(k in err_str.lower() for k in ("prompt is too long", "context length", "max_tokens", "token limit", "request too large")):
                        before = len(self._messages)
                        if before > 6:
                            self._compact_messages(on_text)
                            if len(self._messages) < before:
                                break  # will retry via outer loop
                        return f"API Error: {e}"
                    # Retryable errors — backoff
                    if _should_retry(err_str) and attempt < MAX_API_RETRIES:
                        delay = _backoff_delay(attempt)
                        if on_text:
                            on_text(f"\n[API error, retrying in {delay:.1f}s... ({attempt+1}/{MAX_API_RETRIES})]\n")
                        time.sleep(delay)
                        continue
                    return f"API Error: {e}"
            if response is None:
                continue  # context was compacted, retry

            # Track tokens
            if hasattr(response, "usage"):
                self._total_input_tokens += getattr(response.usage, "input_tokens", 0)
                self._total_output_tokens += getattr(response.usage, "output_tokens", 0)

            # Detect max_tokens truncation — retry with resume prompt (Claude Code pattern)
            if getattr(response, "stop_reason", None) == "max_tokens":
                text_so_far = "".join(b.text for b in response.content if hasattr(b, "text") and b.text)
                if text_so_far:
                    self._messages.append({"role": "assistant", "content": text_so_far})
                    self._messages.append({"role": "user", "content": "[Your response was cut off. Resume directly from where you stopped — do not repeat anything.]"})
                    if on_text:
                        on_text(text_so_far)
                    continue  # retry to get the rest

            # Check for tool use
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if tool_blocks:
                # Emit any text before tools
                for block in response.content:
                    if hasattr(block, "text") and block.text and on_text:
                        on_text(block.text)

                # Serialize API objects to plain dicts so session save (JSON) works
                serialized_content = []
                for block in response.content:
                    if block.type == "tool_use":
                        serialized_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                    elif hasattr(block, "text"):
                        serialized_content.append({"type": "text", "text": block.text or ""})
                    else:
                        serialized_content.append({"type": block.type})
                self._messages.append({"role": "assistant", "content": serialized_content})

                self._set_state("tool_exec")
                tool_results = []
                try:
                    for tb in tool_blocks:
                        self._emit("pre_tool", name=tb.name, input=tb.input)
                        if on_tool_start:
                            on_tool_start(tb.name, tb.input)
                        result = execute_tool(tb.name, tb.input)
                        self._emit("post_tool", name=tb.name, result=result)
                        if on_tool_end:
                            on_tool_end(tb.name, result)
                        # Truncate very large tool results to avoid blowing context
                        if len(result) > self.MAX_TOOL_RESULT:
                            result = result[:self.MAX_TOOL_RESULT] + "\n... (truncated)"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tb.id,
                            "content": result,
                        })
                except BaseException:
                    answered_ids = {tr["tool_use_id"] for tr in tool_results}
                    for tb in tool_blocks:
                        if tb.id not in answered_ids:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tb.id,
                                "content": "Cancelled by user.",
                            })
                    self._messages.append({"role": "user", "content": tool_results})
                    raise
                else:
                    self._messages.append({"role": "user", "content": tool_results})

            else:
                # No tools — extract final text
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                if not text.strip():
                    text = "[TokioAI stopped without a response. Type your message to continue, or 'reset' to start over.]"
                self._messages.append({"role": "assistant", "content": text})
                return text

        return f"Max tool turns reached ({effective_limit} rounds). You can continue the conversation or type 'reset' to start fresh."

    # ── Anthropic Streaming ─────────────────────────

    def _chat_anthropic_stream(self, user_input, on_tool_start, on_tool_end, on_text, on_token) -> str:
        """Anthropic chat with streaming — tokens emitted as they arrive."""
        self._compact_messages(on_text)
        # After compaction, prepend active task context to help LLM orient
        if self._compaction_count > 0 and len(self._messages) <= 4:
            try:
                _task_check = _load_tasks()
                _active_check = [t for t in _task_check if t.get("status") != "done"]
                if _active_check:
                    _ctx_lines = ["[AUTO-CONTEXT: Active tasks after compaction]"]
                    for _tc in _active_check:
                        _tcl = "- [%s] %s" % (_tc.get("status", "?"), _tc.get("task", "?"))
                        if _tc.get("current_step"):
                            _tcl += " | Current step: " + _tc["current_step"]
                        _ctx_lines.append(_tcl)
                    user_input = "\n".join(_ctx_lines) + "\n\nUser message: " + user_input
            except Exception:
                pass
        self._messages.append({"role": "user", "content": user_input})
        effective_limit = self._max_rounds if self._max_rounds > 0 else 999999

        for turn in range(effective_limit):
            self._fix_orphaned_tool_use()
            self._set_state("thinking")
            self._emit("pre_api", model=self._model, turn=turn)
            # API call with backoff
            stream_obj = None
            for attempt in range(MAX_API_RETRIES + 1):
                try:
                    stream_obj = self._client.messages.create(
                        model=self._model,
                        max_tokens=MAX_TOKENS,
                        system=_build_system_prompt(),
                        tools=TOOLS,
                        messages=self._messages,
                        timeout=120.0,
                        stream=True,
                    )
                    break
                except Exception as e:
                    err_str = str(e)
                    if any(k in err_str.lower() for k in ("prompt is too long", "context length", "max_tokens", "token limit", "request too large")):
                        before = len(self._messages)
                        if before > 6:
                            self._compact_messages(on_text)
                            if len(self._messages) < before:
                                break
                        return f"API Error: {e}"
                    if _should_retry(err_str) and attempt < MAX_API_RETRIES:
                        delay = _backoff_delay(attempt)
                        if on_text:
                            on_text(f"\n[API error, retrying in {delay:.1f}s... ({attempt+1}/{MAX_API_RETRIES})]\n")
                        time.sleep(delay)
                        continue
                    return f"API Error: {e}"
            if stream_obj is None:
                continue

            # Consume stream events
            text_chunks = []
            tool_blocks = []
            current_tool = None
            tool_json_acc = ""
            input_tokens = 0
            output_tokens = 0
            stop_reason = None

            try:
                for event in stream_obj:
                    etype = getattr(event, "type", "")

                    if etype == "message_start":
                        usage = getattr(getattr(event, "message", None), "usage", None)
                        if usage:
                            input_tokens += getattr(usage, "input_tokens", 0)

                    elif etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "tool_use":
                            current_tool = {"type": "tool_use", "id": block.id, "name": block.name, "input": {}}
                            tool_json_acc = ""

                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            if getattr(delta, "type", "") == "text_delta":
                                chunk = getattr(delta, "text", "")
                                if chunk:
                                    text_chunks.append(chunk)
                                    on_token(chunk)
                            elif getattr(delta, "type", "") == "input_json_delta":
                                tool_json_acc += getattr(delta, "partial_json", "")

                    elif etype == "content_block_stop":
                        if current_tool:
                            try:
                                current_tool["input"] = json.loads(tool_json_acc) if tool_json_acc else {}
                            except json.JSONDecodeError:
                                current_tool["input"] = {}
                            tool_blocks.append(current_tool)
                            current_tool = None
                            tool_json_acc = ""

                    elif etype == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            stop_reason = getattr(delta, "stop_reason", stop_reason)
                        usage = getattr(event, "usage", None)
                        if usage:
                            output_tokens += getattr(usage, "output_tokens", 0)

            except KeyboardInterrupt:
                # Partial text already streamed — save what we have
                partial = "".join(text_chunks)
                if partial:
                    self._messages.append({"role": "assistant", "content": partial})
                raise

            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens

            full_text = "".join(text_chunks)

            # Max tokens truncation — resume
            if stop_reason == "max_tokens" and full_text.strip():
                self._messages.append({"role": "assistant", "content": full_text})
                self._messages.append({"role": "user", "content": "[Your response was cut off. Resume directly from where you stopped — do not repeat anything.]"})
                continue

            if tool_blocks:
                # Build serialized content for message history
                serialized = []
                if full_text:
                    serialized.append({"type": "text", "text": full_text})
                for tb in tool_blocks:
                    serialized.append(tb)
                self._messages.append({"role": "assistant", "content": serialized})

                # Execute tools
                self._set_state("tool_exec")
                tool_results = []
                try:
                    for tb in tool_blocks:
                        self._emit("pre_tool", name=tb["name"], input=tb["input"])
                        if on_tool_start:
                            on_tool_start(tb["name"], tb["input"])
                        result = execute_tool(tb["name"], tb["input"])
                        self._emit("post_tool", name=tb["name"], result=result)
                        if on_tool_end:
                            on_tool_end(tb["name"], result)
                        if len(result) > self.MAX_TOOL_RESULT:
                            result = result[:self.MAX_TOOL_RESULT] + "\n... (truncated)"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tb["id"],
                            "content": result,
                        })
                except BaseException:
                    answered_ids = {tr["tool_use_id"] for tr in tool_results}
                    for tb in tool_blocks:
                        if tb["id"] not in answered_ids:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tb["id"],
                                "content": "Cancelled by user.",
                            })
                    self._messages.append({"role": "user", "content": tool_results})
                    raise
                else:
                    self._messages.append({"role": "user", "content": tool_results})
            else:
                if not full_text.strip():
                    full_text = "[TokioAI stopped without a response. Type your message to continue, or 'reset' to start over.]"
                    on_token(full_text)
                self._messages.append({"role": "assistant", "content": full_text})
                self._set_state("idle")
                return full_text

        self._set_state("idle")
        return f"Max tool turns reached ({effective_limit} rounds). You can continue the conversation or type 'reset' to start fresh."

    # ── OpenAI / OpenRouter / Ollama ───────────────────

    def _chat_openai(self, user_input, on_tool_start, on_tool_end, on_text) -> str:
        self._compact_messages(on_text)
        # After compaction, prepend active task context to help LLM orient
        if self._compaction_count > 0 and len(self._messages) <= 4:
            try:
                _task_check = _load_tasks()
                _active_check = [t for t in _task_check if t.get("status") != "done"]
                if _active_check:
                    _ctx_lines = ["[AUTO-CONTEXT: Active tasks after compaction]"]
                    for _tc in _active_check:
                        _tcl = "- [%s] %s" % (_tc.get("status", "?"), _tc.get("task", "?"))
                        if _tc.get("current_step"):
                            _tcl += " | Current step: " + _tc["current_step"]
                        _ctx_lines.append(_tcl)
                    user_input = "\n".join(_ctx_lines) + "\n\nUser message: " + user_input
            except Exception:
                pass
        self._messages.append({"role": "user", "content": user_input})
        openai_tools = _tools_to_openai(TOOLS)
        effective_limit = self._max_rounds if self._max_rounds > 0 else 999999

        for turn in range(effective_limit):
            self._fix_orphaned_tool_use()
            self._set_state("thinking")
            self._emit("pre_api", provider="openai", turn=turn)
            # API call with exponential backoff
            response = None
            for attempt in range(MAX_API_RETRIES + 1):
                try:
                    msgs = [{"role": "system", "content": _build_system_prompt()}] + self._messages
                    response = self._client.chat.completions.create(
                        model=self._model,
                        messages=msgs,
                        tools=openai_tools,
                        max_tokens=MAX_TOKENS,
                        timeout=120.0,
                    )
                    break
                except Exception as e:
                    err_str = str(e)
                    if any(k in err_str.lower() for k in ("prompt is too long", "context length", "max_tokens", "token limit", "request too large")):
                        before = len(self._messages)
                        if before > 6:
                            self._compact_messages(on_text)
                            if len(self._messages) < before:
                                break
                        return f"API Error: {e}"
                    if _should_retry(err_str) and attempt < MAX_API_RETRIES:
                        delay = _backoff_delay(attempt)
                        if on_text:
                            on_text(f"\n[API error, retrying in {delay:.1f}s... ({attempt+1}/{MAX_API_RETRIES})]\n")
                        time.sleep(delay)
                        continue
                    return f"API Error: {e}"
            if response is None:
                continue

            # Track tokens
            if hasattr(response, "usage") and response.usage:
                self._total_input_tokens += getattr(response.usage, "prompt_tokens", 0)
                self._total_output_tokens += getattr(response.usage, "completion_tokens", 0)

            choice = response.choices[0]

            # Detect max_tokens truncation — retry with resume prompt
            if getattr(choice, "finish_reason", None) == "length":
                text_so_far = choice.message.content or ""
                if text_so_far.strip():
                    self._messages.append({"role": "assistant", "content": text_so_far})
                    self._messages.append({"role": "user", "content": "[Your response was cut off. Resume directly from where you stopped — do not repeat anything.]"})
                    if on_text:
                        on_text(text_so_far)
                    continue
            msg = choice.message

            if msg.tool_calls:
                # Serialize to plain dict so session save (JSON) works
                msg_dict = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                }
                self._messages.append(msg_dict)

                # Emit text if any
                if msg.content and msg.content.strip() and on_text:
                    on_text(msg.content)

                self._set_state("tool_exec")
                try:
                    for tc in msg.tool_calls:
                        fn = tc.function
                        try:
                            args = json.loads(fn.arguments) if fn.arguments else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                            result = f"ERROR: Malformed tool arguments: {fn.arguments[:200]}"
                            if on_tool_end:
                                on_tool_end(fn.name, result)
                            self._messages.append({
                                "role": "tool", "tool_call_id": tc.id, "content": result,
                            })
                            continue
                        self._emit("pre_tool", name=fn.name, input=args)
                        if on_tool_start:
                            on_tool_start(fn.name, args)
                        result = execute_tool(fn.name, args)
                        self._emit("post_tool", name=fn.name, result=result)
                        if on_tool_end:
                            on_tool_end(fn.name, result)
                        if len(result) > self.MAX_TOOL_RESULT:
                            result = result[:self.MAX_TOOL_RESULT] + "\n... (truncated)"
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
                except BaseException:
                    answered_ids = {m["tool_call_id"] for m in self._messages if isinstance(m, dict) and m.get("role") == "tool"}
                    for tc in msg.tool_calls:
                        if tc.id not in answered_ids:
                            self._messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": "Cancelled by user.",
                            })
                    raise
            else:
                text = msg.content or ""
                if not text.strip():
                    text = "[TokioAI stopped without a response. Type your message to continue, or 'reset' to start over.]"
                self._messages.append({"role": "assistant", "content": text})
                self._set_state("idle")
                return text

        self._set_state("idle")
        return f"Max tool turns reached ({effective_limit} rounds). You can continue the conversation or type 'reset' to start fresh."

    # ── OpenAI Streaming ────────────────────────────

    def _chat_openai_stream(self, user_input, on_tool_start, on_tool_end, on_text, on_token) -> str:
        """OpenAI chat with streaming — tokens emitted as they arrive."""
        self._compact_messages(on_text)
        # After compaction, prepend active task context to help LLM orient
        if self._compaction_count > 0 and len(self._messages) <= 4:
            try:
                _task_check = _load_tasks()
                _active_check = [t for t in _task_check if t.get("status") != "done"]
                if _active_check:
                    _ctx_lines = ["[AUTO-CONTEXT: Active tasks after compaction]"]
                    for _tc in _active_check:
                        _tcl = "- [%s] %s" % (_tc.get("status", "?"), _tc.get("task", "?"))
                        if _tc.get("current_step"):
                            _tcl += " | Current step: " + _tc["current_step"]
                        _ctx_lines.append(_tcl)
                    user_input = "\n".join(_ctx_lines) + "\n\nUser message: " + user_input
            except Exception:
                pass
        self._messages.append({"role": "user", "content": user_input})
        openai_tools = _tools_to_openai(TOOLS)
        effective_limit = self._max_rounds if self._max_rounds > 0 else 999999

        for turn in range(effective_limit):
            self._fix_orphaned_tool_use()
            stream_obj = None
            for attempt in range(MAX_API_RETRIES + 1):
                try:
                    msgs = [{"role": "system", "content": _build_system_prompt()}] + self._messages
                    stream_obj = self._client.chat.completions.create(
                        model=self._model,
                        messages=msgs,
                        tools=openai_tools,
                        max_tokens=MAX_TOKENS,
                        timeout=120.0,
                        stream=True,
                    )
                    break
                except Exception as e:
                    err_str = str(e)
                    if any(k in err_str.lower() for k in ("prompt is too long", "context length", "max_tokens", "token limit", "request too large")):
                        before = len(self._messages)
                        if before > 6:
                            self._compact_messages(on_text)
                            if len(self._messages) < before:
                                break
                        return f"API Error: {e}"
                    if _should_retry(err_str) and attempt < MAX_API_RETRIES:
                        delay = _backoff_delay(attempt)
                        if on_text:
                            on_text(f"\n[API error, retrying in {delay:.1f}s... ({attempt+1}/{MAX_API_RETRIES})]\n")
                        time.sleep(delay)
                        continue
                    return f"API Error: {e}"
            if stream_obj is None:
                continue

            # Consume stream
            text_chunks = []
            tool_calls_acc = {}  # id -> {name, arguments}
            finish_reason = None

            try:
                for chunk in stream_obj:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    # Text tokens
                    if delta.content:
                        text_chunks.append(delta.content)
                        on_token(delta.content)

                    # Tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.id or "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc_delta.id:
                                tool_calls_acc[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_acc[idx]["name"] = tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                    # Usage (some providers send it in the last chunk)
                    if hasattr(chunk, "usage") and chunk.usage:
                        self._total_input_tokens += getattr(chunk.usage, "prompt_tokens", 0)
                        self._total_output_tokens += getattr(chunk.usage, "completion_tokens", 0)

            except KeyboardInterrupt:
                partial = "".join(text_chunks)
                if partial:
                    self._messages.append({"role": "assistant", "content": partial})
                raise

            full_text = "".join(text_chunks)

            # Max tokens truncation
            if finish_reason == "length" and full_text.strip():
                self._messages.append({"role": "assistant", "content": full_text})
                self._messages.append({"role": "user", "content": "[Your response was cut off. Resume directly from where you stopped — do not repeat anything.]"})
                continue

            if tool_calls_acc:
                # Build serialized message
                tc_list = []
                for idx in sorted(tool_calls_acc):
                    tc = tool_calls_acc[idx]
                    tc_list.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })
                msg_dict = {
                    "role": "assistant",
                    "content": full_text or "",
                    "tool_calls": tc_list,
                }
                self._messages.append(msg_dict)

                if full_text.strip() and on_text:
                    on_text(full_text)

                # Execute tools
                try:
                    for tc in tc_list:
                        fn_name = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                            result = f"ERROR: Malformed tool arguments"
                            if on_tool_end:
                                on_tool_end(fn_name, result)
                            self._messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                            continue
                        if on_tool_start:
                            on_tool_start(fn_name, args)
                        result = execute_tool(fn_name, args)
                        if on_tool_end:
                            on_tool_end(fn_name, result)
                        if len(result) > self.MAX_TOOL_RESULT:
                            result = result[:self.MAX_TOOL_RESULT] + "\n... (truncated)"
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                except BaseException:
                    answered_ids = {m["tool_call_id"] for m in self._messages if isinstance(m, dict) and m.get("role") == "tool"}
                    for tc in tc_list:
                        if tc["id"] not in answered_ids:
                            self._messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "Cancelled by user."})
                    raise
            else:
                if not full_text.strip():
                    full_text = "[TokioAI stopped without a response. Type your message to continue, or 'reset' to start over.]"
                    on_token(full_text)
                self._messages.append({"role": "assistant", "content": full_text})
                return full_text

        return f"Max tool turns reached ({effective_limit} rounds). You can continue the conversation or type 'reset' to start fresh."

    # ── Gemini (Google AI — API key) ──────────────────

    def _chat_gemini(self, user_input, on_tool_start, on_tool_end, on_text) -> str:
        """Gemini chat with function calling via google-genai SDK."""
        # Simple Gemini history truncation — keep last 30 entries
        if len(self._gemini_history) > 40:
            self._gemini_history = self._gemini_history[-30:]
            if on_text:
                on_text("\n⚡ Gemini context trimmed (keeping last 30 turns)\n")
        try:
            from google.genai import types

            # Build tool declarations
            fn_decls = []
            for tool in TOOLS:
                props = {}
                required = tool["input_schema"].get("required", [])
                for pname, pdef in tool["input_schema"].get("properties", {}).items():
                    ptype = pdef.get("type", "string").upper()
                    props[pname] = types.Schema(
                        type=ptype,
                        description=pdef.get("description", ""),
                    )
                fn_decls.append(types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=types.Schema(
                        type="OBJECT",
                        properties=props,
                        required=required,
                    ),
                ))

            gemini_tools = [types.Tool(function_declarations=fn_decls)]

            # Append new user message to persistent history
            self._gemini_history.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_input)],
            ))
            # Work with a copy so tool-call turns are included
            contents = list(self._gemini_history)

            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(),
                tools=gemini_tools,
                max_output_tokens=MAX_TOKENS,
            )

            effective_limit = self._max_rounds if self._max_rounds > 0 else 999999
            for turn in range(effective_limit):
                self._set_state("thinking")
                self._emit("pre_api", provider="gemini", turn=turn)
                # API call with exponential backoff
                response = None
                for attempt in range(MAX_API_RETRIES + 1):
                    try:
                        response = self._client.models.generate_content(
                            model=self._model,
                            contents=contents,
                            config=config,
                        )
                        break
                    except Exception as e:
                        if _should_retry(str(e)) and attempt < MAX_API_RETRIES:
                            delay = _backoff_delay(attempt)
                            if on_text:
                                on_text(f"\n[Gemini error, retrying in {delay:.1f}s... ({attempt+1}/{MAX_API_RETRIES})]\n")
                            time.sleep(delay)
                            continue
                        return f"Gemini API Error: {e}"
                if response is None:
                    return "Gemini API Error: all retries failed"

                # Track tokens
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    self._total_input_tokens += getattr(response.usage_metadata, "prompt_token_count", 0)
                    self._total_output_tokens += getattr(response.usage_metadata, "candidates_token_count", 0)

                # Guard against empty candidates (safety filters, etc.)
                if not response.candidates:
                    return "[Gemini returned no response (possibly filtered). Try rephrasing or use a different model.]"

                # Check for function calls
                fn_calls = []
                text_parts = []
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fn_calls.append(part.function_call)
                    elif hasattr(part, "text") and part.text:
                        text_parts.append(part.text)

                if text_parts and on_text:
                    on_text("\n".join(text_parts))

                if not fn_calls:
                    # Save assistant response to persistent history
                    self._gemini_history.append(response.candidates[0].content)
                    final_text = "\n".join(text_parts)
                    if not final_text.strip():
                        final_text = "[TokioAI stopped without a response. Type your message to continue, or 'reset' to start over.]"
                    self._set_state("idle")
                    return final_text

                # Execute function calls
                self._set_state("tool_exec")
                contents.append(response.candidates[0].content)
                fn_response_parts = []
                for fc in fn_calls:
                    args = dict(fc.args) if fc.args else {}
                    self._emit("pre_tool", name=fc.name, input=args)
                    if on_tool_start:
                        on_tool_start(fc.name, args)
                    result = execute_tool(fc.name, args)
                    self._emit("post_tool", name=fc.name, result=result)
                    if on_tool_end:
                        on_tool_end(fc.name, result)
                    fn_response_parts.append(types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result},
                    ))

                contents.append(types.Content(
                    role="user",
                    parts=fn_response_parts,
                ))

            # Save final state of conversation to persistent history
            # (contents has all tool-call turns from this round)
            self._gemini_history = contents
            self._set_state("idle")
            return f"Max tool turns reached ({effective_limit} rounds). You can continue the conversation or type 'reset' to start fresh."

        except ImportError:
            return "ERROR: google-genai not installed. Run: pip install google-genai"
        except Exception as e:
            return f"Gemini API Error: {e}"

    def reset(self):
        """Clear conversation history."""
        self._messages = []
        self._gemini_history = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
