# Server code backup — 20 November 2026

The factory source at the root matches deployed commit 1e1f8b42958acb6671b45c5eaf7c693970514f74. This branch is a backup and must not be deployed automatically or merged blindly into main.

- ops/server-executor: on-demand Codex planning, review, preview and delivery helpers. Several pilot helpers deliberately accept only Cabin 17/18 and contain fixed pilot identifiers. They are not a finished general production worker.
- ops/shared-syntx: browser adapters used at /opt/marketplace-analytics/studio. browser_lease.py serializes access to the one SYNTX browser. Preserve the other project's jobs and browser profile when deploying changes.
- ops/systemd: intake and planning timers. Empty scans do not call the model. A new text correction can invoke one Codex planning call. General automatic video correction remains incomplete.

## Restore outline

1. Restore the factory source from this branch into a review checkout; compare with current production before deploying. Existing deploy/autoupdate.sh follows main, not this branch.
2. Install official Codex CLI 0.171.0 for the server architecture at /opt/relax-codex/release-0.171.0/bin/codex. Verify official release checksum. Create dedicated relax-codex user/home /var/lib/relax-codex and workspace there. Authenticate afresh with the owner's ChatGPT account; do not copy credentials from GitHub.
3. Copy ops/server-executor Python files to /opt/relax-codex. Copy shared browser adapters only after comparing the existing marketplace studio and confirming no active generation. The adapters require the existing Playwright studio container, one authorized SYNTX browser and its shared /state and /downloads mounts. Chromium memory limit was increased to 1280 MiB, combined memory+swap 1536 MiB after confirmed OOM failures.
4. Restore service definitions after checking every path and dependency. Start with read-only login and journal tests. Do not enable a generation worker merely because the files exist.
5. Restore operational state and media separately from their protected backups: factory data, SQLite task history, approved source clips, 109.032-second fireplace 9 audio, recipes and review evidence. These are intentionally absent from GitHub. Code-only recovery cannot recreate lost media or owner approvals.
6. Perform one full 30-second pilot with sound through owner approval in Telegram before enabling production. Never repeat a submitted/uncertain generation blindly. Runway requires displayed price 0; no fireplace masks or inserts. Preserve exact approved versions. Approved publication jobs should enter the active dated queue without a second owner confirmation; render lead time is 24 hours.

The active services have read-only/plain-text planning and intake safeguards, but full motion/audio judgment and general multi-scene correction orchestration still need completion. A successful image-sample check does not certify full video playback or listening.

Credentials, .env, browser profiles, authentication state, task databases, owner comments and media are excluded. Reconstruct credentials and server-specific settings separately through authorized setup.
