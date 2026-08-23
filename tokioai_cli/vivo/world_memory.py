"""
TokioAI Vivo - World Memory
Persistent compressed world model with object registry, events, pose, health.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class WorldObject:
    id: str
    label: str
    position: Optional[Dict[str, float]] = None  # x,y,angle relative or absolute
    confidence: float = 0.5
    last_seen: float = field(default_factory=time.time)
    source: str = "unknown"  # sonar, camera, log, system, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def staleness(self) -> float:
        return time.time() - self.last_seen


@dataclass
class HealthSample:
    ts: float
    score: float  # 0-1
    source: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    id: str
    condition: str
    action: str
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0
    last_hit: Optional[float] = None
    source: str = "builtin"  # builtin, learned, user


@dataclass
class WorldMemoryState:
    objects: List[WorldObject] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    health_history: List[HealthSample] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    pose: Dict[str, Any] = field(default_factory=lambda: {"x": 0, "y": 0, "angle": 0, "frame": "world"})
    objectives: List[Dict[str, Any]] = field(default_factory=list)
    last_cortex_ts: Optional[float] = None
    last_report_ts: Optional[float] = None
    version: int = 1


class WorldMemory:
    """Persistent compressed world memory. Only deltas travel to the cortex."""

    def __init__(self, config, memory_path: Optional[Path] = None):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.memory_path = memory_path or config.memory_path
        self.state = WorldMemoryState()
        self._last_saved = 0.0
        self.load()
        self._load_builtin_rules()

    def _load_builtin_rules(self):
        builtins = [
            Rule(id="cpu_high", condition="cpu_percent > 90 for 120s", action="notify: CPU high; if autonomy>=2: restart_top_cpu_consumer", priority=50, source="builtin"),
            Rule(id="disk_full", condition="disk_percent > 90", action="notify: disk full; if autonomy>=2: clean_temp_files", priority=80, source="builtin"),
            Rule(id="service_down", condition="critical_service not running", action="notify: service down; if autonomy>=2: systemctl restart SERVICE", priority=90, source="builtin"),
            Rule(id="picar_obstacle", condition="sonar_distance < 20cm", action="robot: stop and pivot left 30deg", priority=95, source="builtin"),
            Rule(id="picar_stuck", condition="same_turn repeated 4x in 30s", action="robot: reverse 30cm and scan", priority=90, source="builtin"),
            Rule(id="network_down", condition="gateway_ping fails 3x", action="notify: network down; if autonomy>=2: restart_network_manager", priority=70, source="builtin"),
        ]
        existing_ids = {r.id for r in self.state.rules}
        for r in builtins:
            if r.id not in existing_ids:
                self.state.rules.append(r)

    def record_turn(self, direction: str):
        """Record a robot turn for stuck detection."""
        now = time.time()
        self.state.events.append({
            "ts": now,
            "type": "robot_turn",
            "source": "executor",
            "severity": "info",
            "details": {"direction": direction},
        })
        self._prune_events()
        self.save()

    def add_event(self, event_type: str, source: str, severity: str = "info", details: Optional[Dict] = None):
        event = {
            "ts": time.time(),
            "type": event_type,
            "source": source,
            "severity": severity,
            "details": details or {},
        }
        self.state.events.append(event)
        self._prune_events()
        self.save()

    def add_object(self, obj: WorldObject, replace_if_same_label: bool = True):
        if replace_if_same_label:
            self.state.objects = [o for o in self.state.objects if o.label != obj.label or o.id != obj.id]
        self.state.objects.append(obj)
        self._prune_objects()
        self.save()

    def update_pose(self, pose: Dict[str, Any]):
        self.state.pose.update(pose)
        self.save()

    def add_health(self, score: float, source: str, details: Optional[Dict] = None):
        self.state.health_history.append(HealthSample(
            ts=time.time(), score=score, source=source, details=details or {}
        ))
        self.state.health_history = self.state.health_history[-100:]
        self.save()

    def health_score(self) -> float:
        if not self.state.health_history:
            return 1.0
        return self.state.health_history[-1].score

    def add_or_update_rule(self, rule: Rule):
        existing = [r for r in self.state.rules if r.id == rule.id]
        if existing:
            idx = self.state.rules.index(existing[0])
            self.state.rules[idx] = rule
        else:
            self.state.rules.append(rule)
        self.save()

    def bump_rule(self, rule_id: str):
        for r in self.state.rules:
            if r.id == rule_id:
                r.hit_count += 1
                r.last_hit = time.time()
                self.save()
                return

    def recent_events(self, n: int = 20, severity_min: Optional[str] = None) -> List[Dict]:
        severity_order = {"info": 0, "warning": 1, "error": 2, "critical": 3}
        events = sorted(self.state.events, key=lambda e: e["ts"], reverse=True)[:n]
        if severity_min:
            min_level = severity_order.get(severity_min, 0)
            events = [e for e in events if severity_order.get(e.get("severity", "info"), 0) >= min_level]
        return events

    def active_objects(self, max_age: float = 300.0) -> List[WorldObject]:
        now = time.time()
        return [o for o in self.state.objects if now - o.last_seen < max_age]

    def to_cortex_payload(self) -> Dict[str, Any]:
        """Return a compressed delta payload for the cortex."""
        recent = self.recent_events(15, severity_min="warning")
        anomalies = [e for e in recent if e.get("severity") in ("error", "critical")]
        return {
            "objective": self.cfg.objective,
            "pose": self.state.pose,
            "health_score": round(self.health_score(), 2),
            "active_objects": [
                {
                    "label": o.label,
                    "confidence": o.confidence,
                    "staleness_s": round(o.staleness(), 1),
                    "source": o.source,
                    "position": o.position,
                }
                for o in self.active_objects()
            ],
            "recent_events": recent,
            "top_anomalies": anomalies[:5],
            "rule_count": len(self.state.rules),
            "learned_rules": [
                {"id": r.id, "condition": r.condition, "action": r.action, "hits": r.hit_count}
                for r in self.state.rules if r.source == "learned"
            ],
            "timestamp": time.time(),
        }

    def _prune_events(self, max_items: int = 200):
        if len(self.state.events) > max_items:
            self.state.events = sorted(self.state.events, key=lambda e: e["ts"])[-max_items:]

    def _prune_objects(self, max_items: int = 50):
        if len(self.state.objects) > max_items:
            # Keep most recently seen
            self.state.objects = sorted(self.state.objects, key=lambda o: o.last_seen, reverse=True)[:max_items]

    def save(self):
        now = time.time()
        if now - self._last_saved < 1.0:
            return
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        with open(self.memory_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        self._last_saved = now

    def load(self):
        if not self.memory_path.exists():
            return
        try:
            with open(self.memory_path) as f:
                data = json.load(f)
            self.state.objects = [WorldObject(**o) for o in data.get("objects", [])]
            self.state.events = data.get("events", [])
            self.state.health_history = [HealthSample(**h) for h in data.get("health_history", [])]
            self.state.rules = [Rule(**r) for r in data.get("rules", [])]
            self.state.pose = data.get("pose", self.state.pose)
            self.state.objectives = data.get("objectives", [])
            self.state.last_cortex_ts = data.get("last_cortex_ts")
            self.state.last_report_ts = data.get("last_report_ts")
            self.state.version = data.get("version", 1)
        except Exception as e:
            self.add_event("memory_load_error", "world_memory", "error", {"error": str(e)})
