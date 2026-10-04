import os

from aimv.classification.models import (
    ClassificationDecision,
    ClassificationPlan,
    FileEvidence,
)
from aimv.organization.committer import OrganizationCommitter
from aimv.taxonomy.catalog import METADATA_FILENAME, TaxonomyCatalog
from aimv.tracking.move_log import MoveLog


def _plan(
    path,
    bucket_id="bucket.50.20.03",
    year=2024,
    month=7,
    suggested_name="2024-07_vendor_invoice.pdf",
):
    evidence = FileEvidence(
        path=str(path),
        name=path.name,
        extension=path.suffix,
        type_description="PDF document",
        age_description="recent",
        size=path.stat().st_size,
        content_text="Vendor invoice dated July 2024",
        modified_year=2026,
        modified_month=10,
    )
    decision = ClassificationDecision(
        action="move",
        confidence=0.95,
        bucket_id=bucket_id,
        suggested_name=suggested_name,
        tags=("invoice",),
        year=year,
        month=month,
    )
    return ClassificationPlan(evidence, decision, "invoices")


def test_dry_run_is_non_mutating_and_includes_time_route(tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_text("invoice")
    root = tmp_path / "AIMV"
    catalog = TaxonomyCatalog.load_default(str(root))

    outcome = OrganizationCommitter(catalog, dry_run=True).commit(_plan(source))

    assert outcome.status == "planned"
    assert os.path.join("2024", "2024-07") in outcome.destination_path
    assert source.exists()
    assert not root.exists()


def test_commit_materializes_year_month_metadata_and_moves_file(tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_text("invoice")
    root = tmp_path / "AIMV"
    catalog = TaxonomyCatalog.load_default(str(root))

    outcome = OrganizationCommitter(catalog).commit(_plan(source))

    assert outcome.status == "moved"
    assert not source.exists()
    assert os.path.exists(outcome.destination_path)
    assert os.path.exists(
        os.path.join(os.path.dirname(outcome.destination_path), METADATA_FILENAME)
    )
    year_dir = os.path.dirname(os.path.dirname(outcome.destination_path))
    assert os.path.exists(os.path.join(year_dir, METADATA_FILENAME))


def test_commit_rejects_extension_changes(tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_text("invoice")
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    plan = _plan(source)
    bad_decision = ClassificationDecision(
        action="move",
        confidence=0.95,
        bucket_id="bucket.50.20.03",
        suggested_name="invoice.exe",
        year=2024,
        month=7,
    )

    outcome = OrganizationCommitter(catalog).commit(
        ClassificationPlan(plan.evidence, bad_decision)
    )

    assert outcome.status == "failed"
    assert "preserve the original extension" in outcome.message
    assert source.exists()


def test_index_failure_rolls_back_file_and_compensates_move_log(tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_text("invoice")
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    move_log = MoveLog(str(tmp_path / "logs"))

    class FailingIndex:
        def add_entry(self, _entry):
            raise OSError("index unavailable")

    outcome = OrganizationCommitter(
        catalog,
        move_log=move_log,
        file_index=FailingIndex(),
    ).commit(_plan(source))

    assert outcome.status == "failed"
    assert source.exists()
    record = move_log.get_last(1)[0]
    assert record.reversed is True


def test_commit_never_mutates_file_already_inside_managed_root(tmp_path):
    root = tmp_path / "AIMV"
    root.mkdir()
    source = root / "already-managed.pdf"
    source.write_text("managed")
    catalog = TaxonomyCatalog.load_default(str(root))

    outcome = OrganizationCommitter(
        catalog,
        confirm=lambda _prompt: (_ for _ in ()).throw(
            AssertionError("managed files must not prompt")
        ),
    ).commit(_plan(source))

    assert outcome.status == "stayed"
    assert source.exists()
    assert "already inside" in outcome.message


def test_commit_appends_month_to_unrenamed_monthly_document(tmp_path):
    source = tmp_path / "bank_statement.pdf"
    source.write_text("statement")
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))

    outcome = OrganizationCommitter(catalog, dry_run=True).commit(
        _plan(
            source,
            bucket_id="bucket.50.10.01",
            year=2024,
            month=7,
            suggested_name=None,
        )
    )

    assert outcome.destination_path.endswith("bank_statement_2024-07.pdf")


def test_commit_appends_year_to_tax_document_without_duplicating_existing_year(
    tmp_path,
):
    source = tmp_path / "w2.pdf"
    source.write_text("wage statement")
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    committer = OrganizationCommitter(catalog, dry_run=True)

    renamed = committer.commit(
        _plan(
            source,
            bucket_id="bucket.50.40.02",
            year=2024,
            month=1,
            suggested_name=None,
        )
    )
    existing = committer._append_date_suffix("w2_2024.pdf", 2024, 1, "year")

    assert renamed.destination_path.endswith("w2_2024.pdf")
    assert existing == "w2_2024.pdf"
