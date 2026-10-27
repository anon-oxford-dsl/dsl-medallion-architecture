"""``medallion`` command-line interface.

validate   parse + JSON Schema + semantic checks, report located errors
generate   run the back-ends and write the artefacts
metrics    (Block 3)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .frontend.errors import SpecValidationError
from .frontend.lift import lift
from .frontend.model import Spec
from .frontend.parse import parse_spec_file
from .generators import GENERATORS, UnsupportedTargetError, generate_all, write_files
from .metrics import collect, render_json, render_table


def _load_spec(spec_path: Path) -> Spec:
    return lift(parse_spec_file(spec_path), source=str(spec_path))


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        spec = _load_spec(args.spec)
    except SpecValidationError as exc:
        print(exc.format(), file=sys.stderr)
        return 2
    print(
        f"{args.spec}: OK - product '{spec.product}', "
        f"{len(spec.sources)} source(s), {len(spec.layers)} layer(s)"
    )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    try:
        spec = _load_spec(args.spec)
    except SpecValidationError as exc:
        print(exc.format(), file=sys.stderr)
        return 2

    only = args.only
    if only is not None:
        unknown = [name for name in only if name not in GENERATORS]
        if unknown:
            print(
                f"unknown generator(s): {', '.join(unknown)}; choose from {', '.join(GENERATORS)}",
                file=sys.stderr,
            )
            return 2

    # Artefacts are nested under the product so several products can share an
    # output root without their dbt projects or databases colliding.
    product_dir = args.out / spec.product
    try:
        artefacts = generate_all(spec, only=only)
    except UnsupportedTargetError as exc:
        print(f"{args.spec}: {exc}", file=sys.stderr)
        return 2

    for name, files in artefacts.items():
        for path in write_files(files, product_dir):
            print(f"{name}: {path}")
    total = sum(len(files) for files in artefacts.values())
    print(f"{total} file(s) written to {product_dir}")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    reports = []
    for spec_path in args.specs:
        try:
            reports.append(collect(_load_spec(spec_path), spec_path))
        except SpecValidationError as exc:
            print(exc.format(), file=sys.stderr)
            return 2
    print(render_json(reports) if args.json else render_table(reports))
    return 0


def _generator_list() -> str:
    return "\n".join(f"  {name:<14} {cls.description}" for name, cls in GENERATORS.items())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medallion",
        description="Generate medallion-architecture infrastructure scaffolding from a YAML spec.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a specification and report any errors")
    p_validate.add_argument("spec", type=Path, help="path to the YAML specification")
    p_validate.set_defaults(func=_cmd_validate)

    p_generate = sub.add_parser(
        "generate",
        help="generate infrastructure artefacts from a specification",
        epilog="generators:\n" + _generator_list(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_generate.add_argument("spec", type=Path, help="path to the YAML specification")
    p_generate.add_argument(
        "--out",
        type=Path,
        default=Path("output"),
        help="output root; artefacts are written to <out>/<product> (default: %(default)s)",
    )
    p_generate.add_argument(
        "--only",
        type=lambda value: [part.strip() for part in value.split(",") if part.strip()],
        default=None,
        metavar="NAME[,NAME...]",
        help="run only the named generators (default: all)",
    )
    p_generate.set_defaults(func=_cmd_generate)

    p_metrics = sub.add_parser(
        "metrics",
        help="report specification size, generated output size and DAG complexity",
        description=(
            "Measure one or more scenarios. Artefacts are generated in memory, so a "
            "report never describes a stale output directory."
        ),
    )
    p_metrics.add_argument(
        "specs", type=Path, nargs="+", metavar="SPEC", help="one or more YAML specifications"
    )
    p_metrics.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead of a table"
    )
    p_metrics.set_defaults(func=_cmd_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
