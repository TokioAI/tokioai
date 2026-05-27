# TokioAI CLI v5.1

**Autonomous AI Agent for the terminal.** Cybersecurity, DevOps, Engineering, Hacking, Robotics.

Supports **6 providers**: Claude (Vertex AI), Claude (API), OpenAI, Gemini (2.5 + 3.x), OpenRouter, Ollama.

## Quick Install

### Linux / macOS / WSL
```bash
git clone https://github.com/your-org/tokioai-cli.git
cd tokioai-cli
./setup.sh
```

### Windows
```cmd
git clone https://github.com/your-org/tokioai-cli.git
cd tokioai-cli
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
  TokioAI CLI v5.1 — Setup Wizard
======================================================

Choose your AI provider:

  1) Claude via Vertex AI  (GCP service account)
  2) Claude via API key    (console.anthropic.com)
  3) OpenAI GPT            (platform.openai.com)
  4) Google Gemini          (aistudio.google.com — free tier!)
  5) OpenRouter             (openrouter.ai — 200+ models)
  6) Ollama (local)         (free, runs on your machine)
  7) Multi-provider         (configure multiple, switch at runtime)

  Select [1-7]: 4
  Gemini API key (AIza...): AIzaSy...
  Model [gemini31]: gemini31

  ✓ Config saved to ~/.tokioai/.env
```

The wizard saves everything to `~/.tokioai/.env`. No need to edit files manually.

## Usage

```bash
# Interactive mode (recommended)
tokio

# Single query
tokio "scan my network for open ports"

# With specific model
tokio -m gemini31 "explain this CVE"

# Unlimited tool rounds
tokio -u "deploy the full stack"
```

## Switch Models at Runtime

Inside the CLI, type `model <name>` to switch:

```
🌀 tokio> model opus       → Claude Opus 4 (most capable)
🌀 tokio> model sonnet     → Claude Sonnet 4 (fast + smart)
🌀 tokio> model gemini31   → Gemini 3.1 Pro Preview (latest Google)
🌀 tokio> model flash      → Gemini 2.5 Flash (fast + cheap)
🌀 tokio> model gpt4o      → GPT-4o
🌀 tokio> model llama      → Llama 3.1 via Ollama (local)
🌀 tokio> models           → list all available models
```

Credentials switch automatically — Claude uses Vertex SA, Gemini 3.x uses API key, etc.

## All Model Aliases

| Alias | Model | Provider |
|-------|-------|----------|
| `opus` | claude-opus-4-6 | Vertex AI / Anthropic |
| `sonnet` | claude-sonnet-4-6 | Vertex AI / Anthropic |
| `haiku` | claude-3-5-haiku | Vertex AI / Anthropic |
| `gemini31` | gemini-3.1-pro-preview | Gemini API key |
| `flash3` | gemini-3-flash-preview | Gemini API key |
| `pro` | gemini-2.5-pro | Vertex AI (Gemini SA) |
| `flash` | gemini-2.5-flash | Vertex AI (Gemini SA) |
| `gpt4o` | gpt-4o | OpenAI |
| `o3` | o3 | OpenAI |
| `llama` | llama3.1:8b | Ollama (local) |
| `deepseek` | deepseek-coder-v2:16b | Ollama (local) |
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
  __init__.py            ← version
  __main__.py            ← python -m entry point
```

## License

MIT
