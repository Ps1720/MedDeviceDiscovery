"""Knowledge-base seeding, context shadowing, and checklist fallback."""

import protocol_db
import protocol_seed
from conftest import PACEMAKER_RECORD
import protocol_service


def test_seed_is_idempotent(seeded_db):
    assert protocol_seed.seed_protocols(seeded_db) is False  # same version: no-op


def test_version_bump_reseeds(seeded_db, monkeypatch):
    monkeypatch.setattr(protocol_seed, "SEED_VERSION", "9999.99.9")
    assert protocol_seed.seed_protocols(seeded_db) is True
    conn = protocol_db.get_conn(seeded_db)
    try:
        assert protocol_db.get_meta("seed_version", conn) == "9999.99.9"
    finally:
        conn.close()


def test_all_content_tables_populated(seeded_db):
    conn = protocol_db.get_conn(seeded_db)
    try:
        for table in protocol_db.CONTENT_TABLES:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n > 0, table
    finally:
        conn.close()


def test_every_class_has_surgery_checklist_and_headline(seeded_db):
    conn = protocol_db.get_conn(seeded_db)
    try:
        for class_key in protocol_db.get_device_classes(conn):
            checklist = protocol_db.get_checklist(class_key, "surgery", conn)
            assert checklist, f"{class_key} has no surgery checklist"
            positions = [i["position"] for i in checklist]
            assert positions == sorted(positions)
            facts = protocol_db.get_facts(class_key, "surgery", conn)
            assert "headline" in facts, f"{class_key} has no surgery headline"
    finally:
        conn.close()


def test_context_specific_fact_shadows_all(seeded_db):
    conn = protocol_db.get_conn(seeded_db)
    try:
        conn.execute(
            "INSERT INTO protocol_facts (class_key, context, fact_key, fact_value) "
            "VALUES ('pacemaker', 'all', 'shadow_test', 'generic'),"
            "       ('pacemaker', 'mri', 'shadow_test', 'mri-specific')"
        )
        conn.commit()
        assert protocol_db.get_facts("pacemaker", "mri", conn)["shadow_test"]["fact_value"] == "mri-specific"
        assert protocol_db.get_facts("pacemaker", "surgery", conn)["shadow_test"]["fact_value"] == "generic"
    finally:
        conn.close()


def test_checklist_falls_back_to_all_context(seeded_db):
    conn = protocol_db.get_conn(seeded_db)
    try:
        conn.execute("DELETE FROM checklist_items WHERE class_key = 'cgm'")
        conn.execute(
            "INSERT INTO checklist_items (class_key, context, position, item_text) "
            "VALUES ('cgm', 'all', 1, 'fallback item')"
        )
        conn.commit()
        for context in ("surgery", "mri", "ep_study"):
            items = protocol_db.get_checklist("cgm", context, conn)
            assert [i["item_text"] for i in items] == ["fallback item"]
    finally:
        conn.close()


def test_seeded_rows_require_verification(seeded_db):
    conn = protocol_db.get_conn(seeded_db)
    try:
        for table in ("protocol_facts", "checklist_items", "brand_facts"):
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE requires_verification != 1"
            ).fetchone()[0]
            assert n == 0, f"{table} has rows not flagged for verification"
    finally:
        conn.close()


def test_protocol_block_shape(seeded_db, tmp_path, monkeypatch):
    import overrides as overrides_mod
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "none.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    assert block["device_class"] == "pacemaker"
    assert block["context"] == "surgery"
    assert set(block["available_contexts"]) <= {"surgery", "mri", "ep_study"}
    assert block["headline_actions"]
    assert block["checklist"]
    assert block["disclaimer"]
    assert block["resolution"]["confidence"] in {"high", "medium", "low"}


def test_implant_options_on_cardiac_protocol(seeded_db, tmp_path, monkeypatch):
    import overrides as overrides_mod
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "none.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "surgery")
    assert block["implant_options"]["default_lead_config"] == "ra_rv"
    assert block["implant_options"]["has_pocket"] is True


def test_no_implant_options_on_non_cardiac(seeded_db, tmp_path, monkeypatch):
    from conftest import DBS_RECORD
    import overrides as overrides_mod
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "none.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    block = protocol_service.build_protocol_block(DBS_RECORD, "surgery")
    assert block is not None
    assert "implant_options" not in block


def test_crt_p_gets_magnet_rate_brand_fact(seeded_db, tmp_path, monkeypatch):
    import overrides as overrides_mod
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "none.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    crt_p = {
        "manufacturer": "Medtronic, Inc.",
        "brand_name": "Generic CRT-P",
        "type": "Cardiac resynchronisation therapy pacemaker",
        "gmdn": [{"code": "8", "name": "Cardiac resynchronisation therapy pacemaker"}],
        "fda_product_codes": [{"code": "NKE", "name": "CRT-P"}],
    }
    block = protocol_service.build_protocol_block(crt_p, "surgery")
    assert block["device_class"] == "crt_p"
    assert block["facts"]["magnet_rate"]["value"] == "85 bpm"


def test_invalid_context_falls_back_to_surgery(seeded_db, tmp_path, monkeypatch):
    import overrides as overrides_mod
    monkeypatch.setattr(overrides_mod, "OVERRIDES_PATH", tmp_path / "none.json")
    overrides_mod._cache.update({"mtime": None, "data": None})
    block = protocol_service.build_protocol_block(PACEMAKER_RECORD, "bogus")
    assert block["context"] == "surgery"
