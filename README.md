# TokioAI CLI v5.2

**Autonomous AI Agent for the terminal.** Cybersecurity, DevOps, Engineering, Hacking, Robotics.

Supports **7 providers**: Claude (Vertex AI), Claude (API), OpenAI, Gemini (2.5 + 3.x), Kimi K2 (Moonshot AI), OpenRouter, Ollama.

**NEW in v5.2:** Dual-Model Router — auto-routes between K2.7-code (cheap) and K3 (smart), saving ~60% on costs.

## Quick Install

### Linux / macOS / WSL
```bash
git clone https://github.com/daletoniris/tokioai.git
cd tokioai
./setup.sh
```

### Windows
```cmd
git clone https://github.com/daletoniris/tokioai.git
cd tokioai
setup.bat
```

### Manual (any OS with Python 3.10+)
```bash
pip install -e .
tokioai --setup
```

## Setup Wizard

Run `tokioai --setup` to configure your provider and credentials:

```
$ tokioai --setup

======================================================
  TokioAI CLI v5.2 — Setup Wizard
======================================================

Choose your AI provider:

  1) Claude via Vertex AI  (GCP service account)
  2) Claude via API key    (console.anthropic.com)
  3) OpenAI GPT            (platform.openai.com)
  4) Google Gemini          (aistudio.google.com — free tier!)
  5) Kimi K2                 (platform.moonshot.cn — latest Chinese model)
  6) OpenRouter             (openrouter.ai — 200+ models)
  7) Ollama (local)         (free, runs on your machine)
  8) Multi-provider         (configure multiple, switch at runtime)

  Select [1-7]: 6
  OpenRouter API key: sk-or-...
  Model [dual]: dual

  ✓ Config saved to ~/.tokioai/.env
```

## Usage

```bash
# Interactive mode (recommended)
tokio

# Single query
tokio "scan my network for open ports"

# Dual-model mode (auto K2.7 + K3)
tokio -m dual

# With specific model
tokio -m gemini31 "explain this CVE"

# Unlimited tool rounds
tokio -u "deploy the full stack"
```

## Dual-Model Router (NEW)

The **dual-model router** automatically picks the best model for each request:

| Model | Role | Cost | When Used |
|-------|------|------|-----------|
| **Kimi K2.7-code** | Primary (70%) | $0.71/$3.50 per 1M tok | Code, commands, tools, direct tasks |
| **Kimi K3** | Secondary (30%) | $3.00/$15.00 per 1M tok | Architecture, security analysis, reasoning |

### How It Works

1. You type a message
2. The classifier analyzes complexity (keywords, patterns, length, context)
3. Simple tasks go to K2.7-code (fast, cheap)
4. Complex reasoning goes to K3 (slower, smarter)
5. Each response shows `[K2.7]` or `[K3]` badge so you know which model answered

### Activate

```bash
# At startup
tokio -m dual

# Or switch at runtime
❯ model dual
✓ Switched to kimi-k2.7-code + kimi-k3 (DUAL ROUTER)
```

### Control the Router

```
❯ dual            # Show router stats and recent decisions
❯ threshold 40    # Lower = more K3, higher = more K2.7 (default: 50)
❯ force k2.7      # Force all requests to K2.7-code
❯ force k3        # Force all requests to K3
❯ force auto      # Resume auto-routing
❯ stats           # Full stats with per-model breakdown and savings
```

### Example Output

```
  [K2.7] ⏱ 2.3s │ 🔧 1 tools │ 📊 1,234 in / 567 out │ 💰 ~$0.0023

  [K3] ⏱ 8.1s │ 📊 3,456 in / 1,234 out │ 💰 ~$0.0289
```

### Savings

Typical savings: **50-70%** vs using K3 for everything. The router only escalates to K3 when it detects complex reasoning, architecture design, security analysis, or multi-step planning.

## Switch Models at Runtime

Inside the CLI, type `model <name>` to switch:

```
❯ model opus       → Claude Opus 4 (most capable)
❯ model sonnet     → Claude Sonnet 4 (fast + smart)
❯ model gemini31   → Gemini 3.1 Pro Preview (latest Google)
❯ model flash      → Gemini 2.5 Flash (fast + cheap)
❯ model gpt4o      → GPT-4o
❯ model kimi       → Kimi K2 (Moonshot AI, latest)
❯ model dual       → K2.7-code + K3 auto-router
❯ model k27        → Kimi K2.7-code only
❯ model k3         → Kimi K3 only
❯ model llama      → Llama 3.1 via Ollama (local)
❯ models           → list all available models
```

## All Model Aliases

| Alias | Model | Provider |
|-------|-------|----------|
| `dual` | K2.7-code + K3 (auto) | OpenRouter |
| `k27` | kimi-k2.7-code | OpenRouter |
| `k3` | kimi-k3 | OpenRouter |
| `opus` | claude-opus-4-6 | Vertex AI / Anthropic |
| `sonnet` | claude-sonnet-4-6 | Vertex AI / Anthropic |
| `haiku` | claude-3-5-haiku | Vertex AI / Anthropic |
| `gemini31` | gemini-3.1-pro-preview | Gemini API key |
| `flash3` | gemini-3-flash-preview | Gemini API key |
| `pro` | gemini-2.5-pro | Vertex AI (Gemini SA) |
| `flash` | gemini-2.5-flash | Vertex AI (Gemini SA) |
| `gpt4o` | gpt-4o | OpenAI |
| `o3` | o3 | OpenAI |
| `kimi` | kimi-k2-0711-preview | Kimi (Moonshot AI) |
| `or-claude` | anthropic/claude-sonnet-4 | OpenRouter |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/status` | Full system status |
| `/health` | Health data (smartwatch) |
| `/waf` | WAF dashboard |
| `/entity` | Entity (AI vision) status |
| `/see` | What Entity sees via camera |
| `/wifi` | WiFi defense status |
| `/coffee` | Coffee machine |
| `/ha` | Home Assistant |
| `/picar` | PiCar-X robot status |
| `/logs` | Entity logs with colors |
| `/sitrep` | Full situation report |
| `/threats` | Active threats |
| `/gcp` | GCP containers status |
| `/compact` | Compact conversation |
| `/clear` | Clear screen |

## Features

- **38 tools** — bash, SSH, Docker, security scanning, IoT, robots, WAF, DNS
- **Dual-model router** — auto K2.7-code + K3 with cost savings tracking
- **Tab completion** — commands, paths, models
- **Cost tracking** — per-message and cumulative token costs
- **Session persistence** — SQLite fallback when no PostgreSQL
- **Multi-line input** — end lines with `\`
- **Ctrl+C** — cancels current operation, never breaks terminal
- **Credential masking** — API keys never shown in output
- **Auto-provider detection** — uses whatever credentials are available
- **Zero hardcoded paths** — works on any machine after setup

## Requirements

- Python 3.10+
- At least ONE API key or credential (Gemini free tier is easiest)

## Architecture

```
~/.tokioai/.env          ← credentials & config (created by --setup)
tokioai_cli/
  interactive.py         ← UI, banner, slash commands, model switch
  ops.py                 ← LLM engine, tool execution, 6 providers
  router.py              ← Dual-model router (complexity classifier)
  __init__.py            ← version
  __main__.py            ← python -m entry point
```

## License

MIT
