# McNulty & Jeon Family Tree — Project Instructions

**Purpose:** Maintain and publish a sourced, confidence-tiered McNulty & Burnham family tree. This is the single source of truth the entire family uses — the public site must always show full, unredacted information. Never propose or apply redaction of names, dates, or relationships on the public site.

## Repo layout
- `family-data.json` — canonical data. Currently 3,033 people, 0 broken links.
- `familysearch/library.json` — source document index, schema `{id, t, x, p, cat, f}` (`p` = linked person IDs). Currently 328 docs.
- `familysearch/fs_review.json` — FamilySearch candidate-match review queue (`rows`, 2,906 total). ~2,349 rows still have no `resolved` field — this is a known, lower-priority backlog, separate from the 557-row triage that was closed out.
- `familysearch/fs_accepted.json` — staging file consumed once by `apply_reviewed.py` per batch.
- `index.html` (this repo's root) — embeds `DATA` (from family-data.json) and `LIBRARY` (from library.json) as JS consts. There is also a separate, non-git-tracked working copy of `index.html` one directory up (in the parent "McNulty Family Tree" folder) used as a local scratch/staging copy before changes are brought into this repo — don't confuse the two.
- `MASTER_PLAN_2026-09.md` (parent folder) — running session log. Append a dated section summarizing what changed at the end of any substantial work session.
- `push-update.bat` — Sean's deploy script (git add/commit/pull/push). See the Git/deploy section below for its quirks.

## Non-negotiable data rules
1. **ADD-only mutation.** Never overwrite or delete existing fields. Only fill blanks and append sourced notes / `webEnrichment` entries. This applies especially to FamilySearch enrichment.
2. **Atomic writes.** Every mutation to `family-data.json` or `library.json`: timestamped backup copy first, then write to a `.tmp` file and `os.replace` into place. Never edit these files in place without that pattern.
3. **Name matching must use word-boundary regex** (`\b...\b`), never substring matching — substring matching produces false positives (e.g. "King" inside "looking", "Burke" inside "Burke's Peerage").
4. **Corroborating a candidate match** against a person's family graph (parents/spouse) requires a *distinctive* shared token — exclude common given names (Mary, John, William, etc.) and the target's own surname from counting as corroboration. A single trivial shared surname is not enough to accept a match.
5. Before linking any document to a person, sanity-check dates (birth/death years) against the document's claimed dates/events — don't link on name alone if the timeline is impossible.

## Pipeline scripts (run in this order after any library.json or family-data.json change)
1. `apply_reviewed.py` — applies accepted FamilySearch matches from `fs_accepted.json` (ADD-only).
2. `cleanup_and_build.py --no-merge` — rebuilds the `DATA` blob only.
3. `enhance_library.py` — rebuilds the `LIBRARY` blob + `DATA` blob, plus runs its own military-flag pass. **Must be run after any `library.json` edit**, even if `cleanup_and_build.py` was already run.

## Required integrity checks before considering any change done
- `cleanup_and_build.broken_links(people, families)` returns 0.
- People count is identical across `family-data.json` and this repo's `index.html`'s embedded `DATA`.
- `LIBRARY` blob (regex-extract `const LIBRARY = (\[.*?\]);` from `index.html`, `json.loads`) matches `library.json` doc-for-doc.
- Report these three checks numerically, not narratively, when confirming a change is safe.

## Git / deploy workflow — read carefully, this has bitten us before
- This repo (`site/`) is the only git repo in the project folder. The parent folder's `index.html` and `family-data.json` are working copies, not version-controlled directly.
- Claude typically works from a sandboxed shell that has no delete permission. **Every git command, including read-only ones, leaves a lock file (`index.lock`, `HEAD.lock`, etc.) that can't be removed with `rm`.** Workaround: `mv` the lock file out of the way (rename to something like `index.lock.stale-moved-$(date +%s)`) immediately before each git command, in the same shell invocation, e.g.:
  `(mv .git/index.lock ".git/index.lock.stale-moved-$(date +%s)" 2>/dev/null; true) && git <command>`
- Claude **cannot run `git push`** from this sandbox — it fails with `fatal: could not read Username for 'https://github.com'` because there's no interactive credential store here. Claude can stage, commit, and pull, but the actual push to GitHub must always be done by Sean, from his own machine, via `push-update.bat`.
- **`push-update.bat`'s steps are not reliably halting on failure.** A failed `git add`/`git commit` (e.g. due to a stale lock) does not stop the script from attempting `git pull`/`git push` afterward — and the script prints an unconditional "Done — redeploys in about a minute" message regardless of whether anything was actually pushed. That message is not proof the push worked.
- **To verify a push actually landed**, don't trust the script's printed output alone. Check directly: `git fetch origin main` then `git log --oneline -1 origin/main` and compare against local HEAD, or `git rev-list --left-right --count HEAD...origin/main` (should read `0 0` after a real, successful push).
- Deploy target: GitHub Pages, `seanbmcnulty.github.io/family-tree/`, auto-redeploys ~1 minute after a push to `main` actually lands.
- Working model: Sean wants big local batches of work accumulated, then pushed once ("one big push"), rather than many small pushes.

## Reporting style
Numbers-first, no narrative padding: counts before/after, pass/fail on integrity checks, exact git state (commit hashes, ahead/behind counts). Skip the color commentary.

## Known open items to be aware of
- ~2,349 rows in `fs_review.json` have no `resolved` field — untriaged, lower priority, not part of any closed backlog. Don't treat these as urgent unless Sean asks.
