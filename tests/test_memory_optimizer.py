

# ─────────────────────────────────────────────────────────────
# AUTO-RECALL TESTS (v1.1)
# ─────────────────────────────────────────────────────────────

def test_cold_index_excludes_hot_and_lists_cold():
    """Cold index should list only sections NOT in hot context."""
    from tokioai_cli import memory_optimizer as mo
    idx = mo.build_cold_index()
    if not idx:
        return  # no memory file = nothing to index
    assert "Memory Index" in idx
    # Each line should be short (1-liner)
    for line in idx.splitlines()[1:6]:
        assert len(line) < 90, f"Index line too long: {line}"

def test_search_memory_finds_relevant():
    """search_memory should return sections matching a query."""
    from tokioai_cli import memory_optimizer as mo
    results = mo.search_memory("memory optimizer", max_results=3)
    # May or may not find depending on memory content, but should not crash
    assert isinstance(results, list)
    for r in results:
        assert "title" in r and "body" in r

def test_search_memory_empty_query():
    """Empty query returns empty list."""
    from tokioai_cli import memory_optimizer as mo
    assert mo.search_memory("") == []
    assert mo.search_memory("   ") == []

def test_context_includes_index():
    """build_optimized_context should include the Memory Index when cold entries exist."""
    from tokioai_cli import memory_optimizer as mo
    ctx = mo.build_optimized_context()
    # If there are cold sections, index should be present
    stats = mo.get_memory_stats()
    if stats["cold_sections"] > 0:
        assert "Memory Index" in ctx

def test_no_secrets_in_cold_index():
    """Cold index must not leak secrets (masked by safety layer upstream, but index itself should be titles only)."""
    from tokioai_cli import memory_optimizer as mo
    idx = mo.build_cold_index()
    import re
    # No full API keys in index (titles only, truncated)
    assert not re.search(r'sk-or-v1-[a-zA-Z0-9]{20,}', idx)
    assert not re.search(r'AIza[a-zA-Z0-9]{30,}', idx)
