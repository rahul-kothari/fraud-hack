"""The official data folder layout (organisers' JSON Lines) is read into the engine's shape.

Rows here are invented and minimal: the real dev data is never committed.
"""
import json

from screening import ingest, names
from screening.pipeline import official_row


def test_dates_to_partial_iso():
    assert ingest.parse_date("19/05/2004") == "2004-05-19"          # day-first
    assert ingest.parse_date("1980") == "1980"
    assert ingest.parse_date("March 1975") == "1975-03"
    assert ingest.parse_date("5 March 1975") == "1975-03-05"
    assert ingest.parse_date("13/13/1990") is None                  # no 13th month
    assert ingest.parse_date(None) is None


def test_alert_customer_is_flattened():
    a = ingest.alert({"alert_id": "A-000001", "screened_at": "2026-11-06",
                      "customer": {"name": "Li Wei", "entity_type": "Individual", "dob": "1975",
                                   "country": "SG", "city": None},
                      "account_ref": None, "login_handle": "liwei", "email": None, "hit_ids": ["H-000001"]})
    assert a["customer_name"] == "Li Wei" and a["dob_iso"] == "1975"
    assert a["country_norm"] == "Singapore" and a["hit_ids"] == ["H-000001"]


def test_hit_lists_split_at_top_level_and_countries_tied():
    h = ingest.hit({"hit_id": "H-000001", "alert_id": "A-000001", "entity_type": "Individual", "name": "Wei Li",
                    "dobs": ["1975"], "deceased_date": None, "aliases": [],
                    "relationships": ["Laura, Romoli (Motherinlaw", "PEP)"],        # split inside brackets
                    "place_of_birth": "Zamora, Spain; Madrid, Spain",               # one string
                    "countries": ["Canada"], "nationality": [], "citizenship": [],
                    "addresses": ["1 Main St, Toronto, Canada"], "details": None})
    assert h["relationships"] == ["Laura, Romoli (Motherinlaw; PEP)"]
    assert h["place_of_birth"] == ["Zamora, Spain", "Madrid, Spain"]
    assert h["countries_tied"] == ["Canada", "Spain"]
    assert h["dobs_iso"] == ["1975"] and h["details"] == {}


def test_practice_label_path_list():
    l = ingest.practice_label({"hit_id": "H-000001", "path": ["step one", "step two"]})
    assert l["path"] == "step one → step two" and l["path_steps"] == ["step one", "step two"]


def test_official_folder_detection_and_variants(tmp_path):
    (tmp_path / "alerts.jsonl").write_text(json.dumps({"alert_id": "A-000001", "customer": {}}) + "\n")
    assert ingest.is_official(tmp_path)
    (tmp_path / "name_variants.json").write_text(json.dumps(
        {"description": "x", "groups": [["zbigniew", "zbyszek"]], "company_legal_forms": ["ltd"]}))
    assert ingest.load(tmp_path, "practice_labels") == []           # absent on the unseen set
    before = names._VARIANTS_PATH
    try:
        names.use_variants(ingest.name_variants_path(tmp_path))
        assert names.variant_groups("zbigniew") & names.variant_groups("zbyszek")
        assert "ltd" in names.legal_forms()
    finally:
        names.use_variants(before)


def test_official_row_record_choice():
    base = {"hit_id": "H-000001", "alert_id": "A-000001", "decision": "SAME_ENTITY",
            "reason_codes": ["NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH"], "reference_reason": "r", "evidence": []}
    # two records of one person: either is right, so the first is given
    assert official_row({**base, "customer_record_ids": ["CUS-000001", "CUS-000002"]})["customer_record_id"] == "CUS-000001"
    assert official_row({**base, "customer_record_ids": ["AMBIGUOUS"]})["customer_record_id"] == "AMBIGUOUS"
    assert official_row({**base, "customer_record_ids": []})["customer_record_id"] is None
    assert official_row({**base, "customer_record_ids": []})["reason_code"] == "NAME_DOB_MATCH"
