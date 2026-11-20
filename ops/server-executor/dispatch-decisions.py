"""Consume new owner decisions. Plan corrections once; no automatic video actions yet."""
import importlib.util
import json
from pathlib import Path
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path('/opt/relax-codex')


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def main():
    try:
        module('production_recovery',ROOT/'recover-production.py').main()
    except Exception as error:
        # Recovery must not prevent new owner decisions from being ingested.
        print(json.dumps({'production_recovery':'requires_inspection','error':type(error).__name__}))
    planner=module('planner',ROOT/'plan-one.py')
    bridge=planner.bridge
    rows=bridge.read_rows(Path('/var/lib/relax-factory'))
    production=json.loads(Path('/var/lib/relax-factory/approved-production-queue.json').read_text())
    db=sqlite3.connect('/var/lib/relax-codex-bridge/tasks.sqlite',timeout=10)
    bridge.ingest(db,rows)
    pending=db.execute("SELECT id,job_id,state FROM tasks WHERE state IN ('pending_executor','pending_publication_check','approval_recorded_in_production') ORDER BY created").fetchall()
    for task_id,job_id,state in pending:
        current=rows.get(job_id)
        if not current or planner.fingerprint(current)!=task_id:
            with db:db.execute("UPDATE tasks SET state='superseded' WHERE id=?",(task_id,))
            continue
        if state in ('pending_publication_check','approval_recorded_in_production'):
            promoter=module('promoter',ROOT/'promote-approved.py')
            result=promoter.promote(job_id)
            if result is not None:
                db.execute('CREATE TABLE IF NOT EXISTS publication_receipts (task_id TEXT PRIMARY KEY, receipt TEXT)')
                with db:
                    db.execute('INSERT OR REPLACE INTO publication_receipts VALUES (?,?)',(task_id,json.dumps(result,ensure_ascii=False)))
                    db.execute('UPDATE tasks SET state=? WHERE id=?',('publication_queued' if result.get('state')=='queued' else 'publication_attention_required',task_id))
                continue
            row=production.get(job_id)
            # No invented publication status: save actual card state and its blocker.
            if row:
                db.execute('CREATE TABLE IF NOT EXISTS publication_receipts (task_id TEXT PRIMARY KEY, receipt TEXT)')
                with db:
                    db.execute('INSERT OR REPLACE INTO publication_receipts VALUES (?,?)',(task_id,json.dumps(row,ensure_ascii=False)))
                    db.execute("UPDATE tasks SET state='approval_recorded_in_production' WHERE id=?",(task_id,))
            continue
        if current.get('archived'):
            with db:db.execute("UPDATE tasks SET state='needs_source_recovery' WHERE id=?",(task_id,))
            continue
        comments=current.get('comments',[])
        if not comments or not (comments[-1].get('text') or comments[-1].get('transcript')):
            with db:db.execute("UPDATE tasks SET state='needs_transcription' WHERE id=?",(task_id,))
            continue
        midnight=datetime.now(ZoneInfo('Europe/Moscow')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        # Bound unattended subscription usage. No API fallback or purchased credits.
        count=db.execute("SELECT count(*) FROM tasks WHERE state NOT IN ('pending_executor','pending_publication_check','awaiting_comment','superseded','needs_transcription','approval_recorded_in_production','publication_queued','publication_attention_required') AND created>=?",(midnight,)).fetchone()[0]
        if count>=20:return
        planner.main(job_id)
        return  # One model call per invocation; separate timer starts the next job.


if __name__=='__main__':main()
