# TokioAI

### Intelligence for Evolution

> "Don't build what the model already knows how to do. Build what the model cannot do alone."

We build autonomous AI agents that act in the real world. Not chatbots -- operators.
From cybersecurity incident response to health monitoring, from drone ops to exploring the frontiers of physics.
The model is the brain. We build the body.

**[tokioia.com](https://tokioia.com)** | **[contact@tokioia.com](mailto:contact@tokioia.com)**

---

## Mission

We exist to prove that AI can serve humanity without compromising its essence. Three pillars guide everything we build.

**Protect** -- Autonomous cybersecurity that defends infrastructure, detects threats in real-time, and responds to incidents -- from WAF signatures to SOAR playbooks to full red team operations.

**Heal** -- AI-powered health monitoring today: heart rate, blood pressure, SpO2. Tomorrow: cholesterol, blood sugar, metabolic profiles. The goal: AI that helps humanity prevent, diagnose, and cure every disease.

**Explore** -- Push the boundaries of knowledge -- use AI to discover new laws of physics, decode quantum mechanics, understand new dimensions, and help humanity reach worlds we haven't dreamed of yet.

---

## Philosophy

Exploit the native capabilities of the model. Don't reinvent the wheel. The LLM already knows how to reason, plan, write code, and analyze images. Give it tools and let it think.

- **The Model is the Brain** -- The LLM already knows how to reason, plan, write code, analyze images. Don't put chains of rules on top. Don't add frameworks. Give it TOOLS and let it think. 90% of the work is the model. Your engine is the 10% that connects the model to the real world.

- **Radical Minimalism** -- Every line of code must justify its existence. The entire TokioAI engine is ~1,000 lines controlling 100+ tools. Zero external frameworks.

- **The Body, Not the Mind** -- TokioAI is not the intelligence. TokioAI is the BODY. The model is the brain. The engine is the nervous system. The tools are the hands. The CLI/API is the skin. We give a body to the brain and let it act in the world.

- **Against the Dystopia Industry** -- Fear sells. The "AI will destroy us" narrative generates clicks and funding. We choose a different path: build something that proves AI can coexist with human dignity and freedom.

- **Tools, Not Frameworks** -- Each tool is a pure function. No abstract classes, no factories, no dependency injection. The prompt IS the code. The system prompt defines identity, tools, behavior, and memory. The wrapper is disposable -- the value is in the design.

- **Progress is Non-Negotiable** -- In 6 years, AI went from 1 capability to 30+ native capabilities. OCR, speech, vision, code execution, web browsing, tool use -- all absorbed into the model. The speed doubles every year. The explosion is just getting started.

---

## Architecture

~1,000 lines of engine. 100+ tools. 6 LLM providers. 0 external frameworks.

### The Agent Loop: Think -> Act -> Observe -> Learn

1. **THINK** -- The LLM receives system prompt (identity), persistent memory, conversation history, and available tools (native). It DECIDES what to do.
2. **ACT** -- The LLM uses native tool_use: calls tools directly, executes bash, reads files, queries APIs. No regex. No manual parsing. The API provides tool_use blocks.
3. **OBSERVE** -- The engine executes the tool with timeouts, circuit breaker (5 failures = disabled 60s), sync/async transparent handling. Captures output + errors. Returns result to the LLM.
4. **LEARN** -- The LLM receives the result and decides: use another tool? Respond to the user? Save to memory? The loop repeats with NO iteration limit. Full trust in the model.

### The Tool System

- **Registry (~150 lines)** -- Central catalog. Each tool has name, description, category, parameters, and executor. Exports to any provider's native format.
- **Executor (~150 lines)** -- Receives tool_name + args. Async-aware. Timeouts. Circuit breaker: 5 consecutive failures = tool disabled for 60s.
- **Loader (~300 lines)** -- Registers ALL tools. Categories: System, Files, Network, Containers, DB, GCP, Security, IoT. Plugins from external dirs. If a module fails to load, it's skipped -- the agent stays alive.

---

## Capabilities

**Cybersecurity** -- WAF with custom AI-powered signatures. Real-time SOAR incident response. Firewall log analysis + auto-blocking. Vulnerability scanning and assessment. SpyCloud breach intelligence. Defender / EDR integration.

**Health Monitoring** -- Heart rate, blood pressure, SpO2 in real-time. Anomaly detection & health alerts. AI-powered pattern analysis. Wearable sensor integration. Natural language health reports.

**Infrastructure** -- Docker/Podman container management. Multi-cloud: GCP, AWS, Azure. SSH to any server with auto-ops. PostgreSQL queries & management. Self-healing: auto-detects and fixes failures.

**Vision AI & Drones** -- Real-time camera analysis. DJI Tello drone autonomous flight. Object detection & tracking. Aerial reconnaissance with AI. Natural language drone control.

**Smart Home & IoT** -- Home Assistant + Alexa voice control. Smart lights, switches, sensors. Mood-based coffee machine (custom built). Robot vacuum control. Unified control via natural language.

**Self-Evolving Agent** -- Runs autonomously, no human supervision needed. Programs and improves its own code. Self-healing: auto-detects and fixes failures. Multi-LLM: Claude, Gemini, GPT -- adapts in real-time. Sub-agents: spawns parallel workers for complex tasks. 4 interfaces: CLI, REST API, Telegram, Chat Web.

---

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

## Setup

Run `tokioai --setup` to configure your provider and credentials:

```
$ tokioai --setup

  TokioAI CLI — Setup Wizard

  Choose your AI provider:

    1) Claude via Vertex AI    (GCP service account)
    2) Claude via API key      (console.anthropic.com)
    3) OpenAI GPT              (platform.openai.com)
    4) Google Gemini           (aistudio.google.com — free tier!)
    5) Kimi K2                 (platform.moonshot.cn)
    6) OpenRouter              (openrouter.ai — 200+ models)
    7) Ollama (local)          (free, runs on your machine)
    8) Multi-provider          (configure multiple, switch at runtime)
```

## Usage

```bash
# Interactive mode
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

---

## Niperia -- The Country of Geniuses

Niperia is more than a concept -- it is a vision of civilization. An idea-nation where intelligence, progress, and evolution are the highest values. Where every citizen is a builder, a thinker, a creator. TokioAI was born from this vision.

---

## Work With Us

TokioAI is open-source at its core. But if you need custom deployments, integrations, or security consulting -- we build tailored solutions.

- **Security Consulting** -- Penetration testing, vulnerability assessment, incident response, WAF deployment, SOAR integration, and security architecture review.
- **Custom AI Agents** -- Autonomous agents for your specific use case, tailored to your infrastructure, tools, and workflows.
- **Open Source Contributions** -- Fork our repos, submit PRs, report issues, or build integrations. The engine is open -- every contribution accelerates the mission.

**contact@tokioia.com** | **[tokioia.com](https://tokioia.com)**

---

## Demos

Real footage. No mockups. No simulations.

- [Full Platform Demo](https://www.youtube.com/watch?v=5CV-F6wYrhw) -- CLI agent, Telegram bot, WAF dashboard, AI vision, drone control, health monitoring, IoT integration and more.

---

*AI for human evolution. Born in Niperia. Open source at heart.*

*TokioAI Security Research Inc.*
