"""Layer-dependency graph helpers (pure standard library).

Nodes are layer names. ``deps[name]`` lists the layers ``name`` depends on
(its upstreams). Names in ``deps`` that are not declared layers are ignored
here -- dangling dependencies are reported separately by the semantic checks
in ``lift.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def _upstreams(names: Sequence[str], deps: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Dependencies restricted to declared layers, in declaration order."""
    known = set(names)
    return {name: [dep for dep in deps.get(name, ()) if dep in known] for name in names}


def detect_cycle(names: Sequence[str], deps: Mapping[str, Sequence[str]]) -> list[str] | None:
    """Return one cycle as an ordered list ``[a, b, ..., a]``, or ``None`` if acyclic."""
    upstreams = _upstreams(names, deps)
    visited: set[str] = set()
    path: list[str] = []
    on_path: set[str] = set()

    def visit(node: str) -> list[str] | None:
        visited.add(node)
        path.append(node)
        on_path.add(node)
        for upstream in upstreams[node]:
            if upstream in on_path:
                return [*path[path.index(upstream) :], upstream]
            if upstream not in visited:
                found = visit(upstream)
                if found is not None:
                    return found
        path.pop()
        on_path.discard(node)
        return None

    for name in names:
        if name not in visited:
            found = visit(name)
            if found is not None:
                return found
    return None


def topological_order(names: Sequence[str], deps: Mapping[str, Sequence[str]]) -> list[str]:
    """Kahn's algorithm, breaking ties by declaration order for deterministic output.

    Raises:
        ValueError: if the graph contains a cycle.
    """
    upstreams = _upstreams(names, deps)
    indegree = {name: len(ups) for name, ups in upstreams.items()}

    downstreams: dict[str, list[str]] = {name: [] for name in names}
    for name, ups in upstreams.items():
        for upstream in ups:
            downstreams[upstream].append(name)

    ready = [name for name in names if indegree[name] == 0]
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for downstream in downstreams[node]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)

    if len(order) != len(names):
        raise ValueError("layer-dependency graph contains a cycle")
    return order
