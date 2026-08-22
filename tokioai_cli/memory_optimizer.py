"""
Memory Optimizer for TokioAI CLI
Reduces token spend by 60-80% while preserving critical context.
"""

import os
import re
import json
from datetime import datetime, timedelta
from typing import Tuple, List, Dict

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
MAX_MEMORY_TOKENS = 1500  # Was ~10,000 — now hard-capped
MAX_MEMORY_CHARS = MAX_MEMORY_TOKENS * 4

# Max tasks to include in detail
MAX_ACTIVE_TASKS_DETAIL = 3
MAX_TASK_PLAN_CHARS = 200  # Truncate long plans

# How recent a memory entry must be to stay "hot"
HOT_MEMORY_DAYS = 3

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
        score = _compute_relevance("", first_content, None)
        sections.append({
            "title": "",
            "body": first_content,
            "date": None,
            "score": score,
            "chars": len(first_content),
            "raw": first_content
        })
    
    for i, part in enumerate(parts):
        if i == 0:
            continue  # Already handled above
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
        
        # Calculate relevance score
        score = _compute_relevance(title, body, entry_date)
        
        sections.append({
            "title": title,
            "body": body,
            "date": entry_date,
            "score": score,
            "chars": len(part),
            "raw": "## " + part
        })
    
    return sections


def _compute_relevance(title: str, body: str, entry_date) -> float:
    """Score 0-100. Higher = more relevant."""
    score = 50.0
    
    # Date recency — VERY recent entries always win
    if entry_date:
        days_old = (datetime.now() - entry_date).days
        if days_old <= 0:  # Today
            score += 50
        elif days_old <= 1:
            score += 40
        elif days_old <= 3:
            score += 30
        elif days_old <= 7:
            score += 15
        elif days_old <= 14:
            score += 5
        else:
            score -= 20  # Old entries penalized
    else:
        # No date = probably test data or recent append, ALWAYS keep
        score += 45
    
    # Critical keywords (keep always)
    critical = [
        r'API.*KEY', r'PAT', r'github', r'OpenRouter', r'Gemini',
        r'dual', r'router', r'safety', r'security',
        r'TokioAI', r'Deploy.*Raspi', r'Steering.*Invert',
        r'v11', r'v10', r'current', r'active', r'running',
        r'remember', r'buy', r'password', r'secret', r'credential'
    ]
    for kw in critical:
        if re.search(kw, title, re.I) or re.search(kw, body[:200], re.I):
            score += 20
    
    # Deprecated/obsolete markers
    deprecated = [
        r'abandoned', r'pausa', r'backup', r'old', r'deprecated',
        r'v9', r'v8', r'v7', r'v6', r'v5', r'v4', r'v3', r'v2', r'v1'
    ]
    for kw in deprecated:
        if re.search(kw, title, re.I):
            score -= 10
    
    # Length penalty for very long entries (usually verbose logs)
    if len(body) > 1000:
        score -= 10
    
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────
# MEMORY OPTIMIZATION
# ─────────────────────────────────────────────────────────────

def optimize_memory() -> Tuple[str, str]:
    """
    Returns: (optimized_memory_for_prompt, full_memory_archive)
    optimized: trimmed to MAX_MEMORY_CHARS, high-relevance only
    archive: everything, for reference/restore
    """
    sections = _parse_memory_sections()
    
    if not sections:
        return "", ""
    
    # Sort by score descending, then date descending
    sections.sort(key=lambda x: (-x["score"], x["date"] or datetime.min))
    
    # Split into hot (keep in prompt) and cold (archive)
    hot_sections = []
    cold_sections = []
    current_chars = 0
    
    for s in sections:
        # Always keep if very high score or very recent
        is_hot = (s["score"] >= 70 or 
                  (s["date"] and (datetime.now() - s["date"]).days <= HOT_MEMORY_DAYS))
        
        if is_hot and current_chars + s["chars"] <= MAX_MEMORY_CHARS:
            hot_sections.append(s)
            current_chars += s["chars"]
        else:
            cold_sections.append(s)
    
    # Build optimized memory
    if hot_sections:
        opt_lines = ["## Active Context (recent + relevant)"]
        for s in hot_sections:
            # Truncate very long entries
            body = s["body"]
            if len(body) > 500:
                body = body[:500] + "...[truncated]"
            opt_lines.append(f"\n### {s['title']}")
            opt_lines.append(body)
        optimized = "\n".join(opt_lines)
    else:
        optimized = ""
    
    # Build archive
    archive = "\n\n".join(s["raw"] for s in cold_sections)
    
    return optimized, archive


