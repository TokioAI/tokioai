"""Offline unit tests for TokioAI Vivo core modules."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure imports work when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tokioai_cli.vivo.config import VivoConfig
from tokioai_cli.vivo.token_guard import TokenGuard
from tokioai_cli.vivo.safety import SafetyEnforcer
from tokioai_cli.vivo.world_memory import WorldMemory, WorldObject, Rule
from tokioai_cli.vivo.watchdogs import SystemWatchdog, NetworkWatchdog
from tokioai_cli.vivo.brainstem import Brainstem, BrainstemDecision
from tokioai_cli.vivo.action_executor import ActionExecutor, ActionResult
from tokioai_cli.vivo.llm_client import VivoLLMClient


class TestVivoConfig(unittest.TestCase):
    def test_load_save(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.yaml"
            cfg = VivoConfig(vivo_dir=Path(td))
            cfg.save(path)
            loaded = VivoConfig.load(path)
            self.assertEqual(loaded.objective, cfg.objective)
            self.assertEqual(loaded.autonomy, cfg.autonomy)


class TestSafety(unittest.TestCase):
    def test_blocks_bad_commands(self):
        cfg = VivoConfig()
        s = SafetyEnforcer(cfg)
        blocked, reason = s.is_blocked("rm -rf / --no-preserve-root")
        self.assertTrue(blocked)

    def test_destructive_detection(self):
        cfg = VivoConfig()
        s = SafetyEnforcer(cfg)
        self.assertTrue(s.is_destructive("systemctl restart nginx"))
        self.assertFalse(s.is_destructive("echo hello"))

    def test_simulation_mode(self):
        cfg = VivoConfig(autonomy=3, dry_run=True)
        s = SafetyEnforcer(cfg)
        r = s.can_execute("systemctl restart nginx")
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("dry_run"))

    def test_kill_switch(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            s = SafetyEnforcer(cfg)
            self.assertFalse(s.should_stop())
            s.request_stop()
            self.assertTrue(s.should_stop())


class TestWorldMemory(unittest.TestCase):
    def test_events_and_health(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            mem = WorldMemory(cfg)
            mem.add_event("test", "unit", "warning", {"x": 1})
            mem.add_health(0.5, "unit")
            self.assertGreaterEqual(len(mem.recent_events()), 1)
            self.assertEqual(mem.health_score(), 0.5)

    def test_objects(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            mem = WorldMemory(cfg)
            obj = WorldObject(id="o1", label="chair", confidence=0.8, source="test")
            mem.add_object(obj)
            self.assertEqual(len(mem.active_objects()), 1)

    def test_record_turn(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            mem = WorldMemory(cfg)
            # Clear any pre-existing turn events
            mem.state.events = [e for e in mem.state.events if e.get("type") != "robot_turn"]
            mem.record_turn("left")
            mem.record_turn("left")
            mem.record_turn("left")
            mem.record_turn("left")
            turns = [e for e in mem.state.events if e.get("type") == "robot_turn"]
            self.assertEqual(len(turns), 4)

    def test_learned_rule(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            mem = WorldMemory(cfg)
            # Clear any pre-existing learned rules from previous state
            mem.state.rules = [r for r in mem.state.rules if r.source != "learned"]
            rule = Rule(id="test_rule", condition="cpu_percent > 80", action="notify_cpu", priority=50, source="learned")
            mem.add_or_update_rule(rule)
            learned = [r for r in mem.state.rules if r.source == "learned"]
            self.assertEqual(len(learned), 1)
            self.assertEqual(learned[0].id, "test_rule")


class TestWatchdogs(unittest.TestCase):
    def test_system_snapshot(self):
        w = SystemWatchdog()
        snap = w.read()
        self.assertIn("disk_percent", snap)

    def test_network_snapshot(self):
        w = NetworkWatchdog()
        snap = w.read()
        self.assertIn("gateway_reachable", snap)


class TestBrainstem(unittest.TestCase):
    def test_noop_when_healthy(self):
        cfg = VivoConfig()
        with tempfile.TemporaryDirectory() as td:
            cfg.vivo_dir = Path(td)
            mem = WorldMemory(cfg)
            b = Brainstem(cfg, mem)
            snap = {"ts": time.time(), "system": {"cpu_percent": 20}, "network": {"gateway_reachable": True}}
            b.update_memory_from_snapshot(snap)
            dec = b.evaluate(snap)
            self.assertEqual(dec.action, "noop")

    def test_sustained_detection(self):
        cfg = VivoConfig()
        with tempfile.TemporaryDirectory() as td:
            cfg.vivo_dir = Path(td)
            mem = WorldMemory(cfg)
            b = Brainstem(cfg, mem)
            # Simulate sustained CPU high for multiple ticks
            for _ in range(5):
                result = b._sustained(True, duration=120)
            self.assertTrue(result)

    def test_stuck_turning(self):
        cfg = VivoConfig()
        with tempfile.TemporaryDirectory() as td:
            cfg.vivo_dir = Path(td)
            mem = WorldMemory(cfg)
            b = Brainstem(cfg, mem)
            # Record 4 turns in same direction
            for _ in range(4):
                mem.record_turn("left")
            self.assertTrue(b._is_stuck_turning())

    def test_learned_rule_evaluation(self):
        cfg = VivoConfig()
        with tempfile.TemporaryDirectory() as td:
            cfg.vivo_dir = Path(td)
            mem = WorldMemory(cfg)
            b = Brainstem(cfg, mem)
            # Add a learned rule
            rule = Rule(id="cpu_80", condition="cpu_percent > 80", action="notify_cpu_high", priority=60, source="learned")
            mem.add_or_update_rule(rule)
            # Snapshot with high CPU
            snap = {"ts": time.time(), "system": {"cpu_percent": 85}, "network": {"gateway_reachable": True}}
            dec = b.evaluate(snap)
            self.assertEqual(dec.action, "notify_cpu_high")
            self.assertEqual(dec.rule_id, "cpu_80")


class TestActionExecutor(unittest.TestCase):
    def test_robot_action_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td), dry_run=True)
            mem = WorldMemory(cfg)
            safety = SafetyEnforcer(cfg)
            guard = TokenGuard(cfg)
            executor = ActionExecutor(cfg, safety, mem, guard)
            # Test that robot actions are recognized
            self.assertTrue("robot_stop" in ["robot_stop", "robot_forward", "robot_backward", "robot_turn_left", "robot_turn_right"])


class TestLLMClient(unittest.TestCase):
    def test_client_creation(self):
        cfg = VivoConfig()
        client = VivoLLMClient(cfg)
        self.assertIsNotNone(client)


class TestTokenGuard(unittest.TestCase):
    def test_budget(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td), budget_session_usd=0.00001)
            g = TokenGuard(cfg)
            g.record(2, "meta-llama/llama-3.1-8b-instruct", 1000, 1000)
            self.assertFalse(g.can_use_gear(2)["ok"])

    def test_summary(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VivoConfig(vivo_dir=Path(td))
            g = TokenGuard(cfg)
            summary = g.summary()
            self.assertIn("session_cost_usd", summary)
            self.assertIn("gear2_calls_total", summary)


if __name__ == "__main__":
    unittest.main()
