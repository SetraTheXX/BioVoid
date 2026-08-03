from __future__ import annotations

from scripts.check_public_hygiene import _forbidden_path, _text_findings


def test_private_document_paths_are_not_public_release_paths() -> None:
    assert _forbidden_path("docs/research/ri-1-data-access-plan-v1.md")
    assert _forbidden_path("docs/research/ri-0-ri-1-ri-2-audit-v1.md")
    assert _forbidden_path("docs/specs/benchmark-protocol-v2-draft.md")
    assert _forbidden_path("docs/private/worklog.md")
    assert _forbidden_path("docs/research/ri-7-publication-readiness-report-v2.md")
    assert _forbidden_path("docs/specs/ri5-sealed-evaluation-v1.md")
    assert _forbidden_path("local-private/research/report.md")


def test_public_method_contract_remains_allowed() -> None:
    assert not _forbidden_path("docs/specs/scoring-contract-v1.md")
    assert not _forbidden_path("docs/releases/v0.1.0.md")


def test_artifact_suffixes_and_sensitive_content_are_rejected() -> None:
    for path in (
        "tools/vina/vina.exe",
        "data/arrays/pockets.npz",
        "data/raw/structure.pdb.gz",
        "fixtures/example.pdb.gz",
        "fixtures/example.cif.gz",
        "fixtures/example.mmcif.gz",
        "models/classifier.ckpt",
        "archive/results.zip",
        "docs/specs/benchmark-protocol-v2.md",
    ):
        assert _forbidden_path(path)
    assert _text_findings("C:" + "/" + "Users/example/private/file.txt", "fixture")
    assert _text_findings("-----BEGIN " + "PRIVATE KEY-----", "fixture")
