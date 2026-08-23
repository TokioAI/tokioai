#!/usr/bin/env python3
"""TokioAI CLI - Comprehensive End-to-End Test Suite"""
import os, sys

os.environ.setdefault('GEMINI_API_KEY', 'AIzaSyCzCFB04QQaaupJF_fake_test_key_12345')
os.environ.setdefault('TOKIOAI_PROVIDER', 'kimi')
os.environ.setdefault('KIMI_API_KEY', 'sk-test-fake-key-for-testing-12345678')
os.environ.setdefault('TOKIOAI_MODEL', 'k2.7')

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")

print("=" * 60)
print("TOKIOAI CLI - COMPREHENSIVE END-TO-END TEST")
print("=" * 60)

# ═══ 1: Module Imports ═══
print("\n[1] MODULE IMPORTS")
try:
    from tokioai_cli import __version__
    check("__version__", __version__, __version__)
    from tokioai_cli.safety import default_guard, SafetyReport
    from tokioai_cli.security_config import decide_provider, validate_key_for_provider, ProviderDecision, audit_security_event
    from tokioai_cli.memory_optimizer import build_optimized_context, get_memory_stats, _compute_relevance
    from tokioai_cli.router import DualModelRouter, classify_complexity, PRICING
    from tokioai_cli.ops import TokioOps, resolve_model, list_aliases, execute_tool, TOOLS, MODEL_ALIASES
    check("All imports", True)
except Exception as e:
    check("All imports", False, str(e))
    sys.exit(1)

# ═══ 2: Model Aliases ═══
print("\n[2] MODEL ALIASES")
critical_aliases = {
    'k3': 'kimi-k3', 'k27': 'kimi-k2.7-code', 'k2.7': 'kimi-k2.7-code',
    'dual': 'dual:kimi-k2.7-code+kimi-k3',
    'dual-or': 'dual:moonshotai/kimi-k2.7-code+moonshotai/kimi-k3',
    'opus': 'claude-opus-4-6', 'sonnet': 'claude-sonnet-4-6',
    'flash': 'gemini-2.5-flash', 'gemini3': 'gemini-3-flash-preview',
    'gpt': 'gpt-4o', 'or-claude': 'anthropic/claude-sonnet-4',
    'or-k3': 'moonshotai/kimi-k3', 'or-k27': 'moonshotai/kimi-k2.7-code',
    'kimi-code': 'kimi-k2.7-code', 'kimi-k3': 'kimi-k3',
}
alias_fails = 0
for alias, expected in critical_aliases.items():
    result = resolve_model(alias)
    if result != expected:
        print(f"  FAIL: {alias} -> {result} (expected {expected})")
        alias_fails += 1
check(f"Alias resolution ({len(critical_aliases)} aliases)", alias_fails == 0, f"{alias_fails} failures")

from collections import Counter
dupes = [k for k, v in Counter(list(MODEL_ALIASES.keys())).items() if v > 1]
check("No duplicate aliases", len(dupes) == 0, f"duplicates: {dupes}")

# ═══ 3: Router ═══
print("\n[3] DUAL-MODEL ROUTER")
router = DualModelRouter()
simple_queries = ['ls -la', 'git push', 'install nginx', 'create file test.py', 'reinicia nginx']
complex_queries = ['design zero-trust architecture', 'analyze security vulnerabilities in depth',
                   'explain DNS amplification attacks', 'compare TCP vs UDP for gaming']
routing_ok = True
for q in simple_queries:
    m = router.route(q)
    if m != router.primary_model:
        print(f"  FAIL: simple '{q}' routed to secondary")
        routing_ok = False
for q in complex_queries:
    m = router.route(q)
    if m != router.secondary_model:
        print(f"  FAIL: complex '{q}' routed to primary")
        routing_ok = False
check(f"Routing accuracy ({len(simple_queries) + len(complex_queries)} queries)", routing_ok)
check("Router pricing", "kimi-k2.7-code" in PRICING and "kimi-k3" in PRICING)

# ═══ 4: Safety Layer ═══
print("\n[4] SAFETY LAYER")
guard = default_guard()
clean_texts = [
    'Create /home/user/test.py', 'Run docker ps', 'model kimi-k2.7-code',
    'The function returns True', 'gemini-2.5-flash is cheap',
    'Install package with pip install openai',
]
fp = 0
for t in clean_texts:
    _, report = guard.sanitize(t)
    if report and report.redactions:
        print(f"  FALSE POSITIVE: '{t}' -> {[r.category for r in report.redactions]}")
        fp += 1
check(f"No false positives ({len(clean_texts)} clean texts)", fp == 0, f"{fp} false positives")

secret_texts = [
    'sk-ant-api03-FAKEKEY123456789012345678901234567890',
    'password=SuperSecret123!',
    'AIzaSyCzCFB04QQaaupJF_test_1234567890123',
    'sk-or-v1-FAKEKEY123456789012345678901234567890test1234567890',
]
tp = 0
for t in secret_texts:
    _, report = guard.sanitize(t)
    if report and report.redactions:
        tp += 1
check(f"Secret detection ({len(secret_texts)} secrets)", tp == len(secret_texts), f"only {tp}/{len(secret_texts)} detected")

# ═══ 5: Security Config ═══
print("\n[5] SECURITY CONFIG")
valid_keys = [
    ('anthropic', 'sk-ant-api03-test1234567890test1234567890test12'),
    ('openai', 'sk-proj-test1234567890test1234567890'),
    ('gemini', 'AIzaSyCzCFB04QQaaupJF_test_123456789'),
    ('kimi', 'sk-test1234567890test1234567890'),
    ('openrouter', 'sk-or-v1-test1234567890test12345678901234567890test1234567890'),
]
for prov, key in valid_keys:
    ok, err = validate_key_for_provider(prov, key)
    check(f"Valid {prov} key", ok, err or "")

