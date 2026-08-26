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

import re, json, os, base64, fitz, hashlib

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


OPT_RE = re.compile(r'^([✓*]?)\s*([A-Za-z])[.)]\s*(.*)$')
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
    chosen = next((run for run in runs if any(c in ('✓', '*') for _, c, _ in run)), runs[-1])
    return {idx: (check, val) for idx, check, val in chosen}

ANS_LINE_RE = re.compile(r'^(\d+)[.)]\s*(.+)$')

def find_fill_blanks(lines):
    """Detect the source's own fill-in-the-blank export format: a question
    with no lettered options (checked by the caller) instead ends in lines
    like '1. HAIRY TONGUE' or '2. KAPOSI SARCOMA|ANGIOSARCOMA|' -- one line
    per blank, numbered from 1, holding that blank's acceptable answer(s)
    already pipe-separated (matching the app's own FILL convention, see
    README.md). First seen in Oral Pathology (D2 Spring), where most
    "diagnosis" questions are authored this way rather than as
    multiple-choice. Returns (blanks, line_idxs) -- blanks is a list of
    alt-lists, one per blank, in order; line_idxs is the set of line indices
    consumed so the caller can exclude them from the question text -- or
    None if these lines don't form a clean 1..N sequence (don't guess)."""
    found = {}
    for idx, l in enumerate(lines):
        m = ANS_LINE_RE.match(l)
        if not m:
            continue
        found[int(m.group(1))] = (idx, m.group(2))
    if not found:
        return None
    nums = sorted(found.keys())
    if nums != list(range(1, len(nums) + 1)):
        return None
    blanks = []
    idxs = set()
    for num in nums:
        idx, text = found[num]
        idxs.add(idx)
        alts = [a.strip() for a in text.split('|')]
        alts = [a for a in alts if a]
        if not alts:
            return None
        blanks.append(alts)
    # The source also renders each blank's position in the stem as a bare
    # placeholder digit, usually alone on its own line (e.g. a lone "1"
    # line right before the stem wraps) -- drop those too, not just the
    # "N. answer" lines themselves, so a stray number doesn't leak into the
    # question text. A placeholder embedded mid-line alongside real stem
    # text (rarer) isn't caught here; see the flanking-whitespace cleanup
    # in parse_option_block for that case.
    for idx, l in enumerate(lines):
        if idx in idxs:
            continue
        m = re.fullmatch(r'(\d+)', l)
        if m and int(m.group(1)) in found:
            idxs.add(idx)
    return blanks, idxs

