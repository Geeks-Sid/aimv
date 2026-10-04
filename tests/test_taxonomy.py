import os

import yaml

from aimv.taxonomy.catalog import METADATA_FILENAME, TaxonomyCatalog


def test_default_taxonomy_is_broad_and_valid(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))

    assert catalog.validate() == []
    assert len(catalog.buckets) == 332
    assert len([node for node in catalog.nodes if node.kind == "area"]) == 16
    assert all(
        not any(character.isspace() for character in node.relative_path)
        for node in catalog.nodes
    )


def test_taxonomy_search_returns_semantic_bucket_routes(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))

    bank = catalog.search("2025 Chase monthly bank statement", limit=3)
    labs = catalog.search("blood panel laboratory result", limit=3)
    photos = catalog.search("vacation camera photographs", limit=5)

    assert bank[0].bucket.title == "Bank Statements"
    assert any(match.bucket.title == "Lab Results" for match in labs)
    assert any(match.bucket.title in {"Original Photos", "Travel Photos"} for match in photos)


def test_taxonomy_covers_research_administration_and_academic_letters(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))

    grant = catalog.search("NIH R01 specific aims grant application", limit=3)
    support = catalog.search("letter of support from collaborator", limit=3)
    recommendation = catalog.search("faculty recommendation reference letter", limit=3)
    irb = catalog.search("IRB informed consent human subjects", limit=3)

    assert grant[0].bucket.title == "Proposals & Applications"
    assert support[0].bucket.title == "Letters of Support & Collaboration"
    assert recommendation[0].bucket.title == "Recommendation Letters"
    assert irb[0].bucket.title == "Ethics, IRB & Consent"


def test_taxonomy_covers_common_bank_and_tax_documents_by_stable_id(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))

    cases = {
        "Chase monthly deposit account statement": "bucket.50.10.01",
        "Visa credit card statement minimum payment due": "bucket.50.30.01",
        "2024 W-2 wage and tax statement": "bucket.50.40.02",
        "1099-NEC nonemployee compensation": "bucket.50.40.02",
        "Schedule K-1 partnership income": "bucket.50.40.02",
        "2024 federal Form 1040 tax return": "bucket.50.40.01",
        "IRS CP notice estimated tax payment": "bucket.50.40.04",
    }

    for query, expected_id in cases.items():
        assert catalog.search(query, limit=1)[0].bucket.id == expected_id

    assert catalog.get("bucket.50.10.01").partition == "year_month"
    assert catalog.get("bucket.50.30.01").partition == "year_month"
    assert catalog.get("bucket.50.40.01").partition == "year"
    assert catalog.get("bucket.50.40.02").partition == "year"


def test_taxonomy_has_non_partitioned_flagged_review_destinations(tmp_path):
    catalog = TaxonomyCatalog.load_default(str(tmp_path / "AIMV"))
    flagged_ids = {
        "bucket.00.10.01",
        "bucket.00.10.02",
        "bucket.00.10.03",
        "bucket.00.40.01",
        "bucket.00.40.02",
        "bucket.00.40.03",
        "bucket.00.40.04",
    }

    assert {catalog.get(bucket_id).title for bucket_id in flagged_ids} == {
        "Unsorted Intake",
        "Needs Human Review",
        "Low Confidence",
        "Missing Context",
        "Unsupported Format",
        "Corrupt Files",
        "Access Restricted",
    }
    assert all(catalog.get(bucket_id).partition == "none" for bucket_id in flagged_ids)


def test_managed_root_ownership_uses_resolved_path_not_string_prefix(tmp_path):
    root = tmp_path / "AIMV"
    root.mkdir()
    inside = root / "already-managed.pdf"
    inside.write_text("managed")
    sibling = tmp_path / "AIMV-old" / "outside.pdf"
    sibling.parent.mkdir()
    sibling.write_text("outside")
    alias = tmp_path / "managed-alias"
    alias.symlink_to(root, target_is_directory=True)
    catalog = TaxonomyCatalog.load_default(str(root))

    assert catalog.contains_path(str(root))
    assert catalog.contains_path(str(inside))
    assert catalog.contains_path(str(alias / inside.name))
    assert not catalog.contains_path(str(sibling))


def test_materialize_selected_bucket_writes_hidden_metadata_to_every_level(tmp_path):
    root = tmp_path / "AIMV"
    catalog = TaxonomyCatalog.load_default(str(root))
    bucket_id = "bucket.50.20.03"

    written = catalog.materialize([bucket_id])
    bucket_path = catalog.resolve(bucket_id)
    category_path = os.path.dirname(bucket_path)
    area_path = os.path.dirname(category_path)

    assert written == 4
    for folder in (str(root), area_path, category_path, bucket_path):
        assert os.path.exists(os.path.join(folder, METADATA_FILENAME))

    with open(os.path.join(bucket_path, METADATA_FILENAME), encoding="utf-8") as stream:
        metadata = yaml.safe_load(stream)
    assert metadata["id"] == bucket_id
    assert metadata["partition"] == "year_month"
    assert metadata["relative_path"].endswith("50-20-03-invoices-and-bills")


def test_installed_metadata_aliases_are_searchable(tmp_path):
    root = tmp_path / "AIMV"
    catalog = TaxonomyCatalog.load_default(str(root))
    bucket_id = "bucket.50.10.01"
    catalog.materialize([bucket_id])
    metadata_path = os.path.join(catalog.resolve(bucket_id), METADATA_FILENAME)

    with open(metadata_path, encoding="utf-8") as stream:
        metadata = yaml.safe_load(stream)
    metadata["aliases"] = ["monthly money ledger"]
    with open(metadata_path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(metadata, stream, sort_keys=False)

    reloaded = TaxonomyCatalog.load_default(str(root))
    assert reloaded.search("monthly money ledger", limit=1)[0].bucket.id == bucket_id
    assert " " not in reloaded.get(bucket_id).relative_path


def test_installed_metadata_cannot_override_canonical_structural_path(tmp_path):
    root = tmp_path / "AIMV"
    catalog = TaxonomyCatalog.load_default(str(root))
    bucket_id = "bucket.50.10.01"
    catalog.materialize([bucket_id])
    metadata_path = os.path.join(catalog.resolve(bucket_id), METADATA_FILENAME)

    with open(metadata_path, encoding="utf-8") as stream:
        metadata = yaml.safe_load(stream)
    metadata["relative_path"] = "50 Money/Bank Statements"
    metadata["aliases"] = ["custom bank archive"]
    with open(metadata_path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(metadata, stream, sort_keys=False)

    reloaded = TaxonomyCatalog.load_default(str(root))

    assert reloaded.get(bucket_id).relative_path.endswith("50-10-01-bank-statements")
    assert reloaded.search("custom bank archive", limit=1)[0].bucket.id == bucket_id
