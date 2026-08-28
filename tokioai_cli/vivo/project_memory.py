"""
TokioAI Vivo v3 - Project Memory
Compressed persistent project context that survives context window limits.
The LLM can read/write/update this memory to maintain long-term awareness
of what it has done, what it has learned, and what remains to do.

Structure:
  - facts: key discoveries about the project (capped at 50)
  - decisions: important decisions made (capped at 30)
  - progress: what has been done (capped at 50)
  - todo: remaining work items (capped at 30)
  - errors_seen: unique errors encountered and how they were resolved (capped at 30)
  - architecture: high-level architecture notes (capped at 20)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class ProjectMemory:
    """Persistent compressed project memory for long autonomous sessions."""

    MAX_FACTS = 50
    MAX_DECISIONS = 30
    MAX_PROGRESS = 50
    MAX_TODO = 30
    MAX_ERRORS = 30
    MAX_ARCHITECTURE = 20

    def __init__(self, memory_path: str | Path):
        self.path = Path(memory_path)
        self.data: Dict[str, Any] = {
            "facts": [],
            "decisions": [],
            "progress": [],
            "todo": [],
            "errors_seen": [],
            "architecture": [],
            "meta": {
                "created": time.time(),
                "updated": time.time(),
                "total_updates": 0,
            }
        }
        self.load()

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            self.data = json.loads(self.path.read_text())
            return True
        except Exception:
            return False

    def save(self):
        self.data["meta"]["updated"] = time.time()
        self.data["meta"]["total_updates"] = self.data["meta"].get("total_updates", 0) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, default=str))

    def add_fact(self, fact: str):
        """Add a project fact (deduplicates by checking similarity)."""
        facts = self.data.setdefault("facts", [])
        # Simple dedup: check if very similar fact exists
        fact_lower = fact.lower().strip()
        for existing in facts:
            if isinstance(existing, str) and _similarity(existing.lower(), fact_lower) > 0.85:
                return  # Already known
        facts.append(fact)
        if len(facts) > self.MAX_FACTS:
            facts[:] = facts[-self.MAX_FACTS:]
        self.save()

    def add_decision(self, decision: str):
        decisions = self.data.setdefault("decisions", [])
        decisions.append({"text": decision, "ts": time.time()})
        if len(decisions) > self.MAX_DECISIONS:
            decisions[:] = decisions[-self.MAX_DECISIONS:]
        self.save()

    def add_progress(self, item: str):
        progress = self.data.setdefault("progress", [])
        progress.append({"text": item, "ts": time.time()})
        if len(progress) > self.MAX_PROGRESS:
            progress[:] = progress[-self.MAX_PROGRESS:]
        self.save()

    def add_todo(self, item: str, priority: int = 0):
        todo = self.data.setdefault("todo", [])
        todo.append({"text": item, "priority": priority, "ts": time.time()})
        if len(todo) > self.MAX_TODO:
            # Keep highest priority items
            todo.sort(key=lambda x: -x.get("priority", 0))
            todo[:] = todo[:self.MAX_TODO]
        self.save()

    def complete_todo(self, item_text: str) -> bool:
        """Mark a todo as complete (remove it, add to progress)."""
        todo = self.data.get("todo", [])
        for i, t in enumerate(todo):
            text = t.get("text", "") if isinstance(t, dict) else str(t)
            if _similarity(text.lower(), item_text.lower()) > 0.7:
                todo.pop(i)
                self.add_progress(f"Completed: {text}")
                return True
        return False

    def record_error(self, error: str, resolution: str = ""):
        errors = self.data.setdefault("errors_seen", [])
        # Dedup by error similarity
        err_lower = error.lower()[:200]
        for existing in errors:
            if isinstance(existing, dict) and _similarity(existing.get("error", "").lower()[:200], err_lower) > 0.8:
                if resolution:
                    existing["resolution"] = resolution
                    existing["count"] = existing.get("count", 1) + 1
                    self.save()
                return
        errors.append({"error": error[:500], "resolution": resolution, "ts": time.time(), "count": 1})
        if len(errors) > self.MAX_ERRORS:
            errors[:] = errors[-self.MAX_ERRORS:]
        self.save()

    def add_architecture_note(self, note: str):
        arch = self.data.setdefault("architecture", [])
        arch.append(note)
        if len(arch) > self.MAX_ARCHITECTURE:
            arch[:] = arch[-self.MAX_ARCHITECTURE:]
        self.save()

    def get_context_string(self, max_chars: int = 4000) -> str:
        """Get a compact string representation for LLM context injection."""
        lines = []

        # Architecture
        arch = self.data.get("architecture", [])
        if arch:
            lines.append("PROJECT ARCHITECTURE:")
            for a in arch[-5:]:
                lines.append(f"  - {a}")

        # Key facts
        facts = self.data.get("facts", [])
        if facts:
            lines.append(f"\nKEY FACTS ({len(facts)} total, showing last 15):")
            for f in facts[-15:]:
                lines.append(f"  - {f}")

        # Decisions
        decisions = self.data.get("decisions", [])
        if decisions:
            lines.append(f"\nDECISIONS ({len(decisions)} total, showing last 10):")
            for d in decisions[-10:]:
                text = d.get("text", str(d)) if isinstance(d, dict) else str(d)
                lines.append(f"  - {text}")

        # Progress
        progress = self.data.get("progress", [])
        if progress:
            lines.append(f"\nPROGRESS ({len(progress)} items done, showing last 10):")
            for p in progress[-10:]:
                text = p.get("text", str(p)) if isinstance(p, dict) else str(p)
                lines.append(f"  - {text}")

        # TODO
        todo = self.data.get("todo", [])
        if todo:
            lines.append(f"\nTODO ({len(todo)} items):")
            for t in todo:
                text = t.get("text", str(t)) if isinstance(t, dict) else str(t)
                pri = t.get("priority", 0) if isinstance(t, dict) else 0
                lines.append(f"  - {'[HIGH] ' if pri > 0 else ''}{text}")

        # Errors
        errors = self.data.get("errors_seen", [])
        if errors:
            lines.append(f"\nKNOWN ERRORS ({len(errors)} unique):")
            for e in errors[-10:]:
                if isinstance(e, dict):
                    err = e.get("error", "")[:100]
                    res = e.get("resolution", "")
                    cnt = e.get("count", 1)
                    line = f"  - {err}"
                    if res:
                        line += f" -> FIX: {res}"
                    if cnt > 1:
                        line += f" (x{cnt})"
                    lines.append(line)

        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[... memory truncated]"
        return result

    def clear(self):
        """Clear all memory."""
        self.data = {
            "facts": [], "decisions": [], "progress": [],
            "todo": [], "errors_seen": [], "architecture": [],
            "meta": {"created": time.time(), "updated": time.time(), "total_updates": 0}
        }
        self.save()

    def summary_stats(self) -> Dict[str, int]:
        return {
            "facts": len(self.data.get("facts", [])),
            "decisions": len(self.data.get("decisions", [])),
            "progress": len(self.data.get("progress", [])),
            "todo": len(self.data.get("todo", [])),
            "errors": len(self.data.get("errors_seen", [])),
            "architecture": len(self.data.get("architecture", [])),
        }


def _similarity(a: str, b: str) -> float:
    """Simple Jaccard similarity on word sets."""
    if not a or not b:
        return 0.0
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    intersection = sa & sb
    union = sa | sb
    return len(intersection) / len(union)
