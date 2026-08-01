# Importing exams from Google Drive

This is the runbook for adding a new batch of exams (a new class, a new
semester, or catching up on exams added to Drive after this was written).
It's written for a future Claude Code session that has none of this
conversation's context — read it top to bottom before starting.

## 1. Where the source PDFs live

Google Drive root folder **"TCDM Exam Banks"** contains 11 semester
subfolders, one per school year/season, named:

```
D1 Summer, D1 Fall, D1 Spring,
D2 Summer, D2 Fall, D2 Spring,
D3 Summer, D3 Fall, D3 Spring,
D4 Fall, D4 Spring
```

(The school year starts in Summer, so within a year the order is
Summer → Fall → Spring. Not every D-year necessarily has a Summer/every
season — check what's actually there.)

Inside each semester folder are per-class subfolders (e.g. "GDA", "DAO",
"Ethics", "PCOD I", "Cariology", "Oral Radiology", "PCOD II"). Inside those,
PDF exam files with inconsistent naming — some say the season/year in the
filename, some don't. **The semester folder the class lives in is what
determines `TYPE_SEMESTER` in index.html, not necessarily the season named
inside the exam.** Example: Cariology exams say "Spring" in their own title
text but the class itself is taught in D1 Fall, and that's the folder they
live in — Fall is what you wire into the app.

If a PDF's filename doesn't tell you the year, download it and check the
first page's text for a line like `Course Name: PCOD II (Spring 2019)`.
Cariology in particular is denoted as "Intro to Cariology" in some folders/years.
If a file has genuinely no year anywhere (this happened once, for a PCOD II
final with no date in the PDF and an ambiguous filename), don't guess — ask
the user.

Use `mcp__Google_Drive__search_files` / `list_recent_files` to locate the
folder, then `download_file_content` on each PDF you need. Small files come
back as inline JSON; large files come back as a path to a `.txt` file under
`/root/.claude/projects/<project>/tool-results/` containing that same JSON
(`{content: base64 pdf bytes, id, mimeType, title}`) — either way, that's
the `json_path` argument `parse_lib.decode_and_save_pdf` expects.

## 2. The parsing pipeline (`parse_lib.py`)

`parse_lib.py` in this directory is a finished, battle-tested library — do
not rewrite it from scratch. It was built up incrementally across the DAO,
PCOD I, Ethics, Cariology, Oral Radiology, and PCOD II imports, fixing real
edge cases found in real exam PDFs (see "Known gotchas" below). Read its
module docstring for the call order. Requires PyMuPDF (`pip install
pymupdf`, imports as `fitz`) — check it's installed before running anything
(`python3 -c "import fitz"`).

Copy `process_batch_template.py` (in this directory) to a scratch working
directory (e.g. `/tmp/.../scratchpad/<batch-name>/`, NOT inside the repo —
it's a throwaway driver script, not something to commit), fill in the
`jobs` list, and run it. It will:

1. Decode each PDF and extract text + embedded images.
2. Parse questions/options/correct-answer/attachment-filename out of the text.
3. Map embedded images to the question they belong to.
4. Print a summary per exam: page count, question count, the numeric range
   found and any gaps in it, and any questions it couldn't parse as
   multiple-choice (no options or no checked answer found).
5. Write the CSV to `exams-csv/` and copy any matched images into
   `images/<exam-id>/`.

**Always check the printed summary before moving on.** A gap in the
question-number range, or a "no questions parsed at all" warning, means
something about that PDF's layout doesn't match the parser's assumptions —
investigate (read `extracted/full_text.txt` for that job) rather than
shipping a truncated exam.

### Questions that aren't multiple choice

Some exams include free-response/short-answer questions that aren't
checkbox-style in the source. The template's skip-detection catches these
(`not q['options'] or q['correct'] is None`) and drops them from the CSV
with a printed note — that's usually the right call, they're not meant to
be gradable in the app as-is. If a "free response" question is actually
meant to be a fill-in-the-blank practice question (rather than genuinely
open-ended), hand-author it into the CSV afterward using the `FILL`
convention (see `../build-exams.js` header comment for the exact format,
or `../exams-csv/cario-*.csv` for a worked example). This has to be done
by hand — the parser has no way to know which blanks are the "acceptable
answers."

### Known gotchas the parser already handles

Do not "fix" these away without understanding why they're there —
each one was added because a specific real exam broke without it:

- **Embedded statement lists before the real options**
  (`find_best_option_run` in parse_lib.py): some questions present a
  lettered list of statements ("A. Statement one / B. Statement two") and
  then a *separate* lettered list of actual answer choices ("a. A only /
  b. B only / c. Both A and B"). The parser splits all letter-prefixed
  lines into runs that break whenever the letter sequence doesn't strictly
  increase, and picks whichever run contains the checkmark.
- **Blank question numbers** (`parse_questions`): the source export
  occasionally has `Question #: ` with nothing after it — a numbering
  glitch, not a missing question. Treated as "one more than the last real
  number seen."
- **Two source formats**: most years use `Question #: N` markers;
  some older years use plain `N. question text` numbering instead
  (`parse_questions_numbered`, auto-selected when no `Question #:` markers
  are found at all).
- **Soft line-wrap hyphenation** (`join_wrapped_lines`): PDF text
  extraction breaks "prevent" across lines as "pre-" / "vent"; rejoined
  by de-hyphenating when a line ends in a letter+hyphen and the next line
  starts lowercase.
- **Watermark/letterhead images** (`map_images_to_questions`): an image
  whose exact bytes repeat identically across more than 2 pages is
  filtered out as a watermark, not treated as a real per-question figure.
- **Duplicate/typo'd option letters in the source**: `write_exam_csv`
  places options *positionally* and re-derives the correct answer from
  which option had the checkmark, rather than trusting the source's letter
  labels (which have occasionally been duplicated by authoring typos).
- **More than 4 options**: the CSV column count auto-expands to fit the
  widest question in the batch (`max_opts` in `write_exam_csv`), not
  hardcoded to A-D.

If a new PDF breaks the parser in a way not covered above, fix
`parse_lib.py` itself (it's shared, reusable infrastructure) and add a
bullet here documenting the new gotcha.

## 3. Wiring a new category into the app

If the batch is for a **class/category that doesn't exist yet** in the app
(as opposed to just adding more exams to an existing category), you also
need to touch two files — grep each for an existing category (e.g.
`pcod2`) to find every spot to mirror:

- **`scripts/build-exams.js`**: add the new type to `KNOWN_TYPES`, and to
  `KNOWN_SUBTYPES` if it has midterm/final/quiz subtypes.
- **`index.html`**: add entries to `TYPE_LABELS`, `TYPE_ORDER`,
  `SUBTYPES_BY_TYPE` (if applicable), and `TYPE_SEMESTER` (which
  semester-year the homepage groups it under — see the Drive-folder note
  in section 1 above about using the folder's semester, not the season in
  the exam's own title).

Existing categories and their current semester assignments are visible
directly in `index.html`'s `TYPE_SEMESTER` block — read it rather than
trusting this doc to stay in sync, since it will drift as more semesters
are added.

## 4. Build, verify, ship

```
node scripts/build-exams.js   # regenerates exams.json from exams-csv/*.csv — never hand-edit exams.json
python3 -m http.server 8000   # from the repo root, to preview locally
```

Before shipping, visually verify in a real browser (Playwright is
pre-installed at `/opt/pw-browsers/chromium`) — click into the new
category/exams, take at least one exam, confirm images render, confirm
question counts match what the Drive PDF summary reported. Don't rely on
`build-exams.js` running without errors as proof the content is right.

Then commit, push to the working branch, open a PR, and merge — see the
top-level `CLAUDE.md` for the exact git/PR workflow and this repo's
standing auto-ship policy for additive content changes.