invalid_keys = [
    ('openrouter', 'sk-wrong-prefix-12345678', 'should reject non-openrouter prefix'),
    ('anthropic', 'short', 'too short'),
]
for prov, key, reason in invalid_keys:
    ok, err = validate_key_for_provider(prov, key)
    check(f"Reject invalid {prov} key ({reason})", not ok)

# ═══ 6: Memory Optimizer ═══
print("\n[6] MEMORY OPTIMIZER")
stats = get_memory_stats()
check("Memory stats available", stats["total_sections"] >= 0)
print(f"  Hot: {stats['hot_sections']}, Cold: {stats['cold_sections']}, Reduction: {stats['reduction_pct']:.1f}%")

# Version penalty fix
score_v6 = _compute_relevance('TokioNav v6 deploy', 'Important navigation system', None)
score_abandoned = _compute_relevance('abandoned old project', 'Not used anymore', None)
check("Version names not penalized", score_v6 > score_abandoned,
      f"v6={score_v6}, abandoned={score_abandoned}")

# ═══ 7: Tool Execution ═══
print("\n[7] TOOL EXECUTION")
result = execute_tool('execute_local', {'command': 'echo TOKIOAI_TEST_OK'})
check("execute_local", 'TOKIOAI_TEST_OK' in result, result[:50])

result = execute_tool('read_file', {'path': '/home/mrmoz/tokioai/tokioai_cli/__init__.py'})
check("read_file", '__version__' in result)

result = execute_tool('memory', {'action': 'read'})
check("memory read", isinstance(result, str))

result = execute_tool('task', {'action': 'list'})
check("task list", isinstance(result, str))

# ═══ 8: Cost Tracking ═══
print("\n[8] COST TRACKING")
from tokioai_cli.interactive import CostTracker
ct = CostTracker()
ct.session_cost_usd = 0
ct.model_usage = {}
ct.session_input_tokens = 0
ct.session_output_tokens = 0

ct.add_usage('kimi-k2.7-code', 10000, 5000)
expected_k27 = (10000 * 0.71 + 5000 * 3.50) / 1_000_000
check("K2.7-code cost", abs(ct.session_cost_usd - expected_k27) < 0.0001,
      f"got {ct.session_cost_usd:.6f}, expected {expected_k27:.6f}")

ct.add_usage('kimi-k3', 10000, 5000)
expected_k3 = (10000 * 3.0 + 5000 * 15.0) / 1_000_000
total = expected_k27 + expected_k3
check("K3 cost (cumulative)", abs(ct.session_cost_usd - total) < 0.001,
      f"got {ct.session_cost_usd:.6f}, expected {total:.6f}")
print(f"  K2.7 per call: ${expected_k27:.4f}, K3 per call: ${expected_k3:.4f}, Total: ${total:.4f}")

# ═══ 9: Provider Detection ═══
print("\n[9] PROVIDER DETECTION")
d1 = decide_provider('kimi', 'k2.7', {
    'KIMI_API_KEY': 'sk-test12345678901234567890',
    'VERTEX_PROJECT': None, 'ANTHROPIC_API_KEY': None,
    'OPENAI_API_KEY': None, 'GEMINI_API_KEY': None,
    'MOONSHOT_API_KEY': None, 'OPENROUTER_API_KEY': None, 'OLLAMA_HOST': None,
})
check("Explicit kimi provider", d1.provider == 'kimi', d1.provider)

d2 = decide_provider('', '', {
    'KIMI_API_KEY': 'sk-test12345678901234567890',
    'VERTEX_PROJECT': None, 'ANTHROPIC_API_KEY': None,
    'OPENAI_API_KEY': None, 'GEMINI_API_KEY': None,
    'MOONSHOT_API_KEY': None, 'OPENROUTER_API_KEY': None, 'OLLAMA_HOST': None,
})
check("Auto-detect kimi", d2.provider == 'kimi', d2.provider)

d3 = decide_provider('', '', {
    'KIMI_API_KEY': None, 'VERTEX_PROJECT': None,
    'ANTHROPIC_API_KEY': None, 'OPENAI_API_KEY': None,
    'GEMINI_API_KEY': 'AIzaSyCzCFB04QQaaupJF_test_123456789',
    'MOONSHOT_API_KEY': None, 'OPENROUTER_API_KEY': None, 'OLLAMA_HOST': None,
})
check("Auto-detect gemini", d3.provider == 'gemini', d3.provider)

# ═══ 10: File Completeness ═══
print("\n[10] FILE COMPLETENESS")
required = [
    'tokioai_cli/__init__.py', 'tokioai_cli/__main__.py',
    'tokioai_cli/ops.py', 'tokioai_cli/interactive.py',
    'tokioai_cli/router.py', 'tokioai_cli/safety.py',
    'tokioai_cli/security_config.py', 'tokioai_cli/memory_optimizer.py',
    'tokioai_cli/.env.example', 'README.md',
]
missing = [f for f in required if not os.path.exists(os.path.join('/home/mrmoz/tokioai', f))]
check(f"All {len(required)} files present", len(missing) == 0, f"missing: {missing}")

# ═══ Summary ═══
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} PASSED, {failed} FAILED")
if failed == 0:
    print("STATUS: ALL TESTS PASS - READY FOR PUSH")
else:
    print("STATUS: FIXES NEEDED")
print("=" * 60)
if __name__ == "__main__":
    sys.exit(0 if failed == 0 else 1)
