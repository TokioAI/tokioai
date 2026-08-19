# TokioAI

### Intelligence for Evolution

> *"Don't build what the model already knows how to do. Build what the model cannot do alone."*

We build autonomous AI agents that act in the real world. Not chatbots -- operators.
The model is the brain. We build the body.

**[tokioia.com](https://tokioia.com)** | **[contact@tokioia.com](mailto:contact@tokioia.com)**

---

## Mission

**Protect** -- Autonomous cybersecurity: threat detection, incident response, WAF, SOAR, red team ops.

**Heal** -- AI-powered health monitoring: vitals today, metabolic profiles tomorrow. AI that helps humanity cure every disease.

**Explore** -- Use AI to discover new physics, decode quantum mechanics, and help humanity reach new worlds.

---

## Philosophy

- **Zero frameworks.** No LangChain, no CrewAI. Raw API calls, direct tool execution, total control. ~1,000 lines of engine.
- **Agents, not assistants.** An agent runs nmap, finds the vuln, writes the patch, deploys it, and tells you when it's done.
- **Exploit the model.** The LLM already reasons, plans, writes code, and sees images. Give it tools and let it think.

---

## TokioAI CLI

**Autonomous AI Agent for the terminal.** Cybersecurity, DevOps, Engineering, Hacking, Robotics.

7 providers, 38+ tools, dual-model router.

### Quick Install

```bash
# Linux / macOS / WSL
git clone https://github.com/TokioAI/tokioai.git
cd tokioai && ./setup.sh

# Windows
git clone https://github.com/TokioAI/tokioai.git
cd tokioai && setup.bat

# Manual (Python 3.10+)
pip install -e . && tokioai --setup
```

### Setup

```
$ tokioai --setup

  Choose your AI provider:
    1) Claude via Vertex AI     4) Google Gemini (free tier!)
    2) Claude via API key       5) Kimi K2 (Moonshot AI)
    3) OpenAI GPT               6) OpenRouter (200+ models)
    7) Ollama (local, free)     8) Multi-provider

  Select [1-8]: 6
  OpenRouter API key: sk-or-...
  Model [dual]: dual
  Config saved to ~/.tokioai/.env
```

### Usage

```bash
tokio                                    # interactive mode
tokio "scan my network for open ports"   # single query
tokio -m dual                            # dual-model auto-router
tokio -m gemini31 "explain this CVE"     # specific model
tokio -u "deploy the full stack"         # unlimited tool rounds
```

### Dual-Model Router

Auto-routes between cheap and smart models, saving ~60% on costs.

| Model | Role | Cost (per 1M tok) | Used For |
|-------|------|--------------------|----------|
| **K2.7-code** | Primary (70%) | $0.71 / $3.50 | Code, commands, tools, direct tasks |
| **K3** | Secondary (30%) | $3.00 / $15.00 | Architecture, security analysis, reasoning |

```bash
tokio -m dual          # activate at startup
# or at runtime:
model dual             # switch to dual router
dual                   # show router stats
threshold 40           # adjust routing (lower = more K3)
force k2.7             # force cheap model
force auto             # resume auto-routing
```

### Switch Models at Runtime

```
model opus      -> Claude Opus 4          model k27    -> Kimi K2.7-code
model sonnet    -> Claude Sonnet 4        model k3     -> Kimi K3
model gemini31  -> Gemini 3.1 Pro         model dual   -> K2.7 + K3 auto
model flash     -> Gemini 2.5 Flash       model gpt4o  -> GPT-4o
model kimi      -> Kimi K2                model llama  -> Llama 3.1 (local)
models                                    -> list all available
```

### Slash Commands

| Command | Description | Command | Description |
|---------|-------------|---------|-------------|
| `/status` | System status | `/waf` | WAF dashboard |
| `/health` | Smartwatch vitals | `/entity` | AI vision status |
| `/see` | Camera feed | `/wifi` | WiFi defense |
| `/picar` | PiCar-X robot | `/gcp` | GCP containers |
| `/sitrep` | Situation report | `/threats` | Active threats |
| `/logs` | Entity logs | `/compact` | Compact conversation |

### Architecture

```
~/.tokioai/.env           <- credentials (created by --setup)
tokioai_cli/
  interactive.py          <- UI, banner, slash commands, model switch
  ops.py                  <- LLM engine, tool execution, 6 providers
  router.py               <- dual-model router (complexity classifier)
```

### Features

- 38+ tools -- bash, SSH, Docker, security scanning, IoT, robots, WAF, DNS
- Dual-model router with cost savings tracking
- Local safety layer -- PII/secrets redaction before any LLM API call
- Tab completion, multi-line input, session persistence
- Credential masking -- API keys never shown in output
- Auto-provider detection -- uses whatever credentials are available
- Works on any machine after setup (zero hardcoded paths)

---

## Security & Privacy

TokioAI runs a **local safety layer** (`tokioai_cli/safety.py`) that scans **every outgoing prompt and the system prompt** for common secrets and PII before it reaches any LLM provider — including OpenRouter, Kimi/Moonshot, Gemini, OpenAI and Claude. Detected values are replaced with stable placeholders such as `[REDACTED_API_KEY_1]`. The original values never leave your machine.

Detected categories include:
- API keys (OpenAI `sk-...`, Anthropic `sk-ant-...`, OpenRouter `sk-or-v1-...`, Google `AIza...`, GitHub PATs, AWS keys)
- Passwords and database connection strings
- Private keys (PEM, OpenSSH, RSA, EC)
- Emails, phone numbers, private IPv4 addresses
- Credit cards and national IDs

Commands:

```
safety              # show status and last redaction summary
safety allow <val>  # bypass redaction for a known-safe value
```

Environment variables:

- `TOKIO_SAFETY_PARANOID=1` -- raise detection sensitivity
- `TOKIO_SAFETY_BLOCK=api_key,password` -- block the request if any value in those categories is detected

This is **defence in depth**, not a guarantee. Always review code before pasting it anywhere, and rotate leaked credentials immediately.

---

## Other Projects

| Repo | Description |
|------|-------------|
| [tokioai-v1.8](https://github.com/TokioAI/tokioai-v1.8) | Autonomous AI Agent Framework -- Connect Claude, GPT, or Gemini to your infrastructure. 30+ tools: servers, Docker, databases, IoT, drones, WAF, cloud. Three interfaces: CLI, REST API, Telegram Bot. |
| [tokioai-website](https://github.com/TokioAI/tokioai-website) | TokioAI Security Research Inc. -- Official website. [tokioia.com](https://tokioia.com) |

---

## License

MIT
