"""Measurement harness for framework metrics.

Reports, per scenario (one specification): the size of the specification against
the size of everything generated from it, file counts per back-end, and the
complexity of the generated DAG.

Nothing here judges pass or fail -- it is pure measurement. Metrics are computed
by generating in memory, so a report can never describe a stale ``build/``
directory.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .frontend.model import Spec
from .generators import GENERATORS, GeneratedFile, generate_all
from .generators.orchestration import INGESTION_TASK

#: Line-comment marker by file suffix. Files not listed have no comment syntax.
_COMMENT_PREFIXES: dict[str, str] = {
    ".sql": "--",
    ".yml": "#",
    ".yaml": "#",
    ".py": "#",
}


def _docstring_line_numbers(text: str) -> set[int]:
    """1-based line numbers occupied by module/class/function docstrings."""
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - generated Python always parses
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        first = node.body[0]
        if first.end_lineno is not None:
            lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


@dataclass(frozen=True)
class LineCounts:
    """How a text artefact divides into blank, comment and code lines."""

    total: int
    blank: int
    comment: int
    code: int

    @classmethod
    def of(cls, text: str, suffix: str) -> LineCounts:
        lines = text.splitlines()
        prefix = _COMMENT_PREFIXES.get(suffix)
        # Python docstrings are comments in substance; count them as such rather
        # than inflating the generated code figure.
        docstrings = _docstring_line_numbers(text) if suffix == ".py" else set()

        blank = comment = code = 0
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                blank += 1
            elif number in docstrings or (prefix and stripped.startswith(prefix)):
                comment += 1
            else:
                code += 1
        return cls(total=len(lines), blank=blank, comment=comment, code=code)

    def __add__(self, other: LineCounts) -> LineCounts:
        return LineCounts(
            total=self.total + other.total,
            blank=self.blank + other.blank,
            comment=self.comment + other.comment,
            code=self.code + other.code,
        )


@dataclass(frozen=True)
class GeneratorMetrics:
    """Output attributable to one back-end."""

    name: str
    file_count: int
    lines: LineCounts
    bytes: int


@dataclass(frozen=True)
class DagMetrics:
    """Complexity of the generated orchestration graph.

    Derived from the typed model rather than by parsing the emitted Python, so
    the figures are independent of formatting and need no Airflow install. The
    graph modelled here is the one the orchestration back-end emits: the
    ingestion task plus one task per layer.
    """

    task_count: int
    dependency_edges: int
    max_depth: int
    root_tasks: int
    leaf_tasks: int
    #: Edges as a fraction of the most a DAG on this many nodes could have, V(V-1)/2.
    density: float
    #: McCabe cyclomatic complexity of the task graph, E - V + 2.
    cyclomatic_complexity: int

    @classmethod
    def of(cls, spec: Spec) -> DagMetrics:
        layers = spec.topological_layers()
        layer_names = {layer.name for layer in layers}

        # The emitted DAG is the ingestion task feeding every layer that loads,
        # then the layer graph. Model that, not the layer graph alone, or these
        # figures would describe a DAG the framework does not generate.
        names = [INGESTION_TASK, *(layer.name for layer in layers)]
        upstreams: dict[str, list[str]] = {INGESTION_TASK: []}
        for layer in layers:
            ups = [d for d in layer.depends_on if d in layer_names]
            if layer.has_tables:
                ups = [INGESTION_TASK, *ups]
            upstreams[layer.name] = ups

        downstream_count = dict.fromkeys(names, 0)
        for name in names:
            for up in upstreams[name]:
                downstream_count[up] += 1

        edges = sum(len(ups) for ups in upstreams.values())
        vertices = len(names)

        # Longest path in nodes; layers are already topologically ordered.
        depth: dict[str, int] = {}
        for name in names:
            depth[name] = 1 + max((depth[up] for up in upstreams[name]), default=0)

        max_pairs = vertices * (vertices - 1) / 2
        return cls(
            task_count=vertices,
            dependency_edges=edges,
            max_depth=max(depth.values(), default=0),
            root_tasks=sum(1 for name in names if not upstreams[name]),
            leaf_tasks=sum(1 for name in names if downstream_count[name] == 0),
            density=round(edges / max_pairs, 4) if max_pairs else 0.0,
            cyclomatic_complexity=edges - vertices + 2,
        )


@dataclass(frozen=True)
class MetricsReport:
    """Everything measured for one scenario."""

    scenario: str
    product: str
    spec_lines: LineCounts
    source_count: int
    layer_count: int
    column_count: int
    generators: tuple[GeneratorMetrics, ...]
    file_count: int
    generated_lines: LineCounts
    generated_bytes: int
    dag: DagMetrics

    @property
    def expansion_ratio(self) -> float:
        """Generated code lines per specification code line."""
        if not self.spec_lines.code:
            return 0.0
        return round(self.generated_lines.code / self.spec_lines.code, 2)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["generators"] = [asdict(g) for g in self.generators]
        data["expansion_ratio"] = self.expansion_ratio
        return data


def _spec_text_metrics(spec_path: Path) -> LineCounts:
    return LineCounts.of(spec_path.read_text(encoding="utf-8"), spec_path.suffix)


def _generator_metrics(name: str, files: list[GeneratedFile]) -> GeneratorMetrics:
    lines = LineCounts(0, 0, 0, 0)
    for generated in files:
        lines = lines + LineCounts.of(generated.content, Path(str(generated.path)).suffix)
    return GeneratorMetrics(
        name=name,
        file_count=len(files),
        lines=lines,
        bytes=sum(len(f.content.encode("utf-8")) for f in files),
    )


def collect(spec: Spec, spec_path: Path) -> MetricsReport:
    """Measure one scenario: its specification against everything generated from it."""
    artefacts = generate_all(spec)
    per_generator = tuple(
        _generator_metrics(name, artefacts[name]) for name in GENERATORS if name in artefacts
    )

    generated_lines = LineCounts(0, 0, 0, 0)
    for metrics in per_generator:
        generated_lines = generated_lines + metrics.lines

    return MetricsReport(
        scenario=spec_path.stem,
        product=spec.product,
        spec_lines=_spec_text_metrics(spec_path),
        source_count=len(spec.sources),
        layer_count=len(spec.layers),
        column_count=sum(len(source.columns) for source in spec.sources),
        generators=per_generator,
        file_count=sum(m.file_count for m in per_generator),
        generated_lines=generated_lines,
        generated_bytes=sum(m.bytes for m in per_generator),
        dag=DagMetrics.of(spec),
    )


def render_json(reports: list[MetricsReport]) -> str:
    return json.dumps([report.to_dict() for report in reports], indent=2, sort_keys=False)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip()
    rule = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    return "\n".join([line, rule, *body])


def render_table(reports: list[MetricsReport]) -> str:
    """Human-readable summary: one scenario per row, then a per-generator breakdown."""
    summary = _table(
        [
            "scenario",
            "spec LOC",
            "gen LOC",
            "ratio",
            "files",
            "tasks",
            "edges",
            "depth",
            "density",
            "cyclo",
        ],
        [
            [
                report.scenario,
                str(report.spec_lines.code),
                str(report.generated_lines.code),
                f"{report.expansion_ratio:.2f}x",
                str(report.file_count),
                str(report.dag.task_count),
                str(report.dag.dependency_edges),
                str(report.dag.max_depth),
                f"{report.dag.density:.2f}",
                str(report.dag.cyclomatic_complexity),
            ]
            for report in reports
        ],
    )

    sections = [summary]
    for report in reports:
        breakdown = _table(
            ["generator", "files", "total", "code", "comment", "blank", "bytes"],
            [
                [
                    metrics.name,
                    str(metrics.file_count),
                    str(metrics.lines.total),
                    str(metrics.lines.code),
                    str(metrics.lines.comment),
                    str(metrics.lines.blank),
                    str(metrics.bytes),
                ]
                for metrics in report.generators
            ],
        )
        sections.append(f"\n{report.scenario}: generated output by back-end\n{breakdown}")
    return "\n".join(sections)
