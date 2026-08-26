"""Template driver script for importing a batch of exam PDFs.

This is NOT meant to be run from inside the repo or committed anywhere —
copy it to a scratch directory (e.g. your session's scratchpad), fill in
`jobs` below with the PDFs for this batch, and run it from there:

    cp process_batch_template.py /tmp/.../scratchpad/<batch-name>/process.py
    cd /tmp/.../scratchpad/<batch-name>/
    python3 process.py

See README.md in this directory for the full workflow this fits into
(where to find the PDFs in Drive, how to wire up a brand-new category,
how to ship the result). Requires PyMuPDF (`pip install pymupdf`).
"""
import sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ^ if you copied this file elsewhere, point this at the real
# scripts/exam_import/ directory instead so `parse_lib` is importable.
from parse_lib import decode_and_save_pdf, extract_text_and_images, parse_questions, map_images_to_questions, write_exam_csv

BASE = os.path.dirname(os.path.abspath(__file__))

# Each job: (folder, json_path, title, exam_id, exam_type, subtype)
#   folder    - scratch subdirectory name for this PDF's intermediate files
#   json_path - path to the Google Drive download_file_content JSON (either
#               the inline result saved to a file, or the tool-results .txt
#               path the tool gives you directly for large files)
#   title     - human-readable exam title shown in the app, e.g.
#               "PCOD II Final Exam (Spring 2020)"
#   exam_id   - CSV filename stem == JSON exam key, following
#               {type}-{subtype}-{season}-{year}[-{n}].csv, e.g.
#               "pcod2-final-spring-2020" or "pcod2-quiz-spring-2017-1"
#               for the 1st of multiple quizzes in the same term
#   exam_type - must be in KNOWN_TYPES in scripts/build-exams.js
#   subtype   - must be in KNOWN_SUBTYPES[exam_type] if that type requires
#               one, else '' (see build-exams.js header comment)
jobs = [
    # ('final2024', '/path/to/tool-results/....txt', 'PCOD II Final Exam (Spring 2024)', 'pcod2-final-spring-2024', 'pcod2', 'final'),
]

CSV_DIR = '/home/user/TCDM-practice-exams/exams-csv'
IMG_DIR = '/home/user/TCDM-practice-exams/images'

for folder, json_path, title, exam_id, exam_type, subtype in jobs:
    out_dir = os.path.join(BASE, folder)
    pdf_path = os.path.join(out_dir, 'exam.pdf')
    extract_dir = os.path.join(out_dir, 'extracted')
    map_dir = os.path.join(out_dir, 'mapped')
    print(f'=== {exam_id} ===')
    decode_and_save_pdf(json_path, pdf_path)
    text, image_pages, page_count = extract_text_and_images(pdf_path, extract_dir)
    questions = parse_questions(text)
    image_map = map_images_to_questions(pdf_path, map_dir)
    print(f'  pages={page_count} questions={len(questions)} image_qs={len(image_map)}')

    nums = sorted(questions.keys())
    if nums:
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in questions]
        print(f'  q range {nums[0]}-{nums[-1]}, missing: {gaps}')
    else:
        print('  WARNING: no questions parsed at all! check extracted/full_text.txt')

    # Drop questions that weren't multiple-choice in the source (free
    # response, etc). Hand-author these into the CSV afterward as FILL
    # rows if they should become fill-in-the-blank questions instead of
    # being dropped -- see README.md "Questions that aren't multiple choice".
    skipped = []
    for n in nums:
        q = questions[n]
        if not q.get('blanks') and (not q['options'] or q['correct'] is None):
            print(f'  SKIP q{n} (not multiple-choice in source): {q["text"][:100]!r}')
            skipped.append(n)
    for n in skipped:
        del questions[n]

    img_dir_dest = os.path.join(IMG_DIR, exam_id)
    os.makedirs(img_dir_dest, exist_ok=True)
    csv_path = os.path.join(CSV_DIR, f'{exam_id}.csv')
    to_copy = write_exam_csv(questions, image_map, csv_path, title, exam_type,
                              f'images/{exam_id}/', subtype=subtype)
    for n, src, dest in to_copy:
        shutil.copy(os.path.join(map_dir, src), os.path.join(img_dir_dest, dest))
    print(f'  wrote {csv_path}, copied {len(to_copy)} images')

print('\nDone. Now: cd to the repo, run `node scripts/build-exams.js`, preview')
print('with `python3 -m http.server`, verify in a browser, then commit/push/PR.')
