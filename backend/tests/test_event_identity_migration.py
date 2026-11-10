"""Upgrading 0006 preserves review state, legacy events and read notifications."""

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from app.db.repository import DatabaseStore

ROOT = Path(__file__).resolve().parents[2]


def test_upgrade_event_identity_preserves_legacy_state(tmp_path):
    url = f"sqlite:///{tmp_path}/identity.db"
    env = {**os.environ, "DATABASE_URL": url}
    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)
    migrate("upgrade", "0006_fact_lifecycle")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO profiles (id,display_name,data_mode,created_at)
            VALUES ('profile-demo','Synthetic','synthetic','2026-11-10 10:00:00')"""))
        connection.execute(text("""INSERT INTO check_ins
            (id,profile_id,text,source,created_at,text_revision,confirmed_revision,confirmed_at)
            VALUES ('reviewed','profile-demo','Без жалоб','manual','2026-11-10 10:00:00',1,1,'2026-11-10 10:00:01')"""))
        connection.execute(text("""INSERT INTO monitoring_events
            (id,profile_id,status,level,message,evidence_json,source_observation_ids,ruleset_version,created_at)
            VALUES ('legacy','profile-demo','attention','attention','Synthetic','[]','[]','old-rules','2026-11-10 10:00:01')"""))
        connection.execute(text("""INSERT INTO notifications
            (id,event_id,recipient_id,status,read_at,created_at)
            VALUES ('read','legacy','demo-caregiver','read','2026-11-10 10:00:02','2026-11-10 10:00:01')"""))
    engine.dispose()
    migrate("upgrade", "head")
    migrate("check")
    store = DatabaseStore(url)
    try:
        check = store.get_check_in("profile-demo", "reviewed")
        assert check.is_confirmed and check.facts_revision == 0
        event = store.list_monitoring_events("profile-demo")[0]
        assert event.identity_key is None
        assert event.event.algorithm_version == "old-rules"
        note = store.list_notifications("demo-caregiver")[0]
        assert note.status == "read" and note.read_at.isoformat() == "2026-11-10T10:00:02+00:00"
    finally:
        store.engine.dispose()
