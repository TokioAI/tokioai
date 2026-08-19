#!/usr/bin/env python3
"""
Tests for TokioAI Dual-Model Router.

Run with: python -m pytest tests/test_router.py -v
"""
import pytest
from tokioai_cli.router import (
    classify_complexity,
    DualModelRouter,
    RouterStats,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    PRICING,
)


# ────────────────────────────────────────────────────────
# classify_complexity() tests
# ────────────────────────────────────────────────────────

class TestClassifyComplexity:
    """Test the complexity classifier."""

    # ── Simple queries (should score < 50) ──

    @pytest.mark.parametrize("query", [
        "run ls -la",
        "install nginx",
        "restart the docker container",
        "show me the logs",
        "cat /etc/hosts",
        "pip install flask",
        "git push origin main",
        "check the status of the service",
        "create a file called test.py",
        "fix this bug",
        "find all .py files",
        "ssh into the server",
        "curl localhost:8080",
        "docker ps",
        "kubectl get pods",
    ])
    def test_simple_english(self, query):
        score, reason = classify_complexity(query)
        assert score < 50, f"Expected SIMPLE (<50) for '{query}', got score={score} reason={reason}"

    @pytest.mark.parametrize("query", [
        "ejecuta ls -la",
        "instala nginx",
        "reinicia el contenedor",
        "muestra los logs",
        "busca archivos .py",
        "crea un archivo test.py",
        "borra el archivo viejo",
        "abre el puerto 80",
        "revisa el estado del servicio",
    ])
    def test_simple_spanish(self, query):
        score, reason = classify_complexity(query)
        assert score < 50, f"Expected SIMPLE (<50) for '{query}', got score={score} reason={reason}"

    # ── Complex queries (should score >= 50) ──

    @pytest.mark.parametrize("query", [
        "design a microservice architecture for a payment processing system",
        "explain the security implications of running containers as root",
        "compare Kubernetes vs Docker Swarm for our production deployment",
        "analyze this code for vulnerabilities and suggest hardening measures",
        "what are the trade-offs between monolith and microservices",
        "walk me through the incident response process step by step",
        "how does the Linux kernel handle memory management in depth",
        "design a threat model for our API gateway",
        "review this code for race conditions and deadlocks",
        "build a comprehensive security audit framework from scratch",
        "explain why this distributed system fails under high load and how to fix it",
    ])
    def test_complex_english(self, query):
        score, reason = classify_complexity(query)
        assert score >= 50, f"Expected COMPLEX (>=50) for '{query}', got score={score} reason={reason}"

    @pytest.mark.parametrize("query", [
        "explícame cómo funciona la escalación de privilegios en Linux",
        "analiza las vulnerabilidades de seguridad de este sistema",
        "compara las ventajas y desventajas de usar Redis vs Memcached",
        "diseña una arquitectura para un sistema de pagos distribuido",
        "cuál es la mejor manera de proteger una API contra ataques",
    ])
    def test_complex_spanish(self, query):
        score, reason = classify_complexity(query)
        assert score >= 50, f"Expected COMPLEX (>=50) for '{query}', got score={score} reason={reason}"

    # ── Edge cases ──

    def test_empty_string(self):
        score, reason = classify_complexity("")
        assert 0 <= score <= 100

    def test_single_word(self):
        score, reason = classify_complexity("help")
        assert score < 50  # single word = simple

    def test_very_long_message(self):
        long_msg = "explain " + " ".join(["word"] * 120)
        score, reason = classify_complexity(long_msg)
        assert "long_query" in reason or "very_long_query" in reason

    def test_code_block_is_simple(self):
        query = "fix this:\n```python\ndef foo():\n  return bar\n```"
        score, reason = classify_complexity(query)
        assert score < 50, "Code blocks should bias toward simple (K2.7-code)"

    def test_multiple_questions_is_complex(self):
        query = "what is the best database? how do I scale it? what about sharding?"
        score, reason = classify_complexity(query)
        assert "multi_question" in reason

    def test_conversation_depth_bias(self):
        """Deep conversation follow-ups should be simpler."""
        score_shallow, _ = classify_complexity("do it", conversation_depth=0)
        score_deep, _ = classify_complexity("do it", conversation_depth=10)
        assert score_deep <= score_shallow

    def test_post_tool_bias(self):
        """After tool results, next message is usually a refinement."""
        score_no_tool, _ = classify_complexity("analyze this output", has_tool_results=False)
        score_with_tool, _ = classify_complexity("analyze this output", has_tool_results=True)
        assert score_with_tool <= score_no_tool

    def test_score_bounds(self):
        """Score should always be 0-100."""
        # Try to force extreme values
        extreme_simple = "run ls cat grep find install pip git docker kubectl"
        score_s, _ = classify_complexity(extreme_simple)
        assert 0 <= score_s <= 100

        extreme_complex = (
            "design a comprehensive microservice architecture with trade-offs "
            "comparing scalability implications of distributed systems with "
            "vulnerability analysis and threat modeling step by step from scratch "
            "including security audit and incident response strategy? "
            "what are the consequences? how does it work in depth?"
        )
        score_c, _ = classify_complexity(extreme_complex)
        assert 0 <= score_c <= 100

    def test_returns_tuple(self):
        result = classify_complexity("test")
        assert isinstance(result, tuple)
        assert len(result) == 2
        score, reason = result
        assert isinstance(score, int)
        assert isinstance(reason, str)


