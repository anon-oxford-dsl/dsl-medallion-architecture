from __future__ import annotations

import pytest

from medallion.frontend.graph import detect_cycle, topological_order


def test_detect_cycle_returns_none_for_dag():
    names = ["bronze", "silver", "gold"]
    deps = {"silver": ["bronze"], "gold": ["silver"]}
    assert detect_cycle(names, deps) is None


def test_detect_cycle_finds_a_closed_walk():
    names = ["a", "b", "c"]
    deps = {"a": ["c"], "b": ["a"], "c": ["b"]}
    cycle = detect_cycle(names, deps)
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}


def test_detect_cycle_ignores_unknown_dependencies():
    names = ["a", "b"]
    deps = {"b": ["a"], "a": ["ghost"]}
    assert detect_cycle(names, deps) is None


def test_topological_order_respects_dependencies_and_declaration_order():
    names = ["bronze", "silver", "gold"]
    deps = {"silver": ["bronze"], "gold": ["silver"]}
    assert topological_order(names, deps) == ["bronze", "silver", "gold"]


def test_topological_order_diamond():
    names = ["raw", "a", "b", "merged"]
    deps = {"a": ["raw"], "b": ["raw"], "merged": ["a", "b"]}
    order = topological_order(names, deps)
    assert order.index("raw") < order.index("a") < order.index("merged")
    assert order.index("raw") < order.index("b") < order.index("merged")


def test_topological_order_raises_on_cycle():
    with pytest.raises(ValueError):
        topological_order(["a", "b"], {"a": ["b"], "b": ["a"]})
