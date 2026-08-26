# Importing exams from Google Drive

This is the runbook for adding a new batch of exams (a new class, a new
semester, or catching up on exams added to Drive after this was written).
It's written for a future Claude Code session that has none of this
conversation's context — read it top to bottom before starting.

## 1. Where the source PDFs live

Google Drive root folder **"TCDM Exam Banks"** contains one subfolder per
school year/season, plus one non-semester **"Elective"** folder. As of the
D3 Fall/D3 Spring/D4 Summer/D4 Fall batch, the semester folders are:

```
D1 Summer, D1 Fall, D1 Spring,
D2 Summer, D2 Fall, D2 Spring,
D3 Summer, D3 Fall, D3 Spring,
D4 Summer, D4 Fall
```

(The school year starts in Summer, so within a year the order is
Summer → Fall → Spring. Not every D-year necessarily has a Summer/every
season, and this list will drift as more semesters get added to Drive —
list the root folder with an explicit large `pageSize` rather than trusting
this doc to stay in sync.)

**"Elective" is not a school-year semester** — it groups standalone
elective courses (first seen: a single "Surgical Principles of Periodontics
& Implant Dentistry" final exam) and, unlike the semester folders, its PDFs
so far sit directly in the folder rather than inside a per-class subfolder.
It's wired into `index.html` the same way a semester is (its own
`SEMESTER_ORDER` entry, sorted chronologically after the last real
semester) — see section 4.

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

**Always list a folder's contents with an explicit large `pageSize` (e.g.
50), never the default.** This is not optional — with no `pageSize` set,
`search_files` silently truncates to a small default page, and re-fetching
with the returned `pageToken` can come back *identical* to the first page
instead of actually advancing. Comparing two default-size fetches and
seeing the same file set does **not** prove the folder is fully
enumerated — it proves nothing, since a second default-size fetch can fail
to advance for reasons unrelated to the folder actually being exhausted.
This isn't a hypothetical: it's exactly how 7 exams got missed in the Intro
to Clinical Dentistry unit (default-size fetch found 10 files; explicit
`pageSize: 50` found 17) and 3 more got missed in Orthodontics on a
re-check (found only after the fact). A response with no `nextPageToken`
field at all is the actual "nothing more" signal — get there by asking for
enough results up front, not by trusting a token comparison.

## 2. Reconnaissance: skim before you parse

Before running the batch pipeline (or writing any code to extend it), do a
quick pass over the raw material and form a plan — this is standard
practice for every batch, not just ones that look unusual going in. It's
cheap to do up front and expensive to discover midway through a batch
you've already half-built:

- **Extract text from each PDF and skim it** (`extract_text_and_images` is
  enough — you don't need the full pipeline yet). Check the first page for
  the actual course name/date (catches filename-vs-content year mismatches
  like the Cariology gotcha in section 1), and grep for `Attachment:` to
  see whether questions reference shared exhibits, and if so whether the
  same attachment name repeats across a run of consecutive questions (a
  case cluster, see "Case clusters" below) rather than each question having
  its own distinct figure.
- **List the class folder itself with an explicit large `pageSize`
  first**, before assuming you have the full set of source PDFs to skim in
  the first place — see the pagination warning in section 1 above. Do this
  even for a folder that "looks done"; it's the step that was skipped when
  10 exams were assumed to be all of Intro to Clinical Dentistry when 17
  actually existed.
- **For any attachment that isn't embedded in the exam's own pages**,
  confirm the referenced file actually exists in Drive before planning
  around it — same explicit-`pageSize` rule applies.
- **Compare against what's already in the repo**: does this category exist
  yet (`KNOWN_TYPES`)? Do the exam ids collide with anything in
  `exams-csv/`? Does the source use a format `parse_lib.py` hasn't seen
  before?

If this turns up anything that isn't "a standard flat multiple-choice exam,
same shape as what's already been imported" — a new attachment/exhibit
pattern, a missing referenced file, an ambiguous or absent date, a format
the parser doesn't already handle — stop and walk through a plan with the
user before writing code or running the batch, the same way the
Orthodontics unit's case-cluster pattern and its two exams with missing
attachments got handled. Don't guess and don't silently work around a gap.

## 3. The parsing pipeline (`parse_lib.py`)

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
  are found at all). That plain-numbering format and its option letters
  are sometimes punctuated with `)` instead of `.` (e.g. `1) question` /
  `a) option`) depending on the source document; both are accepted.
