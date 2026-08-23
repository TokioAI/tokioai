"""
TokioAI Vivo - Watchdogs
Local sensor collectors: system, network, services, PiCar, TokioNav.
All zero-token functions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _run(cmd: str, timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", s)) if s else default
    except Exception:
        return default


class SystemWatchdog:
    def read(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time()}
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            load1, load5, load15 = os.getloadavg()
            data.update({
                "cpu_percent": round(cpu, 1),
                "memory_percent": round(mem.percent, 1),
                "memory_available_mb": round(mem.available / (1024 * 1024), 1),
                "disk_percent": round(disk.percent, 1),
                "disk_free_gb": round(disk.free / (1024 ** 3), 2),
                "load1": round(load1, 2),
                "load5": round(load5, 2),
                "load15": round(load15, 2),
                "boot_time": psutil.boot_time(),
            })
        except Exception as e:
            data["error"] = str(e)
            # Fallback to basic tools
            data["cpu_percent"] = None
            data["memory_percent"] = None
            data["disk_percent"] = _to_float(_run("df / | tail -1 | awk '{print $5}'"), 0.0)
            data["disk_free_gb"] = _to_float(_run("df -BG / | tail -1 | awk '{print $4}'"), 0.0)
            data["load1"] = _to_float(_run("uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | tr -d ','"), 0.0)
        return data


class NetworkWatchdog:
    def read(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time()}
        # Gateway ping
        try:
            gateway = _run("ip route | grep default | awk '{print $3}' | head -1")
            if gateway:
                ping_out = subprocess.run(f"ping -c 1 -W 2 {gateway}", shell=True, capture_output=True, text=True, timeout=4)
                data["gateway"] = gateway
                data["gateway_reachable"] = ping_out.returncode == 0
                m = re.search(r"time=([0-9.]+)\s*ms", ping_out.stdout)
                data["gateway_latency_ms"] = round(float(m.group(1)), 2) if m else None
            else:
                data["gateway_reachable"] = False
        except Exception as e:
            data["gateway_reachable"] = False
            data["error"] = str(e)
        # Internet check (cloudflare DNS)
        try:
            inet = subprocess.run("ping -c 1 -W 2 1.1.1.1", shell=True, capture_output=True, text=True, timeout=4)
            data["internet_reachable"] = inet.returncode == 0
        except Exception:
            data["internet_reachable"] = False
        # Interface list
        try:
            import psutil
            data["interfaces"] = {k: {"ip": v[0].address if v else None} for k, v in psutil.net_if_addrs().items()}
        except Exception:
            data["interfaces"] = {}
        return data


class ServiceWatchdog:
    def __init__(self, services: Optional[List[str]] = None):
        self.services = services or ["ssh", "docker", "homeassistant", "tokionav", "nginx"]

    def read(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time(), "services": {}}
        for svc in self.services:
            try:
                out = subprocess.run(f"systemctl is-active {svc}", shell=True, capture_output=True, text=True, timeout=3)
                active = out.returncode == 0 and "active" in out.stdout
                data["services"][svc] = {
                    "active": active,
                    "status": out.stdout.strip(),
                }
            except Exception as e:
                data["services"][svc] = {"active": False, "status": "unknown", "error": str(e)}
        return data


class PiCarWatchdog:
    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url or os.getenv("PICAR_PROXY_URL", "http://127.0.0.1:5000")

    def read(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time(), "reachable": False}
        try:
            import requests
            r = requests.get(f"{self.proxy_url}/status", timeout=3)
            if r.status_code == 200:
                data["reachable"] = True
                data["status"] = r.json() if "application/json" in r.headers.get("Content-Type", "") else r.text
            else:
                data["status"] = f"http_{r.status_code}"
        except Exception as e:
            data["error"] = str(e)
        # Sonar
        try:
            import requests
            r = requests.get(f"{self.proxy_url}/sonar", timeout=3)
            if r.status_code == 200:
                j = r.json()
                data["sonar_distance_cm"] = j.get("distance", j.get("distance_cm")) if isinstance(j, dict) else None
        except Exception:
            data["sonar_distance_cm"] = None
        return data


class TokioNavWatchdog:
    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path

    def read(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time(), "reachable": False}
        if self.state_path and self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    j = json.load(f)
                data["reachable"] = True
                data["state"] = j
            except Exception as e:
                data["error"] = str(e)
        return data


class LogWatchdog:
    def __init__(self, log_paths: Optional[List[str]] = None, patterns: Optional[List[str]] = None):
        self.log_paths = log_paths or ["/var/log/syslog", "/var/log/auth.log"]
        self.patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or ["error", "fail", "critical", "fatal"])]
        self._last_position: Dict[str, int] = {}

    def read(self, max_lines: int = 20) -> Dict[str, Any]:
        data: Dict[str, Any] = {"ts": time.time(), "matches": []}
        for path in self.log_paths:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    start = self._last_position.get(path, max(0, size - 4096))
                    if start > size:
                        start = 0
                    f.seek(start)
                    new_lines = f.readlines()
                    self._last_position[path] = size
                    for line in new_lines[-max_lines:]:
                        if any(p.search(line) for p in self.patterns):
                            data["matches"].append({"file": path, "line": line.strip()[:300]})
            except Exception as e:
                data.setdefault("errors", []).append({"file": path, "error": str(e)})
        return data


class WatchdogManager:
    """Aggregates all watchdogs into a single snapshot."""

    def __init__(self, config):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.system = SystemWatchdog()
        self.network = NetworkWatchdog()
        self.services = ServiceWatchdog()
        self.picar = PiCarWatchdog(config.picar_proxy_url) if config.enable_picar_watchdogs else None
        self.tokionav = TokioNavWatchdog(config.tokionav_state_path)
        self.logs = LogWatchdog() if config.enable_log_watchdogs else None

    def snapshot(self) -> Dict[str, Any]:
        snap: Dict[str, Any] = {"ts": time.time()}
        if self.cfg.enable_system_watchdogs:
            snap["system"] = self.system.read()
        if self.cfg.enable_network_watchdogs:
            snap["network"] = self.network.read()
        snap["services"] = self.services.read()
        if self.picar:
            snap["picar"] = self.picar.read()
        if self.cfg.tokionav_state_path:
            snap["tokionav"] = self.tokionav.read()
        if self.logs:
            snap["logs"] = self.logs.read()
        return snap
