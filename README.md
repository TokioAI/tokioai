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

7 providers, 38+ tools, dual-model router, local safety layer.

### Quick Install

```bash
# Linux / macOS / WSL
git clone https://github.com/TokioAI/tokioai.git
cd tokioai && ./setup.sh

# Windows
git clone https://github.com/TokioAI/tokioai.git
cd tokioai && setup.bat

# Manual (Python 3.10+)
# IMPORTANT: install at least one provider extra:
pip install -e ".[openai]"     # Kimi / OpenRouter / OpenAI
pip install -e ".[gemini]"     # Google Gemini
pip install -e ".[claude]"     # Anthropic Claude
pip install -e ".[all]"        # all providers + SSH
tokioai --setup
```

### Setup (3 steps)

**1. Install:**
```bash
git clone https://github.com/TokioAI/tokioai.git && cd tokioai
pip install -e ".[openai]"   # or .[gemini], .[claude], .[all]
```

**2. Configure:**
```bash
tokioai --setup
# Or copy and edit:
cp tokioai_cli/.env.example ~/.tokioai/.env
```

**3. Run:**
```bash
tokio
```

> **Note:** `pip install -e .` (without extras) does NOT install any AI provider SDK.
> You need at least one: `.[openai]`, `.[gemini]`, `.[claude]`, or `.[all]`.
> The setup scripts handle this automatically.

### Configuration

TokioAI reads config from `~/.tokioai/.env` (global) or `./.env` (project-local, higher priority).

See **[`tokioai_cli/.env.example`](tokioai_cli/.env.example)** for all options with documentation.

**Minimal .env for each provider:**

```bash
# Kimi (best value -- dual mode saves ~60% on costs)
TOKIOAI_PROVIDER=kimi
TOKIOAI_MODEL=dual
KIMI_API_KEY=sk-your-key-here

# Gemini (FREE tier -- 1500 req/day)
TOKIOAI_PROVIDER=gemini
TOKIOAI_MODEL=flash
GEMINI_API_KEY=AIza-your-key-here

# Claude (most capable)
TOKIOAI_PROVIDER=anthropic
TOKIOAI_MODEL=opus
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# OpenRouter (200+ models, one key)
TOKIOAI_PROVIDER=openrouter
TOKIOAI_MODEL=or-claude
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Ollama (local, free)
TOKIOAI_PROVIDER=ollama
TOKIOAI_MODEL=qwen
```

### Usage

```bash
tokio                                    # interactive mode
tokio "scan my network for open ports"   # single query
tokio -m dual                            # dual-model auto-router
tokio -m gemini31 "explain this CVE"     # specific model
tokio -u "deploy the full stack"         # unlimited tool rounds
```

**In-session commands:**
```
help          Show all commands and shortcuts
models        List all available model aliases
model <name>  Switch model (opus, sonnet, k3, dual, flash, etc.)
stats         Token usage, costs, per-model breakdown
dual          Show router stats (in dual mode)
config        Show current configuration
compact       Manually compact old messages
reset         Start fresh conversation
safety        Show safety layer status
```

### Dual-Model Router

Auto-routes between cheap and smart models. Saves ~60% on API costs.

| Model | Role | Cost (per 1M tok) | Used For |
|-------|------|--------------------|----------|
| **K2.7-code** | Primary (~70%) | $0.71 / $3.50 | Code, commands, tools, quick tasks |
| **K3** | Secondary (~30%) | $3.00 / $15.00 | Architecture, security, reasoning |

```bash
tokio -m dual          # activate at startup
# In session:
model dual             # switch to dual mode
dual                   # show router stats & recent decisions
threshold 40           # adjust (lower = more K3 usage)
force k2.7             # force cheap model
force k3               # force smart model
force auto             # resume auto-routing
```

The router analyzes each message and scores complexity (0-100). Score >= threshold goes to K3.
Simple commands, git ops, file edits -> K2.7-code (cheap). Architecture, security analysis, reasoning -> K3 (smart).

### Switch Models at Runtime

