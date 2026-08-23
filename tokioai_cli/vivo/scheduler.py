"""
TokioAI Vivo - Scheduler
Simple scheduler for periodic tasks and telemetry.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List


class ScheduledTask:
    def __init__(self, name: str, interval: float, fn: Callable, last_run: float = 0.0):
        self.name = name
        self.interval = interval
        self.fn = fn
        self.last_run = last_run


class Scheduler:
    def __init__(self):
        self.tasks: List[ScheduledTask] = []

    def add(self, name: str, interval: float, fn: Callable):
        self.tasks.append(ScheduledTask(name, interval, fn))

    def tick(self) -> Dict[str, any]:
        now = time.time()
        results = {}
        for t in self.tasks:
            if now - t.last_run >= t.interval:
                try:
                    results[t.name] = t.fn()
                except Exception as e:
                    results[t.name] = {"error": str(e)}
                t.last_run = now
        return results