# ────────────────────────────────────────────────────────
# RouterStats tests
# ────────────────────────────────────────────────────────

class TestRouterStats:
    """Test the stats tracking class."""

    def test_initial_state(self):
        stats = RouterStats()
        assert stats.total_calls == 0
        assert stats.primary_ratio == 0.0
        assert stats.primary_cost == 0.0
        assert stats.secondary_cost == 0.0
        assert stats.total_cost == 0.0
        assert stats.savings_estimate == 0.0

    def test_record_primary(self):
        stats = RouterStats()
        stats.record(DEFAULT_PRIMARY, 1000, 500)
        assert stats.primary_calls == 1
        assert stats.primary_input_tokens == 1000
        assert stats.primary_output_tokens == 500
        assert stats.secondary_calls == 0
        assert stats.total_calls == 1
        assert stats.primary_ratio == 1.0

    def test_record_secondary(self):
        stats = RouterStats()
        stats.record(DEFAULT_SECONDARY, 2000, 1000)
        assert stats.secondary_calls == 1
        assert stats.secondary_input_tokens == 2000
        assert stats.secondary_output_tokens == 1000
        assert stats.primary_ratio == 0.0

    def test_mixed_usage(self):
        stats = RouterStats()
        stats.record(DEFAULT_PRIMARY, 1000, 500)
        stats.record(DEFAULT_PRIMARY, 1000, 500)
        stats.record(DEFAULT_SECONDARY, 2000, 1000)
        assert stats.total_calls == 3
        assert stats.primary_calls == 2
        assert stats.secondary_calls == 1
        assert abs(stats.primary_ratio - 2/3) < 0.01

    def test_cost_calculation(self):
        stats = RouterStats()
        # 1M input tokens + 1M output tokens on primary
        stats.record(DEFAULT_PRIMARY, 1_000_000, 1_000_000)
        primary_price = PRICING[DEFAULT_PRIMARY]
        expected_cost = primary_price["input"] + primary_price["output"]  # per 1M
        assert abs(stats.primary_cost - expected_cost) < 0.01

    def test_savings_estimate(self):
        stats = RouterStats()
        # If we route 1M tokens to primary instead of secondary, we save money
        stats.record(DEFAULT_PRIMARY, 1_000_000, 1_000_000)
        assert stats.savings_estimate > 0, "Routing to cheaper model should show savings"

    def test_add_decision_capped(self):
        stats = RouterStats()
        for i in range(30):
            stats.add_decision(f"query_{i}", DEFAULT_PRIMARY, "test", 25)
        assert len(stats.last_decisions) == 20  # capped at 20


