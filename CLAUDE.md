# TCDM Practice Exams

A static GitHub Pages site of practice exams for TCDM (dental school)
students. No backend, no build tooling beyond one Node script.

## Architecture

- **`index.html`** — the entire app: vanilla JS/CSS, single file, no
  framework, no build step. Homepage groups exams by semester
  (`TYPE_SEMESTER`), then by category (`TYPE_LABELS`/`TYPE_ORDER`), then by
  subtype (`SUBTYPES_BY_TYPE`) where applicable. Handles quiz-taking,
  grading, and per-exam score history (localStorage, keyed by exam id).
  Supports both normal multiple-choice questions and fill-in-the-blank
  questions (`type: 'fill'`).
- **`exams.json`** — generated. **Never hand-edit.** Regenerate with
  `node scripts/build-exams.js` after editing CSVs.
- **`exams-csv/*.csv`** — source of truth for exam content, one file per
  exam, named `{type}-{subtype}-{season}-{year}[-{n}].csv` (the filename
  stem is also the exam's id used everywhere: JSON key, URL, localStorage
  score key). Format is documented in the header comment of
  `scripts/build-exams.js` — read that before hand-authoring a CSV.
- **`scripts/build-exams.js`** — zero-dependency Node script, CSV → JSON
  compiler. Also the canonical reference for `KNOWN_TYPES` /
  `KNOWN_SUBTYPES` (which categories/subtypes currently exist) and the
  exact CSV format including the `FILL` fill-in-the-blank convention.
- **`images/<exam-id>/*`** — figure assets referenced by CSV `image`
  columns.
- **`scripts/exam_import/`** — the PDF→CSV import pipeline (Python) used
  to bulk-import exams from the Google Drive exam bank, plus a detailed
  runbook. **Start here** when asked to add new exams or a new
  class/category: `scripts/exam_import/README.md`.

## Common tasks

- **Add exams to an existing category**: use
  `scripts/exam_import/` (see its README) to parse PDFs from Drive into
  CSVs, or hand-author a CSV directly if there's no PDF to parse. Then run
  `node scripts/build-exams.js` and verify in a browser before shipping.
- **Add a brand-new category/class**: same as above, plus wire it into
  `KNOWN_TYPES`/`KNOWN_SUBTYPES` in `build-exams.js` and
  `TYPE_LABELS`/`TYPE_ORDER`/`SUBTYPES_BY_TYPE`/`TYPE_SEMESTER` in
  `index.html`. Full steps in `scripts/exam_import/README.md` section 3.
- **Local preview**: `python3 -m http.server` from the repo root.

## Shipping workflow

Work happens on branch `claude/repo-code-access-p6vcix`, pushed to
`origin`, then a PR is opened and merged into `main` via the GitHub MCP
tools. Standing policy for this repo: after verifying a change works
(build succeeds, and for UI-visible changes, a real browser check via
Playwright), push and open+merge the PR without waiting for a separate
explicit approval — this only applies to routine, additive content/tooling
changes (new exams, new categories, docs), not to anything destructive or
architecturally significant.

Note: when creating a PR via the GitHub MCP tools, use owner `xjengax`
(that's what this session's GitHub access is scoped to) even though the
repo may display under a different owner name — GitHub redirects
transparently on rename/transfer.