def get_memory_stats() -> Dict:
    """Return memory statistics for monitoring."""
    sections = _parse_memory_sections()
    optimized, archive = optimize_memory()
    
    return {
        "total_sections": len(sections),
        "total_chars": sum(s["chars"] for s in sections),
        "optimized_chars": len(optimized),
        "archived_chars": len(archive),
        "reduction_pct": 100 * (1 - len(optimized) / max(1, sum(s["chars"] for s in sections))),
        "hot_sections": len([s for s in sections if s["score"] >= 70]),
        "cold_sections": len([s for s in sections if s["score"] < 70])
    }


# ─────────────────────────────────────────────────────────────
# AUTO-RECALL — index + on-demand retrieval
# ─────────────────────────────────────────────────────────────

# Max lines in the cold index (keep it cheap)
MAX_INDEX_LINES = 40

def build_cold_index() -> str:
    """Build a 1-line-per-section index of COLD (not-in-prompt) memory.
    ~15 tokens per line. Lets the model know what else exists and fetch it on demand.
    Only indexes sections NOT already in hot context (no duplication).
    """
    sections = _parse_memory_sections()
    if not sections:
        return ""
    
    # Recompute hot/cold split (same logic as optimize_memory)
    sections.sort(key=lambda x: (-x["score"], x["date"] or datetime.min))
    cold = []
    current_chars = 0
    for s in sections:
        is_hot = (s["score"] >= 70 or 
                  (s["date"] and (datetime.now() - s["date"]).days <= HOT_MEMORY_DAYS))
        if is_hot and current_chars + s["chars"] <= MAX_MEMORY_CHARS:
            current_chars += s["chars"]
        else:
            cold.append(s)
    
    if not cold:
        return ""
    
    lines = ["## Memory Index (older entries on disk — fetch full text with search_files on ~/.tokioai/memory.md if needed)"]
    seen = set()
    count = 0
    for s in cold:
        date_str = s["date"].strftime("%Y-%m-%d") if s["date"] else "?"
        title = s["title"].strip()
        # Clean title: strip leading ##, duplicate date prefix/suffix
        title = re.sub(r'^#+\s*', '', title)
        title = re.sub(r'^\d{4}-\d{2}-\d{2}\s*[-—:]?\s*', '', title)
        title = re.sub(r'\s*[-—(]*\s*\d{4}-\d{2}-\d{2}[\s)]*$', '', title).strip()
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
    """Search memory sections matching a query. Returns full sections.
    Used by /recall command and available for the model via tools.
    """
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
        # Score: count matching terms, bonus for title match
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
    
    # Show top N in detail
    for t in active[:MAX_ACTIVE_TASKS_DETAIL]:
        status = t.get("status", "pending")
        icon = {"pending": "[ ]", "in_progress": "[~]", "blocked": "[!]"}.get(status, "[ ]")
        task_desc = t.get("task", "?")[:80]
        lines.append(f"\n{icon} #{t.get('id', '?')}: {task_desc} ({status})")
        
        if t.get("current_step"):
            lines.append(f"    >>> STEP: {t['current_step']}")
        
        if t.get("plan"):
            plan = t["plan"]
            if len(plan) > MAX_TASK_PLAN_CHARS:
                plan = plan[:MAX_TASK_PLAN_CHARS] + "..."
            lines.append(f"    Plan: {plan}")
    
    # Summarize rest
    if len(active) > MAX_ACTIVE_TASKS_DETAIL:
        others = active[MAX_ACTIVE_TASKS_DETAIL:]
        other_ids = [f"#{t.get('id')}" for t in others]
        lines.append(f"\n...and {len(others)} more active: {', '.join(other_ids)}")
    
    lines.append("\nUse `task list` for full details on any task.")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# MAIN INTERFACE
# ─────────────────────────────────────────────────────────────

def build_optimized_context() -> str:
    """
    Build complete optimized context for system prompt.
    Returns: hot memory + cold index + tasks, trimmed to fit token budget.
    The cold index lets the model know what exists and fetch it on demand.
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
    print(ctx[:2000] + "..." if len(ctx) > 2000 else ctx)
    print(f"\n\nTotal: {len(ctx)} chars (~{len(ctx)//4} tokens)")