- **Soft line-wrap hyphenation** (`join_wrapped_lines`): PDF text
  extraction breaks "prevent" across lines as "pre-" / "vent"; rejoined
  by de-hyphenating when a line ends in a letter+hyphen and the next line
  starts lowercase.
- **Watermark/letterhead images** (`map_images_to_questions`): an image
  whose exact bytes repeat identically across more than half the document's
  pages is filtered out as a watermark, not treated as a real figure. (This
  used to be a flat ">2 pages" cutoff; raised to scale with document length
  once the Orthodontics unit showed up with figures legitimately repeated
  across 5-10 consecutive pages -- see "Case clusters" below.)
- **Duplicate/typo'd option letters in the source**: `write_exam_csv`
  places options *positionally* and re-derives the correct answer from
  which option had the checkmark, rather than trusting the source's letter
  labels (which have occasionally been duplicated by authoring typos).
- **More than 4 options**: the CSV column count auto-expands to fit the
  widest question in the batch (`max_opts` in `write_exam_csv`), not
  hardcoded to A-D.
- **Picture-based answer options**: some questions (first seen in OMFS,
  D2 Spring) letter-label their options A-E but give each one no text at
  all -- the options themselves are images (e.g. "which of these forceps",
  each choice a photo in an attached case PDF). The CSV schema only
  supports one image per *question*, not per option, so there's no way to
  carry this; `parse_option_block` detects an option run where every
  option's text is blank and treats it like a free-response question
  (dropped, per "Questions that aren't multiple choice" above) rather than
  writing a row with empty options that `build-exams.js` would reject.
- **`*` as the correct-answer marker instead of `✓`**: some source PDFs
  (first seen in Intro to Implants, D2 Spring) mark the correct option with
  a literal asterisk (`*d. Removable`) rather than a checkmark. `OPT_RE`
  and the option-parsing code in `parse_lib.py` accept either character as
  "this option is correct" — a `no questions parsed`/"every question
  skipped as not-multiple-choice" result on an otherwise normal-looking
  numbered exam is the symptom to watch for if a *third* marker style ever
  shows up.