# ────────────────────────────────────────────────────────
# DualModelRouter tests
# ────────────────────────────────────────────────────────

class TestDualModelRouter:
    """Test the main router class."""

    def test_default_models(self):
        router = DualModelRouter()
        assert router.primary_model == DEFAULT_PRIMARY
        assert router.secondary_model == DEFAULT_SECONDARY
        assert router.threshold == 50

    def test_route_simple(self):
        router = DualModelRouter()
        model = router.route("run ls -la")
        assert model == DEFAULT_PRIMARY

    def test_route_complex(self):
        router = DualModelRouter()
        model = router.route(
            "design a microservice architecture for a distributed payment system "
            "with trade-offs analysis and security implications"
        )
        assert model == DEFAULT_SECONDARY

    def test_force_primary(self):
        router = DualModelRouter()
        router.force(DEFAULT_PRIMARY)
        # Even complex queries should go to primary when forced
        model = router.route("design a complex architecture with security analysis")
        assert model == DEFAULT_PRIMARY

    def test_force_secondary(self):
        router = DualModelRouter()
        router.force(DEFAULT_SECONDARY)
        # Even simple queries should go to secondary when forced
        model = router.route("run ls")
        assert model == DEFAULT_SECONDARY

    def test_force_none_restores_auto(self):
        router = DualModelRouter()
        router.force(DEFAULT_SECONDARY)
        router.force(None)  # restore auto
        model = router.route("run ls -la")
        assert model == DEFAULT_PRIMARY  # back to auto-routing

    def test_threshold_adjustment(self):
        router_low = DualModelRouter(threshold=20)
        router_high = DualModelRouter(threshold=80)
        query = "explain how this system works"
        model_low = router_low.route(query)
        model_high = router_high.route(query)
        # Lower threshold = more K3, higher threshold = more K2.7
        # At minimum the high-threshold router should not be MORE likely to use K3
        # (they might both pick the same for extreme queries)
        assert model_low == DEFAULT_SECONDARY or model_high == DEFAULT_PRIMARY

    def test_record_usage_updates_stats(self):
        router = DualModelRouter()
        router.route("run ls")
        router.record_usage(DEFAULT_PRIMARY, 100, 50)
        assert router.stats.primary_calls == 1
        assert router.stats.primary_input_tokens == 100

    def test_format_stats_no_crash(self):
        router = DualModelRouter()
        output = router.format_stats()
        assert isinstance(output, str)
        assert "Dual Router" in output

    def test_format_stats_with_data(self):
        router = DualModelRouter()
        router.route("run ls")
        router.record_usage(DEFAULT_PRIMARY, 1000, 500)
        router.route("design an architecture")
        router.record_usage(DEFAULT_SECONDARY, 2000, 1000)
        output = router.format_stats()
        assert "K2.7-code" in output or "kimi-k2.7-code" in output
        assert "K3" in output or "kimi-k3" in output
        assert "$" in output

    def test_format_badge(self):
        router = DualModelRouter()
        assert router.format_badge(DEFAULT_PRIMARY) == "K2.7"
        assert router.format_badge(DEFAULT_SECONDARY) == "K3"
        assert router.format_badge("openai/gpt-4o") == "gpt-4o"

    def test_decisions_tracked(self):
        router = DualModelRouter()
        router.route("run ls")
        router.route("design architecture with security implications")
        assert len(router.stats.last_decisions) == 2
        assert router.stats.last_decisions[0]["model"] in ("K2.7", "K3")
        assert router.stats.last_decisions[0]["score"] >= 0

    def test_custom_models(self):
        router = DualModelRouter(
            primary_model="openai/gpt-4o-mini",
            secondary_model="openai/gpt-4o",
        )
        assert router.primary_model == "openai/gpt-4o-mini"
        assert router.secondary_model == "openai/gpt-4o"


