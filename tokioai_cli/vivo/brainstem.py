"""
TokioAI Vivo - Brainstem
Fast rule-based reflex layer. 0 tokens for routine control.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .world_memory import WorldMemory, WorldObject


class BrainstemDecision:
    def __init__(self, action: str = "noop", reason: str = "", confidence: float = 0.0,
                 destructive: bool = False, rule_id: Optional[str] = None, escalate: bool = False):
        self.action = action
        self.reason = reason
        self.confidence = confidence
        self.destructive = destructive
        self.rule_id = rule_id
        self.escalate = escalate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "destructive": self.destructive,
            "rule_id": self.rule_id,
            "escalate": self.escalate,
        }


class Brainstem:
    """Rule engine that reacts to snapshots. No LLM involved."""

    def __init__(self, config, memory: WorldMemory):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.memory = memory
        self._turn_history: List[str] = []
        self._turn_history_ts: List[float] = []

    def evaluate(self, snapshot: Dict[str, Any]) -> BrainstemDecision:
        # Priority 0: check learned rules first (they override builtins)
        for rule in sorted(self.memory.state.rules, key=lambda r: r.priority, reverse=True):
            if rule.source == "learned":
                decision = self._evaluate_rule(rule, snapshot)
                if decision:
                    return decision

        # Priority 1: critical obstacles / safety
        if "picar" in snapshot:
            picar = snapshot["picar"]
            dist = picar.get("sonar_distance_cm")
            if dist is not None and dist < 20:
                self.memory.bump_rule("picar_obstacle")
                return BrainstemDecision(
                    action="robot_stop_and_pivot",
                    reason=f"sonar {dist}cm < 20cm",
                    confidence=0.95,
                    destructive=False,
                    rule_id="picar_obstacle",
                )

        # Priority 2: network down
        net = snapshot.get("network", {})
        if not net.get("gateway_reachable", True):
            self.memory.bump_rule("network_down")
            return BrainstemDecision(
                action="notify_network_down",
                reason="gateway unreachable",
                confidence=0.9,
                destructive=False,
                rule_id="network_down",
            )

        # Priority 3: system resources
        sys_data = snapshot.get("system", {})
        cpu = sys_data.get("cpu_percent")
        disk = sys_data.get("disk_percent")

        if disk is not None and disk > 90:
            self.memory.bump_rule("disk_full")
            if self.cfg.autonomy >= 2:
                return BrainstemDecision(
                    action="clean_temp_files",
                    reason=f"disk {disk}% > 90%",
                    confidence=0.85,
                    destructive=True,
                    rule_id="disk_full",
                )
            return BrainstemDecision(
                action="notify_disk_full",
                reason=f"disk {disk}% > 90%",
                confidence=0.85,
                rule_id="disk_full",
            )

        if cpu is not None and cpu > 90:
            # Need sustained; keep history
            if self._sustained(cpu > 90, duration=120):
                self.memory.bump_rule("cpu_high")
                if self.cfg.autonomy >= 2:
                    return BrainstemDecision(
                        action="restart_top_cpu_consumer",
                        reason=f"CPU {cpu}% sustained > 90% for 120s",
                        confidence=0.8,
                        destructive=True,
                        rule_id="cpu_high",
                    )
                return BrainstemDecision(
                    action="notify_cpu_high",
                    reason=f"CPU {cpu}% sustained > 90%",
                    confidence=0.8,
                    rule_id="cpu_high",
                )

        # Priority 4: critical services down
        services = snapshot.get("services", {}).get("services", {})
        critical = ["ssh", "docker"]
        for svc in critical:
            st = services.get(svc, {})
            if not st.get("active", True):
                self.memory.bump_rule("service_down")
                if self.cfg.autonomy >= 2:
                    return BrainstemDecision(
                        action=f"systemctl restart {svc}",
                        reason=f"critical service {svc} down",
                        confidence=0.9,
                        destructive=True,
                        rule_id="service_down",
                    )
                return BrainstemDecision(
                    action=f"notify_service_down {svc}",
                    reason=f"critical service {svc} down",
                    confidence=0.9,
                    rule_id="service_down",
                )

        # Priority 5: robot stuck detection
        if self._is_stuck_turning():
            self.memory.bump_rule("picar_stuck")
            return BrainstemDecision(
                action="robot_reverse_and_scan",
                reason="same turn repeated 4x in 30s",
                confidence=0.85,
                destructive=False,
                rule_id="picar_stuck",
            )

        # Default: monitor, maybe escalate if anomalies exist
        anomalies = self.memory.to_cortex_payload().get("top_anomalies", [])
        if anomalies:
            return BrainstemDecision(action="noop", reason=f"{len(anomalies)} anomalies pending cortex review", escalate=True, confidence=0.5)

        return BrainstemDecision(action="noop", reason="all green", confidence=0.9)

    def _evaluate_rule(self, rule, snapshot: Dict[str, Any]) -> Optional[BrainstemDecision]:
        """Evaluate a learned rule against snapshot. Simple condition parser."""
        try:
            cond = rule.condition.lower()
            # Parse simple conditions like "cpu_percent > 90" or "sonar < 20"
            if "cpu_percent" in cond and ">" in cond:
                threshold = float(cond.split(">")[1].strip().split()[0])
                cpu = snapshot.get("system", {}).get("cpu_percent")
                if cpu is not None and cpu > threshold:
                    self.memory.bump_rule(rule.id)
                    return BrainstemDecision(
                        action=rule.action,
                        reason=f"learned rule: {rule.condition}",
                        confidence=0.85,
                        rule_id=rule.id,
                    )
            elif "disk_percent" in cond and ">" in cond:
                threshold = float(cond.split(">")[1].strip().split()[0])
                disk = snapshot.get("system", {}).get("disk_percent")
                if disk is not None and disk > threshold:
                    self.memory.bump_rule(rule.id)
                    return BrainstemDecision(
                        action=rule.action,
                        reason=f"learned rule: {rule.condition}",
                        confidence=0.85,
                        rule_id=rule.id,
                    )
            elif "sonar" in cond and "<" in cond:
                threshold = float(cond.split("<")[1].strip().split()[0].replace("cm", ""))
                dist = snapshot.get("picar", {}).get("sonar_distance_cm")
                if dist is not None and dist < threshold:
                    self.memory.bump_rule(rule.id)
                    return BrainstemDecision(
                        action=rule.action,
                        reason=f"learned rule: {rule.condition}",
                        confidence=0.9,
                        rule_id=rule.id,
                    )
            elif "memory_percent" in cond and ">" in cond:
                threshold = float(cond.split(">")[1].strip().split()[0])
                mem = snapshot.get("system", {}).get("memory_percent")
                if mem is not None and mem > threshold:
                    self.memory.bump_rule(rule.id)
                    return BrainstemDecision(
                        action=rule.action,
                        reason=f"learned rule: {rule.condition}",
                        confidence=0.85,
                        rule_id=rule.id,
                    )
        except Exception:
            pass
        return None

    def record_turn(self, direction: str):
        """Delegate turn recording to memory."""
        self.memory.record_turn(direction)

    def _is_stuck_turning(self) -> bool:
        """Check if robot is stuck turning by analyzing memory events."""
        cutoff = time.time() - 30
        recent_turns = [
            e for e in self.memory.state.events
            if e.get("type") == "robot_turn" and e.get("ts", 0) > cutoff
        ]
        if len(recent_turns) < 4:
            return False
        last4 = [t["details"]["direction"] for t in recent_turns[-4:]]
        return len(set(last4)) == 1

    def _sustained(self, condition: bool, duration: float = 120.0) -> bool:
        """Track sustained conditions using a sliding window of timestamps."""
        now = time.time()
        if not hasattr(self, '_sustained_trackers'):
            self._sustained_trackers: Dict[str, List[float]] = {}
        # Use a per-condition key based on the caller context (simplified: single tracker)
        key = "cpu_high"  # For now, only CPU uses this. Can be parameterized.
        if key not in self._sustained_trackers:
            self._sustained_trackers[key] = []
        if condition:
            self._sustained_trackers[key].append(now)
        # Prune old entries
        cutoff = now - duration
        self._sustained_trackers[key] = [t for t in self._sustained_trackers[key] if t > cutoff]
        # Need at least 3 consecutive ticks (assuming ~2s tick) within duration
        return len(self._sustained_trackers[key]) >= 3

    def update_memory_from_snapshot(self, snapshot: Dict[str, Any]):
        """Translate snapshot into world memory objects/events."""
        self.memory.update_pose({"ts": snapshot.get("ts", time.time())})

        sys_data = snapshot.get("system", {})
        cpu = sys_data.get("cpu_percent")
        mem = sys_data.get("memory_percent")
        disk = sys_data.get("disk_percent")

        # Compute health score
        health = 1.0
        if cpu is not None:
            health -= max(0, (cpu - 50) / 100) * 0.3
        if mem is not None:
            health -= max(0, (mem - 80) / 100) * 0.3
        if disk is not None:
            health -= max(0, (disk - 80) / 100) * 0.3
        if not snapshot.get("network", {}).get("gateway_reachable", True):
            health -= 0.3
        health = max(0.0, min(1.0, health))
        self.memory.add_health(round(health, 2), "brainstem", {"cpu": cpu, "mem": mem, "disk": disk})

        # Add objects from picar sonar
        picar = snapshot.get("picar", {})
        dist = picar.get("sonar_distance_cm")
        if dist is not None:
            self.memory.add_object(WorldObject(
                id="nearest_obstacle",
                label="obstacle",
                position={"distance_cm": dist, "angle": 0},
                confidence=0.9 if dist < 100 else 0.6,
                source="picar_sonar",
            ))

        # Events for thresholds
        if cpu is not None and cpu > 90:
            self.memory.add_event("cpu_high", "brainstem", "warning", {"cpu": cpu})
        if disk is not None and disk > 90:
            self.memory.add_event("disk_full", "brainstem", "critical", {"disk": disk})
        if mem is not None and mem > 95:
            self.memory.add_event("memory_full", "brainstem", "critical", {"mem": mem})
        if not snapshot.get("network", {}).get("gateway_reachable", True):
            self.memory.add_event("network_down", "brainstem", "critical", {})