- **Three source formats, not two**: some exams (first seen in Lasers in
  Dentistry, Summer 2023) have no numbering markers at all -- not
  `Question #:`, not plain `N.`/`N)`, nothing. `parse_questions_numbered`
  falls back to `parse_questions_unmarked` when it finds zero `N.`-style
  starts: question boundaries are inferred purely from where a fresh
  `a`/`A`-lettered option run begins (stem lines accumulate until the next
  `a`/`A` option line, then lettered options accumulate while strictly
  increasing). This format also has no `Question #:` split to discard the
  document's own header banner, so `parse_questions_unmarked` separately
  strips leading lines ending in "Confidential" (every source PDF in this
  bank opens with one, e.g. "Lasers in Dentistry Final Exam -
  Confidential") before scanning for question 1. A `no questions parsed at
  all` result on an exam that clearly has lettered options in the raw text
  (unlike the picture-based-options gotcha, where the options are present
  but blank) is the symptom of this format.

If a new PDF breaks the parser in a way not covered above, fix
`parse_lib.py` itself (it's shared, reusable infrastructure) and add a
bullet here documenting the new gotcha.

### Case clusters (one exhibit shared across several consecutive questions)

First seen in the Orthodontics unit (D2 Fall): rather than each question
carrying its own figure, a block of consecutive questions all say "Refer to
[the] case" and share one clinical exhibit (a photo grid, a panoramic
X-ray, or both), given via an identical `Attachment:` value repeated under
every question in the block (e.g. `CASE 1.jpg` under questions 1-10). This
shows up in two different forms depending on the source PDF, and a single
exam can mix both:

- **Embedded**: the exhibit image(s) are embedded directly in the exam PDF,
  repeated on every page in the block. `map_images_to_questions` already
  picks these up per-question (that's what the relaxed watermark threshold
  above is for) -- no extra lookup needed.
- **External**: the exhibit isn't in the exam PDF at all; it's a *separate*
  PDF uploaded alongside it in the same Drive folder (e.g.
  `Case 2 PDF.pdf`). The filename inside the exam text is **not**
  reliable for an exact match against Drive (`Case 2 PDF.pdf` in the text
  vs. `Spring 2023 Ortho Final Exam - Case 2.pdf` on Drive) -- find it by
  fuzzy title match (e.g. "contains 'Case 2'") within the same subfolder,
  download it, and pull its images with `extract_all_images`.

Workflow: after `parse_questions`, call `find_attachment_clusters(questions)`
to get `[(attachment_text, [question_nums]), ...]` for every contiguous run
sharing one non-blank attachment (case-insensitive, since the source has
typo'd casing on the same attachment mid-block at least once). For each
cluster, `resolve_case_clusters(image_map, clusters, map_dir,
external_images)` composites that cluster's image(s) into one file (via
`composite_images`, stacked vertically -- keeps the CSV/app to one
`image` field per question, no schema change) and points every question in
the cluster at it. `external_images` is `{attachment_text: [images]}` for
clusters you had to resolve externally (build it yourself from
`extract_all_images` before calling); a cluster with no embedded images and
no entry there raises rather than silently shipping a blank exhibit.

Watch for **re-embedded duplicates**: some source PDFs embed the *same*
exhibit image twice per question (identical pixel dimensions, different
JPEG bytes from re-compression) rather than one image appearing once.
`resolve_case_clusters` dedupes by pixel dimensions before compositing so
these don't get stacked on top of a copy of themselves -- this means two
*genuinely* different exhibits that happen to share exact dimensions would
wrongly get merged into one. Low probability, but it's why you check the
composited screenshot (via `verify_batch.js`) for any newly-added
case-based exam rather than trusting the pipeline blind.

If a case's external attachment PDF genuinely isn't in the Drive folder
(list the folder with an explicit large `pageSize` per section 1 before
concluding this — do not trust a default-size fetch), don't guess or ship
the affected questions without their exhibit. Ask the user whether to hold
the exam, drop the affected questions, or ship with an `issues` note — this
happened for two Spring 2022 exams and cost real rework to notice after the
fact instead of before parsing.

## 4. Wiring a new category into the app

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

## 5. Build, verify, ship

```
node scripts/build-exams.js   # regenerates exams.json from exams-csv/*.csv — never hand-edit exams.json
```

Before shipping, run the automated browser check instead of clicking
through the app by hand:

```
NODE_PATH="$(npm root -g)" node scripts/exam_import/verify_batch.js <exam-id> [exam-id...]
```

(pass the same `exam-id`s used in the batch's `jobs` list). It starts a
local server itself, loads the app in headless Chromium, jumps straight to
every question of each exam, and checks: `exams.json`'s question count
against the CSV's row count (catches a forgotten `build-exams.js` rerun),
every question's rendered option/blank count against `exams.json`, and that
every question image actually loads (not a 404). It screenshots one
question per exam (preferring one with an image) to
`/tmp/exam-verify-screenshots/<exam-id>.png` (override with `--out=`) —
look at those to confirm the content actually reads right, since the script
checks structure, not correctness of the parsed text/answers. Exits
non-zero if anything failed. Don't rely on `build-exams.js` running without
errors as proof the content is right.

Requires the `playwright` package + Chromium (both pre-installed in this
environment — see the module docstring in `verify_batch.js` if
`require('playwright')` fails).

If `verify_batch.js` throws `Cannot read properties of undefined (reading
'0')` from `renderQuiz` for *every* exam (not just newly-imported ones),
`index.html`'s `quizState` picked up a new field (e.g. `optionOrder`,
added for the answer-shuffling feature) that the script's hand-built
`quizState` object in its `page.evaluate` call doesn't set — fix the
script to match how `index.html` itself constructs `quizState` when
starting a quiz, rather than assuming the batch just imported is at
fault.

Then commit, push to the working branch, open a PR, and merge — see the
top-level `CLAUDE.md` for the exact git/PR workflow and this repo's
standing auto-ship policy for additive content changes.

## 6. Keep this doc (and others) current

This file exists because a future Claude Code session will start with none
of the current conversation's context — the whole point is to not have to
rediscover things the hard way twice. So: whenever you hit something during
a batch that isn't already written down here — a new Drive folder quirk, a
new parser gotcha, a wrinkle in the shipping workflow, a preference or
correction the user gave you mid-session that'll matter again next time —
add it before you finish, not just when explicitly asked to update docs.

Put it wherever a future session would actually look for it: a parser
edge case goes in "Known gotchas" above, a Drive/folder quirk goes in
section 1, a workflow change goes in section 5, and anything about the app
or repo generally (not specific to importing) belongs in the top-level
`CLAUDE.md` instead of here. If it doesn't fit any existing doc, it's fine
to say so and ask the user where it should live rather than skipping it.
