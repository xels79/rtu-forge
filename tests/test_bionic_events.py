import csv
import json
from datetime import datetime, timezone

from rtuforge.bionic_events import EventJournal


def test_new_journal_events_use_computer_local_time(tmp_path):
    journal = EventJournal(tmp_path / "events.jsonl")
    event = journal.add("RS485", "do-22", "подача закрыта")

    timestamp = datetime.fromisoformat(event.at)
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == datetime.now().astimezone().utcoffset()
    stored = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert stored["at"] == event.at


def test_utc_journal_entries_are_loaded_and_exported_in_local_time(tmp_path):
    path = tmp_path / "events.jsonl"
    utc_at = datetime.now(timezone.utc)
    path.write_text(json.dumps({
        "at": utc_at.isoformat(),
        "kind": "RS485",
        "subject": "do-22",
        "message": "legacy UTC",
        "previous": None,
        "current": None,
    }) + "\n", encoding="utf-8")

    journal = EventJournal(path)
    expected = utc_at.astimezone().isoformat()
    assert journal.events[0].at == expected

    export = tmp_path / "events.csv"
    journal.export_csv(export)
    with export.open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.DictReader(stream))["at"] == expected
