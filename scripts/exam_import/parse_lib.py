"""Reusable PDF->CSV pipeline for importing TCDM exam PDFs into exams-csv/.

See README.md in this directory for the full workflow (where the PDFs live
in Drive, how to run this, and known gotchas). In short, per PDF:

    decode_and_save_pdf(json_path, pdf_path)
    text, image_pages, page_count = extract_text_and_images(pdf_path, extract_dir)
    questions = parse_questions(text)
    image_map = map_images_to_questions(pdf_path, map_dir)
    # drop any question with no options/correct answer (free-response in the
    # source -- see README "Questions that aren't multiple choice")
    to_copy = write_exam_csv(questions, image_map, csv_path, title, exam_type,
                              image_url_prefix, subtype=subtype)
    # then copy each (num, src, dest) in to_copy from map_dir into images/<exam_id>/

Requires PyMuPDF: pip install pymupdf (importable as `fitz`).
"""

import re, json, os, base64, fitz

def decode_and_save_pdf(json_path, pdf_out_path):
    """json_path points at a file containing the Google Drive
    download_file_content JSON ({content, id, mimeType, title}); content is
    base64-encoded PDF bytes."""
    with open(json_path) as f:
        data = json.load(f)
    raw = base64.b64decode(data['content'])
    with open(pdf_out_path, 'wb') as out:
        out.write(raw)
    return data['title']

