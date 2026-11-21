# Cabin backlog — 21 November 2026

Runs only the twelve missing publication dates through 22 December: 03, 05–07,
09–12, 15, 19–21 December. Existing approved versions and other channels are untouched.

The root-owned frozen `registry.json` enumerates exact groups, attempts, source
hashes, titles and publication times. Source images are staged in the existing
SYNTX downloads volume. QA rectangles are computed separately for each source in
1280×720 coordinates; they select pixels for analysis and are never editing masks.

`run-batch.py` runs serially under `relax-cabin-backlog.service`. It resumes exact
receipts, skips already occupied publication dates and keeps status in
`/opt/relax-codex/cabin-backlog/batch-status.json`. Each source is inspected before
video generation. Only full-frame native Runway motion is allowed. The existing
adapter verifies Gen-4 Turbo, 16:9, 10 seconds and displayed price **0** before
submission, and reserves a ledger before clicking. Three received videos per
source, then up to two ordinary Banana 2 replacement images, at most 3 tokens per
image. Confirmed service failures do not count as visual rejection. Two failures
pause the model; ambiguous submissions and deliveries are held for inspection.

Each downloaded clip receives sampled visual QC and full-sequence cat/camera
motion checks. A clean 8+ second temporal segment is tried before regeneration.
A 30-second full-frame preview uses the approved complete fireplace-9 audio,
with no wind, music, pasted fireplaces, synthetic cat or indoor snow layers.
Final checks cover decoded frames, audio correlation, scene-specific cat/fire and
window detail sheets, and the real publication-loop recipe. Only then is a dated
publication manifest registered and the preview sent to owner Telegram.
Automation does not replace owner approval or claim actual listening/playback.

The existing approval intake promotes the exact approved preview to its reserved
calendar date. Final 3h rendering is scheduled 24h before publication. No long
final is started merely because a preview passes automated QC.

The batch's implementations are isolated from the earlier 08/22 pilot and other
projects. Shared browser access uses the existing browser lease. No containers
are restarted to install these scripts. Root worker memory limit is 256MB;
ephemeral visual Codex checks have their own 512MB limit. Media processing uses
the existing constrained factory container.

Recovery: inspect batch status, each production-runs/<group>/{state,delivery}.json,
assets/<request>/QC evidence and studio-state/runway-<request>.json. Never remove
an uncertain submission ledger to force a fresh generation. Never resend an
uncertain Telegram delivery blindly. Start the same service to resume safe states.
