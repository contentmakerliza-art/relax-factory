# Automatic approval processing

Prepared releases with a reviewed manifest in /opt/relax-codex/publication-manifests can now be moved automatically to the active dated factory queue after exact-version Telegram approval. A per-source receipt prevents repeated submissions and repeated Telegram notifications. Ordinary approval checks make no model calls. The owner does not need to confirm a draft again.

Restore these source files together: dispatch-decisions.py, promote-approved.py, publish-approved-card.py and prepare-publication.py. Restore the protected operational manifests and receipts separately from their state backup, not from GitHub. A manifest must contain an approved-preview SHA256, full-audio SHA256, a verified full-frame loop recipe, the exact profile, date, texts and cover path. Do not invent missing manifests for unreviewed sources. Existing date conflicts or uncertain writes are held for inspection without automatic retries. General automatic video correction remains incomplete.

The tested Cabin source 20261120-150523-44c3 entered publication f53b4fda on 18 December 2026 at 22:00 Moscow time via the scheduled server handler. The queue lead time is 24 hours. This is a scheduled queue item, not evidence that a final video is already rendered or on YouTube.
