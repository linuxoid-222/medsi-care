"""Verify schema from scratch and upgrading legacy check-ins/events on SQLite."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

from app.db.repository import DatabaseStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("legacy", [False, True])
def test_fact_lifecycle_migrations_preserve_legacy_events(tmp_path, legacy):
    url = f"sqlite:///{tmp_path}/migration.db"
    env = {**os.environ, "DATABASE_URL": url}
    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)
    if legacy:
        migrate("upgrade", "0005_daily_monitoring")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO profiles
                (id, display_name, data_mode, created_at)
                VALUES ('profile-demo', 'Synthetic', 'synthetic', '2026-11-10 10:00:00')"""))
            connection.execute(text("""INSERT INTO check_ins
                (id, profile_id, text, source, created_at) VALUES
                ('old-check', 'profile-demo', 'Слабость', 'manual', '2026-11-10 10:00:00')"""))
            connection.execute(text("""INSERT INTO symptom_facts
                (id, check_in_id, category, polarity, evidence, confirmed, created_at)
                VALUES ('old-fact','old-check','weakness','present','Слабость',true,'2026-11-10 10:00:00')"""))
            connection.execute(text("""INSERT INTO monitoring_events
                (id, profile_id, status, level, message, evidence_json, source_observation_ids,
                 ruleset_version, created_at) VALUES
                ('old-event','profile-demo','attention','attention','Synthetic','["symptom:weakness"]',
                 '[]','manual-slice-v1','2026-11-10 10:00:00')"""))
        engine.dispose()
    migrate("upgrade", "head")
    migrate("check")
    store = DatabaseStore(url)
    try:
        if legacy:
            check = store.get_check_in("profile-demo", "old-check")
            assert check.text_revision == 1
            assert check.confirmed_revision is None
            assert not check.is_confirmed
            assert store.list_symptom_facts("old-check") == []
            event = store.list_monitoring_events("profile-demo")[0].event
            assert event.evidence == ("symptom:weakness",)
            assert event.text_provenance == ()
            assert event.algorithm_version == "manual-slice-v1"
        else:
            assert store.list_check_ins("profile-demo") == []
    finally:
        store.engine.dispose()
