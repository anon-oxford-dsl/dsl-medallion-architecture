from __future__ import annotations

import pytest

from medallion.frontend.errors import SpecValidationError
from medallion.frontend.parse import LinedMap, parse_spec_file, parse_text


def test_parses_mapping_with_line_numbers(example_spec_path):
    doc = parse_spec_file(example_spec_path)
    assert isinstance(doc, LinedMap)
    assert doc["product"] == "customer_orders"
    # nested mappings also carry their source line (a block mapping starts at its first key)
    assert doc.line == 2
    assert doc["sources"].line == 5
    assert doc["sources"]["orders"].line == 6


def test_syntax_error_is_located():
    bad = "product: customer_orders\n\tsources: {}\n"  # tab indentation
    with pytest.raises(SpecValidationError) as excinfo:
        parse_text(bad, source="bad.yml")
    (error,) = excinfo.value.errors
    assert error.line is not None
    assert "bad.yml" in excinfo.value.format()


def test_top_level_must_be_mapping():
    with pytest.raises(SpecValidationError) as excinfo:
        parse_text("- just\n- a\n- list\n")
    assert "mapping at the top level" in excinfo.value.errors[0].message


def test_empty_document_rejected():
    with pytest.raises(SpecValidationError):
        parse_text("\n\n")


def test_missing_file_reports_cleanly(tmp_path):
    with pytest.raises(SpecValidationError) as excinfo:
        parse_spec_file(tmp_path / "nope.yml")
    assert "no such file" in excinfo.value.errors[0].message
