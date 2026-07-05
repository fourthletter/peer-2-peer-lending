import json
import os
from pathlib import Path

from src.viz_cache import load_payload_cache, save_payload_cache


def test_payload_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZ_CACHE_DIR", str(tmp_path))
    payload = {
        "records": [{"headline": "Test", "url": "https://example.com/a"}],
        "viz": {"total": 1},
        "discovered": 1,
        "filter_summary": "",
        "date_from": "2020-01-01",
        "date_to": "2024-01-01",
    }
    save_payload_cache(payload)
    loaded = load_payload_cache()
    assert loaded is not None
    assert loaded["records"][0]["headline"] == "Test"
    assert (tmp_path / "payload.json").is_file()
    assert not (tmp_path / "payload.json.tmp").exists()


def test_payload_cache_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZ_CACHE_DIR", str(tmp_path))
    path = tmp_path / "payload.json"
    path.write_text('{"records": []}', encoding="utf-8")
    save_payload_cache({"records": [{"url": "https://example.com/b"}], "viz": {}})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["records"]) == 1
