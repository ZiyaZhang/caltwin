"""Tests for domain/utils/text.py — extract_keywords."""

from twin_runtime.domain.utils.text import extract_keywords


def test_empty_input():
    assert extract_keywords("") == []
    # "  ".split() → [] so this returns [] via the keyword filter, not the
    # `if not text` guard (whitespace-only strings are truthy in Python).
    assert extract_keywords("  ") == []


def test_english_keywords():
    result = extract_keywords("should we use Redis or Memcached for caching")
    assert "should" in result
    assert "Redis" in result
    assert "Memcached" in result
    assert "caching" in result
    # Short words filtered out
    assert "we" not in result
    assert "or" not in result


def test_cjk_bigrams():
    result = extract_keywords("数据库选择")
    # Should produce bigrams: 数据, 据库, 库选, 选择
    assert "数据" in result
    assert "据库" in result
    assert "选择" in result


def test_mixed_cjk_english():
    result = extract_keywords("用 Redis 还是 PostgreSQL 做数据库")
    assert "Redis" in result
    assert "PostgreSQL" in result
    assert "数据" in result


def test_max_keywords_cap():
    long_text = " ".join(f"word{i}" for i in range(50))
    result = extract_keywords(long_text, max_keywords=5)
    assert len(result) <= 5


def test_default_max_keywords():
    long_text = " ".join(f"word{i}" for i in range(50))
    result = extract_keywords(long_text)
    assert len(result) <= 20
