# TokioAI

### Intelligence for Evolution

> *"Don't build what the model already knows how to do. Build what the model cannot do alone."*

We build autonomous AI agents that act in the real world. Not chatbots -- operators.
The model is the brain. We build the body.

**[tokioia.com](https://tokioia.com)** | **[[REDACTED_EMAIL_21]](mailto:[REDACTED_EMAIL_22])**

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

7 providers, 38+ tools, dual-model router, local safety layer, and a persistent autonomous organism mode.

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

---

## Usage

```bash
tokio                                    # interactive mode
tokio "scan my network for open ports"   # single query
tokio -m dual                            # dual-model auto-router
tokio -m gemini31 "explain this CVE"     # specific model
tokio -u "deploy the full stack"         # unlimited tool rounds
tokio --vivo                             # autonomous organism mode (see below)
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

---

## Dual-Model Router

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

---

## Slash Commands (instant, no LLM)

| Command | Description | Command | Description |
|---------|-------------|---------|-------------|
| `/status` | System overview | `/waf` | WAF attack stats |
| `/health` | Smartwatch vitals | `/entity` | AI vision status |
| `/see` | Camera snapshot | `/wifi` | WiFi defense |
| `/picar` | PiCar-X robot | `/gcp` | GCP containers |
| `/sitrep` | Full sit report | `/threats` | Active threats |
| `/logs` | Entity logs | `/diff` | Git diff |

---

## TokioAI Vivo -- Autonomous Organism Mode

**`tokio --vivo`** turns the CLI into a persistent, autonomous agent that runs continuously -- monitoring, reasoning, and acting on your systems without human intervention.

This is not a background daemon. It is the same TokioAI agent you talk to every day, running in an autonomous loop with its own nervous system.

### How It Works

The Vivo mode is built on a **three-gear architecture** designed to minimize token cost while maximizing autonomy:

```
  +-----------------------------------------------------+
  |  GEAR 1: Brainstem (Local Reflexes)                 |
  |  - 0 tokens. Pure Python rules.                     |
  |  - Runs every 2 seconds.                            |
  |  - Checks: CPU, RAM, disk, services, network,       |
  |    logs, robot sensors, GPIO, custom watchdogs.      |
  |  - Handles 95% of routine situations instantly.      |
  +-----------------------------------------------------+
                          |
                   anomaly or timer
                          |
  +-----------------------------------------------------+
  |  GEAR 2: Cortex Light (Cheap LLM)                   |
  |  - ~$0.00005 per call.                              |
  |  - Runs every 5 minutes or on anomaly.              |
  |  - Reviews world model, assesses health, decides    |
  |    if anything needs attention.                      |
  |  - Can trigger Gear 3 for novel situations.          |
  +-----------------------------------------------------+
                          |
                  novel or critical
                          |
  +-----------------------------------------------------+
  |  GEAR 3: Cortex Deep (Expensive LLM)                |
  |  - ~$0.005-0.02 per call.                           |
  |  - Only for novel situations, complex reasoning,    |
  |    or when Gear 2 escalates.                         |
  |  - Plans multi-step solutions, writes new rules.    |
  +-----------------------------------------------------+
```

### Key Benefits

**1. Near-zero operating cost**
- Gear 1 (local rules) handles 95% of events -- zero tokens consumed.
- Gear 2 uses a cheap 8B model -- fractions of a cent per call.
- Gear 3 only fires on genuine anomalies -- maybe 2-5 times per day.
- A healthy system running 24/7 costs **cents per day**, not dollars.

**2. Learns and adapts**
- World model is persistent across restarts (`~/.tokioai/vivo/memory.json`).
- Gear 3 can write new local rules that Gear 1 executes from then on.
- The system gets smarter over time without retraining.

**3. Graduated autonomy**
- **Level 0 (Simulation)**: Observes and logs. Nothing executed. Perfect for testing.
- **Level 1 (Assisted)**: Alerts you before any destructive action. You approve.
- **Level 2 (Trusted)**: Executes only whitelisted destructive commands (restart services, reboot, etc.).
- **Level 3 (Full)**: Full autonomy. Use with extreme caution.

**4. Safety by design**
- Kill switch: `touch ~/.tokioai/vivo/STOP` or `tokio --vivo-stop` halts everything.
- Blocked commands list: `rm -rf /`, fork bombs, `dd`, `mkfs` -- never executed.
- Rate limits: max actions per hour, max destructive per hour.
- Token guard: hard budget limits per hour/session/day.
- Dry-run by default: you must explicitly pass `--no-dry-run` to execute.

**5. Full observability**
- Real-time dashboard at `~/.tokioai/vivo/dashboard.html`.
- All actions logged to `~/.tokioai/vivo/actions.log` (JSONL).
- Metrics persisted to `~/.tokioai/vivo/metrics.jsonl`.
- CLI reports at configurable intervals.

### Quick Start (Vivo)

```bash
# Check status
tokio --vivo-status

# Simulation mode (safe, dry-run)
tokio --vivo --objective "keep my server healthy" --autonomy 0

# Assisted mode (asks before destructive actions)
tokio --vivo --objective "keep my server healthy" --autonomy 1 --no-dry-run

# Trusted mode (auto-executes whitelisted commands)
tokio --vivo --objective "monitor the robot and restart if stuck" --autonomy 2 --no-dry-run

# Stop
tokio --vivo-stop
```

### Vivo Options

| Flag | Default | Description |
|------|---------|-------------|
| `--objective TEXT` | "keep system healthy" | High-level mission statement |
| `--autonomy {0,1,2,3}` | 1 | Autonomy level |
| `--dry-run` / `--no-dry-run` | dry-run | Simulate or execute |
| `--budget-hour USD` | 0.50 | Hourly budget limit |
| `--budget-session USD` | 10.00 | Session budget limit |
| `--gear2-model MODEL` | llama-3.1-8b-instruct | Cheap model for periodic review |
| `--gear3-model MODEL` | kimi-k3 | Expensive model for deep reasoning |
| `--tick S` | 2 | Brainstem loop interval (seconds) |
| `--cortex-interval S` | 300 | Gear 2 review interval (seconds) |
| `--report-every S` | 60 | CLI report interval (seconds) |

### Vivo Data

All state persists in `~/.tokioai/vivo/`:

```
~/.tokioai/vivo/
  config.yaml       # Configuration
  memory.json       # World model (objects, events, health, learned rules)
  token_guard.json  # Token spend tracking
  actions.log       # All actions executed (JSONL)
  metrics.jsonl     # Periodic metrics
  state.yaml        # Runtime state
  STOP              # Kill switch (create this file to halt)
  vivo.pid          # PID file for the running process
```

### Use Cases

- **Server watchdog**: Monitor CPU, RAM, disk, services. Restart what dies. Alert on anomalies.
- **Robot guardian**: Watch PiCar-X sensors, detect stuck states, auto-recover navigation.
- **Security patrol**: Check auth logs, detect brute force, auto-ban IPs, monitor WAF.
- **DevOps sentinel**: Watch CI/CD pipelines, container health, auto-rollback on failure.
- **Smart home brain**: Monitor IoT sensors, adjust based on rules, learn patterns over time.

### Architecture (Vivo)

```
tokioai_cli/vivo/
  config.py          # Configuration and paths
  token_guard.py     # Budget and cost tracking
  safety.py          # Whitelist, kill switch, rate limits
  world_memory.py    # Persistent world model
  watchdogs.py       # Local sensors (0 tokens)
  brainstem.py       # Reflex rules engine
  cortex.py          # Gear 2/3 reasoning
  llm_client.py      # LLM client (OpenRouter/direct)
  action_executor.py # Action execution with safety
  scheduler.py       # Periodic tasks
  vivo_loop.py       # Main loop
  cli_plugin.py      # CLI integration
  templates/
    dashboard.html   # Static dashboard
    dashboard_ws.html# WebSocket live dashboard
```

---

## Cost Optimization

TokioAI optimizes costs at every level:

1. **Dual-model router** -- routes ~70% of requests to the cheaper model
2. **Smart compaction** -- uses Gemini Flash (near-free) to summarize old context, not your expensive model
3. **Memory optimizer** -- only sends recent/relevant memory entries, archives old ones (60-80% token reduction)
4. **Token tracking** -- per-model cost breakdown in `stats`
5. **Context limits** -- auto-compacts at 40k tokens, keeps last 10 messages
6. **Vivo three-gear system** -- 95% of autonomous operation uses zero tokens

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
- Audit log at `~/.tokioai/security_audit.log`

**In-session:**
```
safety          Show safety layer status and redaction stats
safety test     Test the safety layer with sample data
security        Show security audit report
```

---

## Architecture

```
~/.tokioai/
  .env                    <- credentials (from --setup)
  memory.md               <- persistent memory across sessions
  tasks.json              <- task tracker for continuity
  vivo/                   <- autonomous organism state
  security_audit.log      <- security event log

tokioai_cli/
  interactive.py          <- UI: banner, commands, streaming, markdown renderer
  ops.py                  <- LLM engine: tool execution, 7 providers, compaction
  router.py               <- dual-model router (complexity classifier)
  safety.py               <- local PII/secrets sanitization layer
  security_config.py      <- provider validation, key audit, security policies
  memory_optimizer.py     <- smart context compression (60-80% token reduction)
  .env.example            <- fully documented config template
  vivo/                   <- autonomous organism mode (see above)
```

---

## Requirements

- Python 3.10+
- One API key from any supported provider
- Linux, macOS, or WSL

---

## License

[MIT](LICENSE)