# ────────────────────────────────────────────────────────
# Integration: full routing scenarios
# ────────────────────────────────────────────────────────

class TestRoutingScenarios:
    """End-to-end routing scenarios."""

    def test_code_tasks_go_to_k27(self):
        router = DualModelRouter()
        code_queries = [
            "fix the syntax error in line 42",
            "add a try/except around this function",
            "write a Python script to parse CSV",
            "create a Dockerfile for this app",
            "install tensorflow and run the training script",
        ]
        for q in code_queries:
            model = router.route(q)
            assert model == DEFAULT_PRIMARY, f"Code task should go to K2.7: '{q}'"

    def test_security_analysis_goes_to_k3(self):
        router = DualModelRouter()
        security_queries = [
            "perform a full security audit of this infrastructure from scratch",
            "analyze these logs for signs of lateral movement and privilege escalation",
            "design a threat model for our API with attack surface analysis",
        ]
        for q in security_queries:
            model = router.route(q)
            assert model == DEFAULT_SECONDARY, f"Security analysis should go to K3: '{q}'"

    def test_devops_commands_go_to_k27(self):
        router = DualModelRouter()
        devops_queries = [
            "docker compose up -d",
            "kubectl apply -f deployment.yaml",
            "terraform plan",
            "ansible-playbook deploy.yml",
            "systemctl restart nginx",
        ]
        for q in devops_queries:
            model = router.route(q)
            assert model == DEFAULT_PRIMARY, f"DevOps command should go to K2.7: '{q}'"

    def test_cost_tracking_accuracy(self):
        """Verify cost tracking math is correct."""
        router = DualModelRouter()
        # Simulate 7 K2.7 calls + 3 K3 calls (typical 70/30 split)
        for _ in range(7):
            router.route("run ls")
            router.record_usage(DEFAULT_PRIMARY, 1000, 500)
        for _ in range(3):
            router.route("design a complex distributed architecture with trade-offs")
            router.record_usage(DEFAULT_SECONDARY, 3000, 1500)

        # Verify costs
        p_k27 = PRICING[DEFAULT_PRIMARY]
        p_k3 = PRICING[DEFAULT_SECONDARY]

        expected_k27_cost = (7 * 1000 * p_k27["input"] + 7 * 500 * p_k27["output"]) / 1_000_000
        expected_k3_cost = (3 * 3000 * p_k3["input"] + 3 * 1500 * p_k3["output"]) / 1_000_000

        assert abs(router.stats.primary_cost - expected_k27_cost) < 0.0001
        assert abs(router.stats.secondary_cost - expected_k3_cost) < 0.0001
        assert router.stats.savings_estimate > 0

    def test_70_30_split_natural(self):
        """A diverse set of queries should roughly split 60-80% to K2.7."""
        router = DualModelRouter()
        queries = [
            # Simple (should go to K2.7)
            "run ls", "install python3", "show me disk usage",
            "restart nginx", "check docker status", "git pull",
            "create a test file", "cat /var/log/syslog", "pip install flask",
            "grep error in logs", "find large files", "ssh to server",
            "curl the API", "fix this typo", "add import os",
            "delete old backups", "list running containers", "ping google.com",
            # Complex (should go to K3)
            "design a scalable microservice architecture",
            "explain the security implications of this vulnerability",
            "compare monolith vs microservices trade-offs",
            "analyze this system for race conditions and deadlocks",
            "walk me through a comprehensive incident response plan from scratch",
            "what are the implications of running this in production",
            "design a threat model for our distributed system",
        ]
        results = [router.route(q) for q in queries]
        k27_count = results.count(DEFAULT_PRIMARY)
        ratio = k27_count / len(queries)
        assert 0.55 <= ratio <= 0.85, f"Expected 55-85% K2.7, got {ratio*100:.0f}%"
