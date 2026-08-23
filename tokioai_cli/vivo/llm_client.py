"""
TokioAI Vivo - LLM Client
Simple token-efficient LLM caller for Gear 2/3.
Primary: OpenRouter (Kimi models) OR Moonshot AI native (kimi-k3, etc.).
Fallback: reuse TokioOps if provider is vertex/anthropic/openai/gemini/kimi.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Tuple


class VivoLLMClient:
    """Minimal LLM client optimized for short structured prompts."""

    def __init__(self, config):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self._session = None
        self._tokio_ops = None

    def _client(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _openrouter_key(self) -> Optional[str]:
        key = os.getenv("OPENROUTER_API_KEY")
        if key and key.startswith("sk-or-"):
            return key
        # Check Kimi/Moonshot key that might actually be OpenRouter
        for kvar in ("KIMI_API_KEY", "MOONSHOT_API_KEY"):
            k = os.getenv(kvar, "")
            if k.startswith("sk-or-"):
                return k
        return key

    def _call_openrouter(self, model: str, messages: List[Dict], temperature: float = 0.2, max_tokens: int = 1024) -> Tuple[str, int, int]:
        import requests
        key = self._openrouter_key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tokioai.local",
            "X-Title": "TokioAI Vivo",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        r = self._client().post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content") or ""
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        out_tok = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
        return text.strip(), in_tok, out_tok

    def _call_tokio_ops(self, model: str, prompt: str) -> Tuple[str, int, int]:
        """Fallback via TokioOps. Returns text and estimated tokens."""
        if self._tokio_ops is None:
            from tokioai_cli.ops import TokioOps, resolve_model
            resolved = resolve_model(model)
            self._tokio_ops = TokioOps(provider=self.cfg.provider, model=resolved)
        # We don't have direct token counts from TokioOps easily, so estimate.
        text = self._tokio_ops.chat(prompt, max_rounds=1)
        in_tok = len(prompt) // 4
        out_tok = len(text) // 4
        return text, in_tok, out_tok

    def call(self, gear: int, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 1024) -> Dict[str, any]:
        model = self.cfg.effective_model(gear)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        start = time.time()
        provider = self.cfg.provider.lower()

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                if provider in ("openrouter", "or") or "/" in model or model.startswith("moonshotai/"):
                    text, in_tok, out_tok = self._call_openrouter(model, messages, temperature, max_tokens)
                else:
                    full_prompt = system_prompt + "\n\n" + user_prompt
                    text, in_tok, out_tok = self._call_tokio_ops(model, full_prompt)
                latency = round(time.time() - start, 2)
                return {
                    "ok": True,
                    "text": text,
                    "model": model,
                    "gear": gear,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "latency_s": latency,
                    "attempt": attempt + 1,
                }
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(x in error_msg.lower() for x in ["rate limit", "timeout", "connection", "429", "502", "503", "overloaded"])
                if attempt < max_retries - 1 and is_retryable:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                return {
                    "ok": False,
                    "error": error_msg,
                    "model": model,
                    "gear": gear,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_s": round(time.time() - start, 2),
                    "attempts": attempt + 1,
                }

    def call_structured(self, gear: int, system_prompt: str, user_prompt: str, schema_hint: str = "Respond ONLY with a valid JSON object. No markdown, no explanation.", max_tokens: int = 1200) -> Dict[str, any]:
        full_system = system_prompt.strip() + "\n" + schema_hint
        result = self.call(gear, full_system, user_prompt, temperature=0.1, max_tokens=max_tokens)
        if not result["ok"]:
            return result
        text = result["text"]
        # Strip markdown fences
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
            result["parsed"] = parsed
        except Exception as e:
            result["parsed"] = None
            result["parse_error"] = str(e)
        return result