def extract_text_and_images(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    full_text = []
    image_pages = {}
    for i, page in enumerate(doc):
        text = page.get_text()
        full_text.append(text)
        imgs = page.get_images(full=True)
        if imgs:
            image_pages[i+1] = []
            for j, img in enumerate(imgs):
                xref = img[0]
                base = doc.extract_image(xref)
                ext = base['ext']
                fname = f'page{i+1:02d}_img{j+1}.{ext}'
                with open(os.path.join(out_dir, fname), 'wb') as f:
                    f.write(base['image'])
                image_pages[i+1].append({'file': fname, 'size': len(base['image']), 'w': base.get('width'), 'h': base.get('height')})
    full_text_str = '\n'.join(full_text)
    with open(os.path.join(out_dir, 'full_text.txt'), 'w') as f:
        f.write(full_text_str)
    return full_text_str, image_pages, len(doc)

def join_wrapped_lines(lines):
    """Join lines with spaces, but de-hyphenate soft line-wrap breaks like
    "pre-" + "vent" -> "prevent" (a word ending in '-' with no preceding
    space, followed by a line starting with a lowercase letter)."""
    result = ''
    for l in lines:
        if result and re.search(r'[a-zA-Z]-$', result) and l[:1].islower():
            result = result[:-1] + l
        elif result:
            result += ' ' + l
        else:
            result = l
    return result


OPT_RE = re.compile(r'^(✓?)\s*([A-Za-z])[.)]\s*(.*)$')
IMG_EXT_RE = re.compile(r'\.(png|jpg|jpeg)$', re.I)

def find_best_option_run(lines):
    """Some exams letter-label an embedded statement list (e.g. 'A. Statement
    one' / 'B. Statement two', or lowercase, or restarting the same case)
    right before the real answer options (e.g. 'a. A only' / 'b. A and B').
    Scanning every letter-prefixed line as an option would treat the
    statement labels as bogus extra options with duplicate/out-of-order
    letters. Instead, split all letter-prefixed lines into "runs" that break
    wherever the letter sequence doesn't strictly increase (A,B,C then
    restarting at A signals a new, unrelated list) and pick whichever run
    contains the checkmark -- that's the real option list. Returns a dict of
    {line_idx: (checked, letter_upper)} for lines in the chosen run, or {}
    if no letter-prefixed lines are found at all."""
    runs = []
    current = []
    prev_val = None
    for idx, l in enumerate(lines):
        m = OPT_RE.match(l)
        if not m:
            continue
        check, letter, _ = m.groups()
        val = letter.upper()
        if prev_val is not None and val <= prev_val:
            runs.append(current)
            current = []
        current.append((idx, check, val))
        prev_val = val
    if current:
        runs.append(current)
    if not runs:
        return {}
    chosen = next((run for run in runs if any(c == '✓' for _, c, _ in run)), runs[-1])
    return {idx: (check, val) for idx, check, val in chosen}

def parse_option_block(lines):
    """Parse a single question's lines into (question_text, options, correct_letter, attachment)."""
    option_idxs = find_best_option_run(lines)
    question_lines = []
    options = []
    correct_letter = None
    attachment = None
    seen_option = False
    i2 = 0
    while i2 < len(lines):
        l = lines[i2]
        if i2 in option_idxs:
            seen_option = True
            check, letter = option_idxs[i2]
            optxt = OPT_RE.match(l).group(3)
            j = i2 + 1
            while j < len(lines) and j not in option_idxs and lines[j] != 'Attachment:' and not IMG_EXT_RE.search(lines[j]):
                optxt = join_wrapped_lines([optxt, lines[j]])
                j += 1
            options.append((letter, optxt.strip()))
            if check == '✓':
                correct_letter = letter
            i2 = j
            continue
        if l == 'Attachment:':
            j = i2 + 1
            fname_parts = []
            while j < len(lines):
                fname_parts.append(lines[j])
                j += 1
            attachment = ' '.join(fname_parts).strip()
            i2 = j
            continue
        if not seen_option:
            question_lines.append(l)
        i2 += 1
    qtext = join_wrapped_lines(question_lines).strip()
    return qtext, options, correct_letter, attachment

def parse_questions(text):
    # The question number after "Question #:" is occasionally blank in the
    # source export (a numbering glitch, not a missing question) -- treat
    # that as "one more than the last real number seen" rather than losing
    # the split point, which would otherwise silently merge that whole
    # question into the previous one's last option as garbage text.
    parts = re.split(r'Question #:\s*(\d*)\s*', text)
    if len(parts) < 2:
        # numbered format "N\. text" without "Question #:" (used in some years)
        return parse_questions_numbered(text)
    questions = {}
    last_num = 0
    for i in range(1, len(parts), 2):
        num_str = parts[i]
        num = int(num_str) if num_str else last_num + 1
        last_num = num
        block = parts[i+1]
        lines = [l.strip() for l in block.split('\n')]
        lines = [l for l in lines if l != '' and not re.fullmatch(r'_{15,}', l)]
        qtext, options, correct_letter, attachment = parse_option_block(lines)
        questions[num] = {'text': qtext, 'options': options, 'correct': correct_letter, 'attachment': attachment}
    return questions

def parse_questions_numbered(text):
    """Format: "N. question text" or "N) question text" ... "A. opt" / "✓B. opt"
    (no "Question #:" markers)."""
    lines = [l.strip() for l in text.split('\n')]
    lines = [l for l in lines if l != '' and not re.fullmatch(r'_{15,}', l)]
    q_start_re = re.compile(r'^(\d+)[.)]\s*(.*)$')

    # find candidate question-start lines, keeping only sequentially-increasing numbers
    starts = []  # (line_index, num, rest_of_line)
    expected = 1
    for i, l in enumerate(lines):
        m = q_start_re.match(l)
        if m and int(m.group(1)) == expected:
            starts.append((i, expected, m.group(2)))
            expected += 1

    questions = {}
    for si, (line_idx, num, first_line_rest) in enumerate(starts):
        end_idx = starts[si + 1][0] if si + 1 < len(starts) else len(lines)
        block_lines = ([first_line_rest] if first_line_rest else []) + lines[line_idx + 1:end_idx]
        qtext, options, correct_letter, attachment = parse_option_block(block_lines)
        questions[num] = {'text': qtext, 'options': options, 'correct': correct_letter, 'attachment': attachment}
    return questions

def map_images_to_questions(pdf_path, out_dir):
    """Walk each page's content blocks in reading order, tracking the current
    'Question #: N' seen so far, and assign each image block to that question.
    Images whose exact bytes repeat across more than 2 pages are dropped as
    letterhead/watermark artifacts (a real embedded figure is essentially
    never bit-identical across more than a couple of pages; a watermark is
    bit-identical on nearly every page of the document)."""
    import hashlib
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    q_re = re.compile(r'Question #:\s*(\d+)')
    q_re_numbered = re.compile(r'^(\d+)\\?\.\s')
    candidates = []  # list of (current_q, page_no, hash, ext, bytes, w, h)
    current_q = None
    for page_no, page in enumerate(doc):
        blocks = page.get_text('dict')['blocks']
        blocks.sort(key=lambda b: (round(b['bbox'][1], 1), round(b['bbox'][0], 1)))
        for b in blocks:
            if b['type'] == 0:
                for line in b.get('lines', []):
                    line_text = ''.join(span['text'] for span in line.get('spans', []))
                    m = q_re.search(line_text)
                    if m:
                        current_q = int(m.group(1))
                        continue
                    m2 = q_re_numbered.match(line_text.strip())
                    if m2:
                        current_q = int(m2.group(1))
            elif b['type'] == 1:
                h = hashlib.md5(b['image']).hexdigest()
                candidates.append((current_q, page_no, h, b.get('ext', 'png'), b['image'], b.get('width'), b.get('height')))
    pages_per_hash = {}
    for _, page_no, h, *_ in candidates:
        pages_per_hash.setdefault(h, set()).add(page_no)
    result = {}
    img_counter = 0
    for current_q, page_no, h, ext, data, w, ht in candidates:
        if len(pages_per_hash[h]) > 2:
            continue  # repeats across too many pages to be a real figure
        img_counter += 1
        fname = f'mapped_img{img_counter}.{ext}'
        with open(os.path.join(out_dir, fname), 'wb') as f:
            f.write(data)
        result.setdefault(current_q, []).append({'file': fname, 'w': w, 'h': ht})
    return result

def write_exam_csv(questions, image_map, out_csv_path, title, exam_type, image_url_prefix, subtype=''):
    """questions: {num: {text, options:[(letter,text)], correct, ...}}
    image_map: {num: [{'file':..., ...}]} (question num as int)
    Writes CSV and returns list of (question_num, source_image_file, dest_name) to copy.
    Options are placed POSITIONALLY (ignoring source letter labels, which are
    occasionally duplicated by authoring typos) and "correct" is re-derived
    from the position of the checked option, not trusted as a letter lookup.
    This does not handle fill-in-the-blank (FILL) rows -- those questions
    are typically flagged by the caller (no options/correct parsed) and
    either omitted with an issues note, or hand-authored into the CSV
    afterward using the FILL convention (see README.md)."""
    import csv
    to_copy = []
    max_opts = max((len(v['options']) for v in questions.values()), default=4)
    max_opts = max(max_opts, 4)
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:max_opts]
    with open(out_csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['title', title, exam_type, subtype])
        w.writerow(['question'] + [f'option_{l.lower()}' for l in letters] + ['correct', 'image'])
        for n in sorted(questions.keys()):
            v = questions[n]
            opt_letters = [l for l, t in v['options']]
            opt_texts = [t for l, t in v['options']]
            if len(set(opt_letters)) != len(opt_letters):
                print(f'  WARNING: question {n} has duplicate option letters in source: {opt_letters}')
            if v['correct'] not in opt_letters:
                raise ValueError(f'question {n}: correct letter {v["correct"]!r} not found among option letters {opt_letters}')
            correct_idx = opt_letters.index(v['correct'])
            row_opts = opt_texts + [''] * (len(letters) - len(opt_texts))
            image_field = ''
            imgs = image_map.get(n) or image_map.get(str(n))
            if imgs:
                src = imgs[0]['file']
                ext = src.split('.')[-1]
                dest_name = f'fig{n}.{ext}'
                image_field = f'{image_url_prefix}{dest_name}'
                to_copy.append((n, src, dest_name))
            w.writerow([v['text']] + row_opts + [letters[correct_idx], image_field])
    return to_copy
