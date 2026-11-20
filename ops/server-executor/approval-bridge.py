"""Durable intake only. Never calls AI, Telegram, generation, or rendering."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def read_rows(root):
    rows = {}
    # Archived records first; a live record takes precedence.
    for pattern in ('notes/*/approval.json', '*/job.json'):
        for path in sorted(root.glob(pattern)):
            try:
                data = json.loads(path.read_text())
                ap = data.get('approval')
                if not isinstance(ap, dict):
                    continue
                rows[path.parent.name] = {
                    'job_id': path.parent.name, 'label': data.get('label', ''),
                    'status': ap.get('status'), 'time': ap.get('time'),
                    'comments': [{k: c[k] for k in ('time', 'text', 'transcript', 'voice') if k in c}
                                 for c in ap.get('comments', []) if isinstance(c, dict)],
                    'archived': pattern.startswith('notes/'),
                }
            except (OSError, ValueError, TypeError):
                # A concurrent factory save may be partial. Retry next scan.
                continue
    return rows


def ingest(db, rows):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS seen (job_id TEXT PRIMARY KEY, fingerprint TEXT);
      CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, job_id TEXT, state TEXT, payload TEXT, created REAL);
    ''')
    with db:
        initial = not db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone()
        created = 0
        for job_id, row in rows.items():
            # Archiving or changing the label does not create a new owner decision.
            decision = {k: row[k] for k in ('job_id', 'status', 'time', 'comments')}
            fingerprint = hashlib.sha256(json.dumps(decision, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            old = db.execute('SELECT fingerprint FROM seen WHERE job_id=?', (job_id,)).fetchone()
            if old and old[0] == fingerprint:
                continue
            db.execute('INSERT OR REPLACE INTO seen VALUES (?,?)', (job_id, fingerprint))
            if initial:
                continue
            db.execute("UPDATE tasks SET state='superseded' WHERE job_id=? AND state IN ('awaiting_comment','pending_executor','pending_publication_check')", (job_id,))
            status = row.get('status')
            if status not in ('правка', 'одобрено'):
                continue
            comments = row.get('comments', [])
            state = ('pending_publication_check' if status == 'одобрено' else
                     'pending_executor' if comments else 'awaiting_comment')
            cursor = db.execute('INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?)',
                                (fingerprint, job_id, state, json.dumps(row, ensure_ascii=False), time.time()))
            created += cursor.rowcount
        # Refuse to establish an empty baseline if factory storage is unavailable.
        if rows:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('initialized','yes')")
    return {'baseline': initial, 'records_seen': len(rows), 'new_tasks': created}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/var/lib/relax-factory'))
    parser.add_argument('--database', type=Path, default=Path('/var/lib/relax-codex-bridge/tasks.sqlite'))
    args = parser.parse_args()
    args.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(args.database, timeout=10) as db:
        print(json.dumps(ingest(db, read_rows(args.data))))
