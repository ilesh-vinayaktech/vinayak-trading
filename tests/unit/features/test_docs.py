from pathlib import Path

from algo.features import registry
from algo.features.docs import render

DOC = Path(__file__).parents[3] / "docs/features.md"


def test_every_registered_feature_has_an_entry_in_the_committed_document():
    text = DOC.read_text()
    for name, d in registry.DEFINITIONS.items():
        assert f"## {name} (version {d.version})" in text and d.manifest_sha256 in text, name


def test_the_committed_document_is_what_the_registry_generates():
    assert DOC.read_text() == render(), "run: uv run python scripts/feature_docs.py write"
