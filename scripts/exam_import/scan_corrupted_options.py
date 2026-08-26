#!/usr/bin/env python3
"""Sweep exams-csv/*.csv for the "orphaned text glued onto the wrong
option" signature described in README.md ("Text-only case clusters" and
the embedded-numbered-sub-list gotcha in `parse_questions_numbered`).

Both bugs left the same fingerprint in already-shipped CSVs: a
question/option/image cell containing prose that belongs to a *different*
question -- almost always because it's abnormally long and/or contains
phrasing that only appears in a case-intro paragraph ("the next N
questions...", "pertain(s) to", "CASE <TAG>", "scenario applies to
questions N-M", etc).

This is a static content scan -- it only reads the already-generated
CSVs, so it works even for exams imported in a session that no longer has
the source PDF cached. It is a *triage* tool, not an auto-fixer: both
signals have false positives (a legitimately long answer choice; the
ordinary English word "case"), so treat "long AND phrase-matching" as a
near-certain hit and anything else as "worth a human look," not a
confirmed bug. Re-derive a confirmed hit by re-running the import
pipeline on that exam's source PDF (see README.md).

Usage: python3 scan_corrupted_options.py [exams-csv-dir]
"""
import csv, glob, os, re, sys

LENGTH_THRESHOLD = 300
# No legitimate answer choice observed in this corpus has ever exceeded
# ~460 chars (verbose sedation-level definitions, the longest known
# genuine case) -- so a cell past this length is corrupted regardless of
# whether it happens to also match CASE_PHRASE_RE (a heading styled with a
# bullet, e.g. "CASE • Intro:", won't match the phrase regex but is
# just as broken).
EXTREME_LENGTH_THRESHOLD = 700

CASE_PHRASE_RE = re.compile(
    r'(questions?\s*#?s?\s*\d+\s*[-–—]\s*\d+'
    r'|next\s+\d+\s+questions'
    r'|pertain(s|ing)?\s+to\s+(case|Case)'
    r'|refer(s)?\s+to\s+CASE'
    r'|CASE\s+[A-Z]{2,}[\s,-]'
    r'|scenario\s+applies\s+to'
    r'|following\s+scenario)',
    re.I,
)


def scan(csv_dir):
    long_hits = []
    phrase_hits = []
    for path in sorted(glob.glob(os.path.join(csv_dir, '*.csv'))):
        with open(path, encoding='utf-8') as f:
            rows = list(csv.reader(f))
        if len(rows) < 3:
            continue
        header = rows[1]
        for row_num, row in enumerate(rows[2:], start=3):
            for col_idx, cell in enumerate(row):
                if col_idx == 0:
                    continue  # question text itself is expected to be long
                col_name = header[col_idx] if col_idx < len(header) else str(col_idx)
                is_long = len(cell) > LENGTH_THRESHOLD
                is_phrase = bool(CASE_PHRASE_RE.search(cell))
                is_extreme = len(cell) > EXTREME_LENGTH_THRESHOLD
                if (is_long and is_phrase) or is_extreme:
                    long_hits.append((path, row_num, col_name, len(cell), cell[:100]))
                elif is_long or is_phrase:
                    phrase_hits.append((path, row_num, col_name, len(cell), cell[:100]))
    return long_hits, phrase_hits


def main():
    csv_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..', 'exams-csv')
    confirmed, maybe = scan(csv_dir)

    print(f'=== {len(confirmed)} high-confidence hit(s) (long AND case-phrase match) ===')
    for path, row_num, col, length, snippet in confirmed:
        print(f'{path} row {row_num} [{col}] ({length} chars): {snippet!r}')

    print(f'\n=== {len(maybe)} lower-confidence hit(s) (long OR case-phrase, not both) '
          f'-- review manually, expect false positives ===')
    for path, row_num, col, length, snippet in maybe:
        print(f'{path} row {row_num} [{col}] ({length} chars): {snippet!r}')

    return 1 if confirmed else 0


if __name__ == '__main__':
    sys.exit(main())
