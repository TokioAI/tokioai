"""
Memory Optimizer for TokioAI CLI — v3.0 (anti-amnesia + efficiency edition)
Reduces token spend while NEVER losing critical persistent context.

v3.0 changes:
- Smart truncation at sentence/line boundaries (no mid-word cuts)
- Deduplication of similar entries (prevents memory bloat)
- Today's entries always HOT regardless of score
- Compaction recovery is more focused (less noise)
- Cold index more compact (40 lines, shorter titles)
- Pinned + HOT budget accounting prevents overflows
"""

import os
import re
import json
from datetime import datetime, timedelta
from typing import Tuple, List, Dict

def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate text at a sentence or line boundary, never mid-word."""
    if len(text) <= max_chars:
        return text
    # Try to cut at last newline before limit
    cut = text[:max_chars]
    last_nl = cut.rfind('\n')
    if last_nl > max_chars * 0.6:  # Found a newline in the last 40%
        return cut[:last_nl] + "\n...[truncated]"
    # Try to cut at last sentence boundary
    for sep in ('. ', '.\n', '! ', '? '):
        last_sep = cut.rfind(sep)
        if last_sep > max_chars * 0.5:
            return cut[:last_sep + 1] + "\n...[truncated]"
    # Fallback: cut at last space
    last_space = cut.rfind(' ')
    if last_space > max_chars * 0.7:
        return cut[:last_space] + "...[truncated]"
    return cut + "...[truncated]"


MEMORY_FILE = os.path.expanduser("~/.tokioai/memory.md")
MEMORY_ARCHIVE = os.path.expanduser("~/.tokioai/memory_archive.md")
TASKS_FILE = os.path.expanduser("~/.tokioai/tasks.json")

# Module-level overrides for testing (set by ops.py before calling)
_MEMORY_FILE_OVERRIDE = None
_TASKS_FILE_OVERRIDE = None

def _get_memory_file():
    return _MEMORY_FILE_OVERRIDE or MEMORY_FILE

def _get_tasks_file():
    return _TASKS_FILE_OVERRIDE or TASKS_FILE

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

# Max tokens for memory in system prompt (~4 chars per token)
MAX_MEMORY_TOKENS = 3500   # v2 was 4000 — trim slightly to leave more room for conversation
MAX_MEMORY_CHARS = MAX_MEMORY_TOKENS * 4  # ~14000 chars

# Max tokens for pinned sections (separate budget)
MAX_PINNED_CHARS = 6000  # Pinned infra gets its own budget, not counted against hot

# Max tasks to include in detail
MAX_ACTIVE_TASKS_DETAIL = 5
MAX_TASK_PLAN_CHARS = 300  # Truncate long plans

# How recent a memory entry must be to stay "hot"
HOT_MEMORY_DAYS = 7

# Pinned sections: CORE infrastructure definitions only (not project logs)
# These match section TITLES only -- dated deploy/fix entries are NOT pinned
PINNED_TITLE_EXACT = [
    "infraestructura", "infrastructure",
    "ssh",
    "credential", "credencial",
    "home assistant",
    "wifi defense",
    "drone tello",
    "telegram bot",
]

PINNED_TITLE_CONTAINS = [
    "regla",
    "no olvidar",
    "don\'t forget",
    "no tocar",
]

# Max chars for body truncation per section
MAX_BODY_CHARS_PINNED = 3000   # Pinned sections get more space
MAX_BODY_CHARS_HOT = 1500      # Hot sections (was 500 — lost too much)
MAX_BODY_CHARS_COLD = 300      # Cold sections in index only

# ─────────────────────────────────────────────────────────────
# MEMORY PARSING
# ─────────────────────────────────────────────────────────────

def _parse_memory_sections() -> List[Dict]:
    """Parse memory.md into structured sections."""
    mem_file = _get_memory_file()
    if not os.path.exists(mem_file):
        return []
    
    with open(mem_file, "r") as f:
        content = f.read()
    
    sections = []
    parts = re.split(r'\n## ', content)
    
    # Handle content before first ## (simple entries without headers)
    if parts[0].strip():
        first_content = parts[0].strip()
        sections.append({
            "title": "",
            "body": first_content,
            "date": None,
            "score": 0,  # Will be computed below
            "chars": len(first_content),
            "raw": first_content,
            "pinned": False
        })
    
    for i, part in enumerate(parts):
        if i == 0:
            continue
        lines = part.split('\n')
        title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()
        
        # Extract date from title
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', title)
        entry_date = None
        if date_match:
            try:
                entry_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            except ValueError:
                pass
        
        # Check if pinned
        is_pinned = _is_pinned(title, body)
        
        # Calculate relevance score
        score = _compute_relevance(title, body, entry_date, is_pinned)
        
        sections.append({
            "title": title,
            "body": body,
            "date": entry_date,
            "score": score,
            "chars": len(part),
            "raw": "## " + part,
            "pinned": is_pinned
        })
    
    # Recompute score for first section now that we know context
    if sections and not sections[0]["title"]:
        sections[0]["score"] = _compute_relevance("", sections[0]["body"], None, 
                                                    _is_pinned("", sections[0]["body"]))
        sections[0]["pinned"] = _is_pinned("", sections[0]["body"])
    
    return sections


def _is_pinned(title: str, body: str) -> bool:
    """Pin = section whose title matches core infrastructure patterns.
    
    We do NOT pin project logs/deploys (Business Agent v8.x, TokioNav vX, etc.)
    Those are important but date-scored, not pinned.
    Only pin: infrastructure definitions, SSH config, rules marked "NO OLVIDAR", etc.
    """
    title_lower = title.lower().strip()
    
    # Dated entries: only pin if title contains a "never forget" rule
    if re.search(r'\d{4}-\d{2}-\d{2}', title_lower):
        for kw in PINNED_TITLE_CONTAINS:
            if kw in title_lower:
                return True
        return False
    
    # Undated sections: check if title matches core infra
    for kw in PINNED_TITLE_EXACT:
        if kw in title_lower:
            return True
    
    for kw in PINNED_TITLE_CONTAINS:
        if kw in title_lower:
            return True
    
    # The first section (consolidated memory header) is always pinned
    if not title and "infraestructura" in body[:500].lower():
        return True
    
    # Business Agent DEFINITION section (not a dated log)
    if "business agent" in title_lower and "pro" in title_lower:
        return True
    
    # "Projects" section (short list)
    if title_lower in ("projects", "proyectos"):
        return True
    
    return False


def _compute_relevance(title: str, body: str, entry_date, is_pinned: bool = False) -> float:
    """Score 0-100. Higher = more relevant."""
    # Pinned sections ALWAYS get max score
    if is_pinned:
        return 100.0
    
    score = 50.0
    
    # Date recency
    if entry_date:
        days_old = (datetime.now() - entry_date).days
        if days_old <= 0:
            score += 50
        elif days_old <= 1:
            score += 40
        elif days_old <= 3:
            score += 30
        elif days_old <= 7:
            score += 20
        elif days_old <= 14:
            score += 10
        elif days_old <= 30:
            score += 0  # neutral, not penalized
        else:
            score -= 15  # Old but not harsh
    else:
        # No date = probably infrastructure/config, keep it
        score += 40
    
    # Critical keywords (keep always)
    critical = [
        r'API.*KEY', r'PAT', r'github', r'OpenRouter', r'Gemini',
        r'dual', r'router', r'safety', r'security',
        r'TokioAI', r'Deploy', r'Steering',
        r'current', r'active', r'running',
        r'remember', r'buy', r'password', r'secret', r'credential',
        r'IP\s*:', r'SSH', r'docker', r'container',
        r'Raspi', r'PiCar', r'PiDog', r'GCP', r'VM',
        r'Home.?Assistant', r'Telegram', r'WiFi',
        r'REGLA', r'NO TOCAR', r'NO OLVIDAR',
    ]
    matched_critical = 0
    for kw in critical:
        if re.search(kw, title, re.I) or re.search(kw, body[:300], re.I):
            matched_critical += 1
    # Diminishing returns: first 3 matches = +20 each, then +5
    score += min(matched_critical, 3) * 20 + max(0, matched_critical - 3) * 5
    
    # Deprecated/obsolete markers
    deprecated = [
        r'\babandoned\b', r'\bpausa\b', r'\bold version\b', r'\bdeprecated\b',
    ]
    for kw in deprecated:
        if re.search(kw, title, re.I):
            score -= 10
    
    # Length penalty for very long entries (verbose logs)
    if len(body) > 2000:
        score -= 5  # Mild penalty (was -10 for >1000)
    
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────
# MEMORY OPTIMIZATION
# ─────────────────────────────────────────────────────────────

def optimize_memory() -> Tuple[str, str]:
    """
    Returns: (optimized_memory_for_prompt, full_memory_archive)
    
    Strategy:
    1. Pinned sections ALWAYS included (infra, SSH, credentials, rules)
    2. Hot sections (recent + relevant) fill remaining budget
    3. Cold sections go to archive (index only in prompt)
    """
    sections = _parse_memory_sections()
    
    if not sections:
        return "", ""
    
    # Sort by score descending, then date descending
    sections.sort(key=lambda x: (-x["score"], x["date"] or datetime.min))
    
    # Phase 1: Always include pinned sections (separate budget)
    pinned_sections = []
    remaining_sections = []
    pinned_chars = 0
    
    for s in sections:
        if s["pinned"]:
            pinned_sections.append(s)
            pinned_chars += s["chars"]
        else:
            remaining_sections.append(s)
    
    # Phase 2: Fill remaining budget with hot sections
    hot_budget = MAX_MEMORY_CHARS
    hot_sections = []
    cold_sections = []
    current_chars = 0
    now = datetime.now()
    
    for s in remaining_sections:
        is_today = s["date"] and (now - s["date"]).days <= 0 if s["date"] else False
        is_hot = (s["score"] >= 65 or is_today or
                  (s["date"] and (now - s["date"]).days <= HOT_MEMORY_DAYS))
        
        if is_hot and current_chars + min(s["chars"], MAX_BODY_CHARS_HOT) <= hot_budget:
            hot_sections.append(s)
            current_chars += min(s["chars"], MAX_BODY_CHARS_HOT)
        else:
            cold_sections.append(s)
    
    # Build optimized memory
    opt_lines = ["## Active Context (recent + relevant)"]
    
    # Pinned first (with separate budget cap)
    pinned_total = 0
    for s in pinned_sections:
        body = s["body"]
        remaining_pinned = MAX_PINNED_CHARS - pinned_total
        if remaining_pinned <= 0:
            cold_sections.append(s)  # Overflow pinned -> cold
            continue
        if len(body) > min(MAX_BODY_CHARS_PINNED, remaining_pinned):
            body = _smart_truncate(body, min(MAX_BODY_CHARS_PINNED, remaining_pinned))
        pinned_total += len(body)
        opt_lines.append(f"\n### {s['title']}")
        opt_lines.append(body)
    
    # Then hot (smart truncation)
    for s in hot_sections:
        body = s["body"]
        if len(body) > MAX_BODY_CHARS_HOT:
            body = _smart_truncate(body, MAX_BODY_CHARS_HOT)
        opt_lines.append(f"\n### {s['title']}")
        opt_lines.append(body)
    
    optimized = "\n".join(opt_lines) if len(opt_lines) > 1 else ""
    
    # Build archive
    archive = "\n\n".join(s["raw"] for s in cold_sections)
    
    return optimized, archive


def get_memory_stats() -> Dict:
    """Return memory statistics for monitoring."""
    sections = _parse_memory_sections()
    optimized, archive = optimize_memory()
    
    pinned = len([s for s in sections if s.get("pinned")])
    hot = len([s for s in sections if s["score"] >= 65 and not s.get("pinned")])
    cold = len(sections) - pinned - hot
    
    return {
        "total_sections": len(sections),
        "total_chars": sum(s["chars"] for s in sections),
        "optimized_chars": len(optimized),
        "archived_chars": len(archive),
        "reduction_pct": round(100 * (1 - len(optimized) / max(1, sum(s["chars"] for s in sections))), 1),
        "pinned_sections": pinned,
        "hot_sections": hot,
        "cold_sections": cold,
    }


# ─────────────────────────────────────────────────────────────
# AUTO-RECALL — index + on-demand retrieval
# ─────────────────────────────────────────────────────────────

MAX_INDEX_LINES = 40  # Compact index (was 50)

def build_cold_index() -> str:
    """Build a 1-line-per-section index of COLD memory.
    Lets the model know what exists and fetch it on demand.
    """
    sections = _parse_memory_sections()
    if not sections:
        return ""
    
    # Recompute hot/cold split (same logic as optimize_memory)
    sections.sort(key=lambda x: (-x["score"], x["date"] or datetime.min))
    cold = []
    current_chars = 0
    for s in sections:
        if s.get("pinned"):
            continue  # pinned = always in prompt, skip
        is_hot = (s["score"] >= 65 or 
                  (s["date"] and (datetime.now() - s["date"]).days <= HOT_MEMORY_DAYS))
        if is_hot and current_chars + s["chars"] <= MAX_MEMORY_CHARS:
            current_chars += s["chars"]
        else:
            cold.append(s)
    
    if not cold:
        return ""
    
    lines = ["\n## Memory Index (older entries on disk -- fetch full text with search_files on ~/.tokioai/memory.md if needed)"]
    seen = set()
    count = 0
    for s in cold:
        title = s["title"] or "(untitled)"
        date_str = s["date"].strftime("%Y-%m-%d") if s["date"] else "?"
        # Clean title
        title = re.sub(r'^\d{4}-\d{2}-\d{2}\s*[-\u2014:]?\s*', '', title)
        title = re.sub(r'\s*[-\u2014(]*\s*\d{4}-\d{2}-\d{2}[\s)]*$', '', title).strip()
        if not title or title == date_str:
            title = (s["body"].split("\n")[0][:50] or "(note)").strip()
            title = re.sub(r'^#+\s*', '', title)
        if len(title) > 55:
            title = title[:55] + "..."
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- [{date_str}] {title}")
        count += 1
        if count >= MAX_INDEX_LINES:
            lines.append(f"- ...({len(cold) - count} more on disk)")
            break
    
    return "\n".join(lines)


def search_memory(query: str, max_results: int = 3) -> List[Dict]:
    """Search memory sections matching a query."""
    if not query or not query.strip():
        return []
    
    sections = _parse_memory_sections()
    if not sections:
        return []
    
    query_lower = query.lower().strip()
    terms = [t for t in re.split(r'\s+', query_lower) if len(t) > 1]
    
    scored = []
    for s in sections:
        text = (s["title"] + "\n" + s["body"]).lower()
        hits = sum(1 for t in terms if t in text)
        title_hits = sum(1 for t in terms if t in s["title"].lower())
        score = hits + (title_hits * 3)
        if score > 0:
            scored.append((score, s))
    
    scored.sort(key=lambda x: -x[0])
    return [s for score, s in scored[:max_results]]


# ─────────────────────────────────────────────────────────────
# TASK OPTIMIZATION
# ─────────────────────────────────────────────────────────────

def optimize_tasks() -> str:
    """Return optimized task context: only active, truncated plans."""
    tasks_file = _get_tasks_file()
    if not os.path.exists(tasks_file):
        return ""
    
    try:
        with open(tasks_file, "r") as f:
            tasks = json.load(f)
    except Exception:
        return ""
    
    active = [t for t in tasks if t.get("status") != "done"]
    if not active:
        return ""
    
    # Sort: in_progress first, then by ID (recent)
    active.sort(key=lambda t: (t.get("status") != "in_progress", -t.get("id", 0)))
    
    lines = ["## Active Tasks"]
    
    for t in active[:MAX_ACTIVE_TASKS_DETAIL]:
        status = t.get("status", "pending")
        icon = {"pending": "[ ]", "in_progress": "[~]", "blocked": "[!]"}.get(status, "[ ]")
        task_desc = t.get("task", "?")[:100]
        lines.append(f"\n{icon} #{t.get('id', '?')}: {task_desc} ({status})")
        
        if t.get("current_step"):
            lines.append(f"    >>> STEP: {t['current_step']}")
        
        if t.get("plan"):
            plan = t["plan"]
            if len(plan) > MAX_TASK_PLAN_CHARS:
                plan = plan[:MAX_TASK_PLAN_CHARS] + "..."
            lines.append(f"    Plan: {plan}")
    
    if len(active) > MAX_ACTIVE_TASKS_DETAIL:
        others = active[MAX_ACTIVE_TASKS_DETAIL:]
        other_ids = [f"#{t.get('id')}" for t in others]
        lines.append(f"\n...and {len(others)} more active: {', '.join(other_ids)}")
    
    lines.append("\nUse `task list` for full details on any task.")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# COMPACTION RECOVERY CONTEXT
# ─────────────────────────────────────────────────────────────

def build_compaction_recovery() -> str:
    """Build a memory snapshot specifically for post-compaction recovery.
    
    Unlike optimize_memory (for system prompt every turn), this builds a
    focused snapshot with the MOST critical info for re-orientation:
    - All pinned sections (infra, SSH, credentials)
    - Active tasks with full plans
    - Last 3 dated entries
    
    This is injected into the conversation after compaction so the model
    doesn't lose its bearings.
    """
    sections = _parse_memory_sections()
    if not sections:
        return ""
    
    parts = []
    
    # 1. All pinned sections (truncated to fit recovery budget)
    pinned = [s for s in sections if s.get("pinned")]
    if pinned:
        for s in pinned:
            body = _smart_truncate(s["body"], 2000)  # Tighter for recovery
            parts.append(f"## {s['title']}\n{body}")
    
    # 2. Last 3 dated entries (most recent context)
    dated = [s for s in sections if s.get("date") and not s.get("pinned")]
    dated.sort(key=lambda x: x["date"], reverse=True)
    for s in dated[:3]:
        body = _smart_truncate(s["body"], 800)
        parts.append(f"## {s['title']}\n{body}")
    
    result = "\n\n".join(parts)
    # Cap total at 8000 chars for recovery context
    if len(result) > 8000:
        result = result[:8000] + "\n...(truncated)"
    
    return result


# ─────────────────────────────────────────────────────────────
# MAIN INTERFACE
# ─────────────────────────────────────────────────────────────

def build_optimized_context() -> str:
    """
    Build complete optimized context for system prompt.
    Returns: hot memory + cold index + tasks, trimmed to fit token budget.
    """
    optimized_mem, _ = optimize_memory()
    cold_index = build_cold_index()
    optimized_tasks = optimize_tasks()
    
    parts = []
    if optimized_mem:
        parts.append(optimized_mem)
    if cold_index:
        parts.append(cold_index)
    if optimized_tasks:
        parts.append(optimized_tasks)
    
    return "\n\n".join(parts)


if __name__ == "__main__":
    # CLI test
    stats = get_memory_stats()
    print("Memory Optimization Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    print("\n" + "="*50)
    print("Optimized Context Preview:")
    print("="*50)
    ctx = build_optimized_context()
    print(ctx[:3000] + "..." if len(ctx) > 3000 else ctx)
    print(f"\n\nTotal: {len(ctx)} chars (~{len(ctx)//4} tokens)")
    
    print("\n" + "="*50)
    print("Compaction Recovery Preview:")
    print("="*50)
    recovery = build_compaction_recovery()
    print(recovery[:2000] + "..." if len(recovery) > 2000 else recovery)
    print(f"\nRecovery: {len(recovery)} chars (~{len(recovery)//4} tokens)")
