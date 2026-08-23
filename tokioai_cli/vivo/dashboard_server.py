"""
TokioAI Vivo - Dashboard Server
WebSocket + HTTP server for real-time dashboard.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import websockets
    from websockets.server import serve
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False


class DashboardServer:
    """Serves dashboard HTML and streams live data via WebSocket."""

    def __init__(self, config, memory, token_guard, host: str = "0.0.0.0", port: int = 8765):
        self.cfg = config
        self.memory = memory
        self.token_guard = token_guard
        self.host = host
        self.port = port
        self._server = None
        self._clients = set()
        self._last_reasoning: Optional[Dict] = None

    def set_last_reasoning(self, reasoning: Dict[str, Any]):
        self._last_reasoning = reasoning

    def get_state(self) -> Dict[str, Any]:
        from .world_memory import WorldMemory
        from .token_guard import TokenGuard

        pid = None
        if self.cfg.pidfile.exists():
            try:
                pid = int(self.cfg.pidfile.read_text().strip())
            except Exception:
                pass

        return {
            "status": "alive" if pid else "offline",
            "pid": pid,
            "uptime_s": time.time() - self._start_time if hasattr(self, '_start_time') else 0,
            "ticks": getattr(self, '_tick_count', 0),
            "health": self.memory.health_score(),
            "autonomy": self.cfg.autonomy,
            "dry_run": self.cfg.dry_run,
            "objective": self.cfg.objective,
            "gear2_model": self.cfg.gear2_model,
            "gear3_model": self.cfg.gear3_model,
            "token_summary": self.token_guard.summary(),
            "recent_events": self.memory.recent_events(20),
            "active_objects": [
                {
                    "label": o.label,
                    "confidence": o.confidence,
                    "staleness_s": round(o.staleness(), 1),
                    "source": o.source,
                    "position": o.position,
                }
                for o in self.memory.active_objects()
            ],
            "learned_rules": [
                {"id": r.id, "condition": r.condition, "action": r.action, "hits": r.hit_count}
                for r in self.memory.state.rules if r.source == "learned"
            ],
            "last_reasoning": self._last_reasoning,
        }

    async def _ws_handler(self, websocket, path):
        self._clients.add(websocket)
        try:
            async for message in websocket:
                # Client can request specific data
                if message == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
        finally:
            self._clients.remove(websocket)

    async def _broadcast_loop(self):
        while True:
            if self._clients:
                state = self.get_state()
                msg = json.dumps(state, default=str)
                await asyncio.gather(
                    *[client.send(msg) for client in self._clients],
                    return_exceptions=True
                )
            await asyncio.sleep(2.0)

    async def _http_handler(self, reader, writer):
        request = await reader.read(4096)
        request_str = request.decode()

        if "GET / " in request_str or "GET /index.html" in request_str:
            # Serve dashboard HTML
            html_path = Path(__file__).parent / "templates" / "dashboard_ws.html"
            if html_path.exists():
                body = html_path.read_text()
                response = f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n\r\n{body}"
            else:
                response = "HTTP/1.1 404 Not Found\r\n\r\nDashboard not found"
        elif "GET /api/state " in request_str:
            body = json.dumps(self.get_state(), default=str)
            response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        else:
            response = "HTTP/1.1 404 Not Found\r\n\r\n"

        writer.write(response.encode())
        await writer.drain()
        writer.close()

    async def run_async(self):
        self._start_time = time.time()
        self._tick_count = 0

        # Start WebSocket server
        ws_server = await serve(self._ws_handler, self.host, self.port)

        # Start HTTP server
        http_server = await asyncio.start_server(self._http_handler, self.host, self.port + 1)

        print(f"[DASHBOARD] WebSocket: ws://{self.host}:{self.port}")
        print(f"[DASHBOARD] HTTP: http://{self.host}:{self.port + 1}")

        # Start broadcast loop
        await asyncio.gather(
            ws_server.wait_closed(),
            http_server.wait_closed(),
            self._broadcast_loop(),
        )

    def run(self):
        if not WEBSOCKETS_AVAILABLE:
            print("[DASHBOARD] websockets not installed. Install: pip install websockets")
            return
        asyncio.run(self.run_async())


def start_dashboard_in_thread(config, memory, token_guard, port: int = 8765):
    """Start dashboard in a background thread."""
    import threading
    server = DashboardServer(config, memory, token_guard, port=port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server