def parse_option_block(lines):
    """Parse a single question's lines into (question_text, options,
    correct_letter, attachment, blanks). blanks is None for an ordinary
    multiple-choice question, or a list of per-blank alt-lists (see
    find_fill_blanks) for a FILL-shaped question -- in which case options
    is [] and correct_letter is None."""
    option_idxs = find_best_option_run(lines)
    fill = None if option_idxs else find_fill_blanks(lines)
    fill_idxs = fill[1] if fill else set()
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
            if check in ('✓', '*'):
                correct_letter = letter
            i2 = j
            continue
        if i2 in fill_idxs:
            i2 += 1
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
    if fill:
        # Best-effort cleanup of any blank-placeholder digit the source
        # rendered on the same physical line as real stem text (e.g.
        # "(upper case)    1    .  What is..."), rather than on its own
        # line (already dropped above). Flanked by 2+ spaces on both sides,
        # unlike a real number in prose ("52-year-old", "20 years", single-
        # spaced), so this doesn't touch genuine content.
        qtext = re.sub(r'\s{2,}\d+(?=\s{2,}|$)', ' ', qtext)
        qtext = re.sub(r'^\d+\s{2,}', '', qtext)
        qtext = re.sub(r'\s+', ' ', qtext).strip()
        return qtext, [], None, attachment, fill[0]
    if options and not any(re.search(r'[A-Za-z0-9]', t) for _, t in options):
        # Every option came back with no real text -- the answer choices
        # are themselves images (e.g. "which of these forceps"/"which
        # display of paired teeth", A-E each a picture), which the CSV
        # schema has no way to represent (one image per question, not per
        # option). A blank option sometimes isn't literally empty -- one
        # PDF left a run of decorative dots ("....") where a picture was --
        # so check for actual alphanumeric content, not just non-blank.
        # Not multiple-choice in any form this pipeline can carry, so drop
        # it like a free-response question rather than writing garbage
        # options.
        return qtext, [], None, attachment, None
    return qtext, options, correct_letter, attachment, None

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
        qtext, options, correct_letter, attachment, blanks = parse_option_block(lines)
        questions[num] = {'text': qtext, 'options': options, 'correct': correct_letter, 'attachment': attachment, 'blanks': blanks}
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
        qtext, options, correct_letter, attachment, blanks = parse_option_block(block_lines)
        questions[num] = {'text': qtext, 'options': options, 'correct': correct_letter, 'attachment': attachment, 'blanks': blanks}
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
    # A watermark/letterhead repeats on essentially every page of the
    # document; a real figure shared across a handful of consecutive
    # questions (a "case cluster" -- see find_attachment_clusters) does not
    # get anywhere close to that. Scale the cutoff to the document length
    # instead of a fixed page count so multi-page case clusters (seen first
    # in the Orthodontics unit, where one figure covers 5-10 consecutive
    # questions) don't get discarded as if they were letterhead.
    watermark_threshold = max(2, len(doc) // 2)
    result = {}
    img_counter = 0
    for current_q, page_no, h, ext, data, w, ht in candidates:
        if len(pages_per_hash[h]) > watermark_threshold:
            continue  # repeats across too many pages to be a real figure
        img_counter += 1
        fname = f'mapped_img{img_counter}.{ext}'
        with open(os.path.join(out_dir, fname), 'wb') as f:
            f.write(data)
        result.setdefault(current_q, []).append({'file': fname, 'w': w, 'h': ht})
    return result

def find_attachment_clusters(questions):
    """Group consecutive question numbers that share the same non-blank
    'attachment' value (e.g. "Case 2 PDF.pdf" repeated under questions 11-18)
    -- these questions share one reference exhibit rather than each having
    their own distinct figure. Returns [(attachment_text, [nums]), ...],
    nums sorted ascending and contiguous within each cluster."""
    nums = sorted(questions.keys())
    clusters = []
    cur_att = None
    cur_key = None
    cur_nums = []
    for n in nums:
        att = (questions[n].get('attachment') or '').strip()
        # Compare case-insensitively: the source has typo'd casing on the
        # same attachment within one cluster (e.g. "Case 1.pdf" then
        # "case 1.pdf" a question later, in exam1_2022) -- an exact-string
        # comparison would wrongly split one cluster into several.
        key = att.lower()
        if att and key == cur_key and cur_nums and n == cur_nums[-1] + 1:
            cur_nums.append(n)
        else:
            if cur_nums:
                clusters.append((cur_att, cur_nums))
            cur_att = att or None
            cur_key = key or None
            cur_nums = [n] if att else []
    if cur_nums:
        clusters.append((cur_att, cur_nums))
    return clusters

def extract_all_images(pdf_path):
    """Return every distinct (by byte hash) embedded image in a PDF, in
    reading order. For small single-purpose attachment PDFs (e.g. a "Case 2
    PDF.pdf" exhibit that isn't embedded in the exam's own pages at all) --
    not watermark-filtered, since the whole file is the exhibit, and there's
    no "current question" to attribute images to block-by-block."""
    doc = fitz.open(pdf_path)
    seen = set()
    out = []
    for page in doc:
        blocks = page.get_text('dict')['blocks']
        blocks.sort(key=lambda b: (round(b['bbox'][1], 1), round(b['bbox'][0], 1)))
        for b in blocks:
            if b['type'] != 1:
                continue
            h = hashlib.md5(b['image']).hexdigest()
            if h not in seen:
                seen.add(h)
                out.append({'ext': b.get('ext', 'png'), 'data': b['image']})
    return out

def composite_images(images, out_path):
    """Stack a list of {'ext','data'} embedded images vertically into one
    JPEG at out_path, scaling each to a common width. Used so a case
    cluster's multiple exhibits (e.g. a clinical-photo grid + a panoramic
    radiograph) show up as the one figure a question can carry, instead of
    requiring the app to support multiple images per question. Requires
    Pillow (pip install pillow)."""
    from PIL import Image
    import io
    pil_imgs = [Image.open(io.BytesIO(im['data'])).convert('RGB') for im in images]
    width = max(im.width for im in pil_imgs)
    scaled = []
    for im in pil_imgs:
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)))
        scaled.append(im)
    gap = 10
    total_h = sum(im.height for im in scaled) + gap * (len(scaled) - 1)
    canvas = Image.new('RGB', (width, total_h), 'white')
    y = 0
    for im in scaled:
        canvas.paste(im, (0, y))
        y += im.height + gap
    canvas.save(out_path, quality=88)

def _dedupe_images_by_size(images):
    """Some source PDFs re-embed the exact same case picture more than once
    per question (identical pixel dimensions, different JPEG compression, so
    it doesn't dedupe by byte hash) -- e.g. Case 1/3/4/5 in the Spring 2023
    Orthodontics final each carry one real exhibit image that shows up twice
    in image_map with different bytes. Composite would otherwise stack a
    picture on top of a copy of itself. A genuinely distinct second exhibit
    (Case 2's clinical-photo grid + separate panoramic X-ray) has different
    dimensions, so this dedupe doesn't touch it. Small risk: two truly
    different exhibits that happen to share exact pixel dimensions would get
    wrongly collapsed -- check the composite screenshot when a new
    case-based exam is added."""
    from PIL import Image
    import io
    seen_sizes = set()
    out = []
    for im in images:
        size = Image.open(io.BytesIO(im['data'])).size
        if size in seen_sizes:
            continue
        seen_sizes.add(size)
        out.append(im)
    return out