```
model opus      -> Claude Opus 4          model k27    -> Kimi K2.7-code
model sonnet    -> Claude Sonnet 4        model k3     -> Kimi K3
model gemini31  -> Gemini 3.1 Pro         model dual   -> K2.7 + K3 auto
model flash     -> Gemini 2.5 Flash       model gpt4o  -> GPT-4o
model kimi      -> Kimi K2                model llama  -> Llama 3.1 (local)
models                                    -> list all available
```

You can set up multiple provider keys and switch between them seamlessly.

### Slash Commands (instant, no LLM)

| Command | Description | Command | Description |
|---------|-------------|---------|-------------|
| `/status` | System overview | `/waf` | WAF attack stats |
| `/health` | Smartwatch vitals | `/entity` | AI vision status |
| `/see` | Camera snapshot | `/wifi` | WiFi defense |
| `/picar` | PiCar-X robot | `/gcp` | GCP containers |
| `/sitrep` | Full sit report | `/threats` | Active threats |
| `/logs` | Entity logs | `/diff` | Git diff |

### Cost Optimization

TokioAI optimizes costs at every level:

1. **Dual-model router** -- routes ~70% of requests to the cheaper model
2. **Smart compaction** -- uses Gemini Flash (near-free) to summarize old context, not your expensive model
3. **Memory optimizer** -- only sends recent/relevant memory entries, archives old ones
4. **Token tracking** -- per-model cost breakdown in `stats`
5. **Context limits** -- auto-compacts at 40k tokens, keeps last 10 messages

### Architecture

```
~/.tokioai/
  .env                    <- credentials (from --setup)
  memory.md               <- persistent memory across sessions
  tasks.json              <- task tracker for continuity

tokioai_cli/
  interactive.py          <- UI: banner, commands, streaming, markdown renderer
  ops.py                  <- LLM engine: tool execution, 7 providers, compaction
  router.py               <- dual-model router (complexity classifier)
  safety.py               <- local PII/secrets sanitization layer
  security_config.py      <- provider validation, key audit, security policies
  memory_optimizer.py     <- smart context compression (60-80% token reduction)
  .env.example            <- fully documented config template
```

---

## Security & Privacy

TokioAI runs a **local safety layer** (`safety.py`) that scans **every outgoing message** for secrets and PII **before** it reaches any LLM API. Detected values are replaced with stable placeholders. The original values never leave your machine.

**Detected categories:**
- API keys (OpenAI, Anthropic, OpenRouter, Google, GitHub PATs, AWS, HuggingFace, Stripe, PyPI)
- Passwords and database connection strings
- Private keys (PEM, OpenSSH, RSA, EC, DSA)
- JWT tokens, Bearer tokens
- Emails, phone numbers, private IPv4 addresses
- Credit cards and national IDs

**Provider security** (`security_config.py`):
- API key prefix validation per provider
- Key whitespace/length sanity checks
- OpenRouter proxy detection (prevents accidental key leakage)
- Provider lock (`TOKIO_PROVIDER_LOCK`) for shared environments
- Audit log at `~/.tokioai/security.log`

**Commands:**
```
safety              # show status and last redaction summary
safety allow <val>  # bypass redaction for a known-safe value
```

**Environment variables:**
```bash
TOKIO_SAFETY_PARANOID=1                    # raise detection sensitivity
TOKIO_SAFETY_BLOCK=api_key,password        # block if these categories found
TOKIO_SECURITY_STRICT=1                    # reject ambiguous configs
TOKIO_PROVIDER_LOCK=kimi                   # lock to one provider
```

This is **defence in depth**, not a guarantee. Always review code before pasting, and rotate leaked credentials immediately.

---

## Other Projects

| Repo | Description |
|------|-------------|
| [tokioai-v1.8](https://github.com/TokioAI/tokioai-v1.8) | Autonomous AI Agent Framework -- 30+ tools, CLI + REST API + Telegram Bot |
| [tokioai-website](https://github.com/TokioAI/tokioai-website) | [tokioia.com](https://tokioia.com) |

---

## License

MIT