def resolve_case_clusters(image_map, clusters, map_dir, external_images=None):
    """Composite each attachment cluster's shared image(s) into one file and
    point every question in the cluster at it, overwriting whatever those
    questions' own image_map entries were -- a case cluster's questions
    share one exhibit rather than each having a distinct figure.

    For a cluster whose questions already carry embedded images (the case
    picture is repeated on every page in that range, e.g. "CASE 1.jpg"),
    those already-saved files (from map_images_to_questions) are read back
    and composited. For a cluster with no embedded images at all (the case
    is a separate attachment PDF not embedded in the exam, e.g.
    "Case 2 PDF.pdf"), external_images must supply
    {attachment_text: [{'ext','data'}, ...]} (see extract_all_images) --
    raises if one is needed but missing, rather than silently shipping a
    case cluster with no figure.

    Mutates image_map in place. Returns [(attachment_text, nums, filename)]
    for what was written, for the caller to log."""
    external_images = external_images or {}
    written = []
    counter = 0
    for att, nums in clusters:
        images = None
        for n in nums:
            entries = image_map.get(n)
            if entries:
                images = []
                for e in entries:
                    with open(os.path.join(map_dir, e['file']), 'rb') as f:
                        images.append({'ext': e['file'].rsplit('.', 1)[-1], 'data': f.read()})
                break
        if images is None:
            if att not in external_images:
                raise ValueError(f'case cluster {att!r} (questions {nums}) has no embedded images in the exam and no external images were supplied for it')
            images = external_images[att]
        images = _dedupe_images_by_size(images)
        counter += 1
        fname = f'case{counter}.jpg'
        composite_images(images, os.path.join(map_dir, fname))
        for n in nums:
            image_map[n] = [{'file': fname}]
        written.append((att, nums, fname))
    return written

def write_exam_csv(questions, image_map, out_csv_path, title, exam_type, image_url_prefix, subtype=''):
    """questions: {num: {text, options:[(letter,text)], correct, blanks, ...}}
    image_map: {num: [{'file':..., ...}]} (question num as int)
    Writes CSV and returns list of (question_num, source_image_file, dest_name) to copy.
    Options are placed POSITIONALLY (ignoring source letter labels, which are
    occasionally duplicated by authoring typos) and "correct" is re-derived
    from the position of the checked option, not trusted as a letter lookup.
    A question with v['blanks'] set (see find_fill_blanks in this module) is
    written as a FILL row instead -- one option_* cell per blank, each
    holding that blank's '|'-separated acceptable answers, with "correct"
    set to the literal FILL. Any other free-response question (no options
    parsed and no blanks detected) is the caller's responsibility to drop
    or hand-author, per README.md."""
    import csv
    to_copy = []
    max_opts = max(
        (len(v['blanks']) if v.get('blanks') else len(v['options']) for v in questions.values()),
        default=4,
    )
    max_opts = max(max_opts, 4)
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:max_opts]
    with open(out_csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['title', title, exam_type, subtype])
        w.writerow(['question'] + [f'option_{l.lower()}' for l in letters] + ['correct', 'image'])
        for n in sorted(questions.keys()):
            v = questions[n]
            image_field = ''
            imgs = image_map.get(n) or image_map.get(str(n))
            if imgs:
                src = imgs[0]['file']
                ext = src.split('.')[-1]
                dest_name = f'fig{n}.{ext}'
                image_field = f'{image_url_prefix}{dest_name}'
                to_copy.append((n, src, dest_name))
            if v.get('blanks'):
                row_opts = ['|'.join(alts) for alts in v['blanks']] + [''] * (len(letters) - len(v['blanks']))
                w.writerow([v['text']] + row_opts + ['FILL', image_field])
                continue
            opt_letters = [l for l, t in v['options']]
            opt_texts = [t for l, t in v['options']]
            if len(set(opt_letters)) != len(opt_letters):
                print(f'  WARNING: question {n} has duplicate option letters in source: {opt_letters}')
            if v['correct'] not in opt_letters:
                raise ValueError(f'question {n}: correct letter {v["correct"]!r} not found among option letters {opt_letters}')
            correct_idx = opt_letters.index(v['correct'])
            row_opts = opt_texts + [''] * (len(letters) - len(opt_texts))
            w.writerow([v['text']] + row_opts + [letters[correct_idx], image_field])
    return to_copy
