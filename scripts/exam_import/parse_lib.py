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

def _checkmarked_option_run_count(lines):
    """Same run-grouping as find_best_option_run, but returns how many
    distinct runs carry a checked/starred answer instead of picking one.
    Used by parse_questions_numbered to tell "this span is exactly one
    real answered question" (count == 1) apart from a span that
    accidentally spans zero or multiple real questions."""
    runs = []
    current = []
    prev_val = None
    for l in lines:
        m = OPT_RE.match(l)
        if not m:
            continue
        check, letter, _ = m.groups()
        val = letter.upper()
        if prev_val is not None and val <= prev_val:
            runs.append(current)
            current = []
        current.append(check)
        prev_val = val
    if current:
        runs.append(current)
    return sum(1 for run in runs if any(c in ('✓', '*') for c in run))

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

# A named-tag heading, e.g. "CASE AB", "Case #1" -- captures a short token
# usable as a back-reference key for each question's own "(CASE AB)" /
# "(Case #1 attached)" tag (see CASE_TAG_RE below).
CASE_TAG_HEADING_RE = re.compile(r'^(?:CASE|Case)\s*#?\s*([A-Za-z0-9]+)\b')
# The much wider net of phrasings actually seen introducing a case, none of
# which necessarily carry a clean short tag to key off of: a bare "CASE" on
# its own line before a bulleted patient summary (Pathomedicine, Exam 2
# Fall 2020); "CONSIDER THE CASE SCENARIO DESCRIBED BELOW WHEN ANSWERING
# QUESTIONS 43-50..." (Oral & Maxillofacial Surgery, Final Spring 2020);
# "The following scenario applies to questions 50-53:" (same course, Final
# Spring 2021). Exams using one of these don't tag each question with a
# back-reference either -- they just expect the reader to remember the
# case for the next few questions -- so there's nothing here to match
# CASE_TAG_RE against; the vignette only needs to reach the question
# immediately following it (see parse_questions_numbered's
# `pending_vignette` handling), not every question in the block.
CASE_INTRO_TRIGGER_RE = re.compile(
    r'^(?:CASE|Case)\s*#?\s*[A-Za-z0-9]*\s*$'
    r'|^(?:CASE|Case)\s*#?\s*[A-Za-z0-9]+\b'
    r'|\bcase\s+scenario\b'
    r'|\bscenario\s+applies\s+to\b'
    r'|\bfollowing\s+scenario\b'
    r'|\banswering\s+questions?\s+\d+\s*[-–—]\s*\d+'
    r'|\bpertain(?:s|ing)?\s+to\s+(?:case|Case)\b'
    r'|\brefer(?:s)?\s+to\s+CASE\b',
    re.I,
)
CASE_TAG_RE = re.compile(r'^\(([^)]+)\)')

def find_case_intro_split(block_lines):
    """A question's raw block sometimes has a *different* case's intro
    tacked onto its tail -- e.g. "...d. Multidisciplinary management...
    CASE CD- questions 11-16 are pertinent to Case CD\nA 55 year old
    female..." -- because nothing marks where the previous question's
    answer ends and the next case's vignette begins except prose, and
    that prose would otherwise get silently absorbed into the previous
    question's last option by parse_option_block's continuation-line
    logic. Returns the index in block_lines where a case-intro heading
    starts (see CASE_INTRO_TRIGGER_RE for the range of phrasings this
    covers), but only when real lettered options (with a checked answer)
    were already found earlier in the block -- i.e. this heading is
    trailing garbage, not part of the question's own stem. Returns None if
    no such split point exists."""
    for i, l in enumerate(block_lines):
        if CASE_INTRO_TRIGGER_RE.search(l):
            option_idxs = find_best_option_run(block_lines[:i])
            if option_idxs and any(c in ('✓', '*') for c, _ in option_idxs.values()):
                return i
    return None

def extract_case_vignette(block_lines, fallback_tag):
    """block_lines[0] is a case-intro heading line (per
    find_case_intro_split, or the text preceding question 1). Returns
    (tag, vignette_text). When the heading is a short "CASE X" / "Case #N"
    tag, that becomes the vignette's key (upper-cased, for matching
    against each question's own "(CASE X)" back-reference) and is dropped
    from the vignette text itself, since the bare tag adds nothing to show
    the student; otherwise (a longer, one-off phrasing with no clean tag
    to extract) `fallback_tag` is used as the key -- it won't match any
    real question's "(...)" back-reference, which is fine, since exams
    that phrase the intro this way don't tag their questions either and
    the vignette only needs to reach the question right after it."""
    m = CASE_TAG_HEADING_RE.match(block_lines[0])
    if m and m.group(1):
        return m.group(1).upper(), join_wrapped_lines(block_lines[1:]).strip()
    return fallback_tag, join_wrapped_lines(block_lines).strip()

def parse_questions_numbered(text):
    """Format: "N. question text" or "N) question text" ... "A. opt" / "✓B. opt"
    (no "Question #:" markers)."""
    lines = [l.strip() for l in text.split('\n')]
    lines = [l for l in lines if l != '' and not re.fullmatch(r'_{15,}', l)]
    q_start_re = re.compile(r'^(\d+)[.)]\s*(.*)$')

    all_candidates = [(i, int(m.group(1)), m.group(2))
                       for i, l in enumerate(lines)
                       for m in [q_start_re.match(l)] if m]

    if not all_candidates:
        # Third source format: no numbering markers of any kind (not even
        # plain "N."), just a stem followed directly by lettered options.
        # First seen in Lasers in Dentistry, Summer 2023.
        return parse_questions_unmarked(lines)

    # Some exams pose a question as "Which of the following are true? 1.
    # ... 2. ... 3. ..." -- a numbered *sub-list* of statements embedded in
    # the stem, before the question's real lettered options. If that
    # sub-list's own numbering happens to coincide with the real question
    # numbers coming up next (it restarts at 1, so this is only a matter of
    # timing), naively taking the first line matching each expected number
    # treats sub-list items as question boundaries: it truncates the
    # still-open question before its real options, and once a later
    # coincidental item finally closes it, the accumulated sub-list *and*
    # the real options end up glued onto the wrong question's last option.
    # First seen in TMD & Orofacial Pain, Spring 2020. Fixed by not blindly
    # taking the first line matching `expected`: when more than one line
    # matches, prefer whichever occurrence -- when used to close the
    # currently-open question -- leaves that question with exactly one
    # real, checked, lettered option run (not zero -- a genuine
    # free-response question, which by construction never has one, so it
    # still falls back to the first/only occurrence and splits off the same
    # as before, for "Questions that aren't multiple choice" to drop it;
    # and not *more* than one either -- an unbounded search for "some
    # checkmarked run exists somewhere" will eventually find one by
    # accident once the span is large enough to swallow several real
    # questions, e.g. when the currently-open question is itself a
    # legitimate non-MC matching/labeling exercise with no options of its
    # own, first seen swallowing questions 5-31 whole in Oral Surgery II,
    # Fall 2022 while chasing a coincidental "5." inside an answer key
    # ("1. G 2. A 3. F...") on question 31).
    starts = []  # (line_index, num, rest_of_line)
    expected = 1
    prev_end = 0
    search_from = 0
    while True:
        occurrences = [c for c in all_candidates if c[1] == expected and c[0] >= search_from]
        if not occurrences:
            break
        chosen = occurrences[0]
        if starts:  # question 1 has no prior open question to validate against
            for occ in occurrences:
                if _checkmarked_option_run_count(lines[prev_end:occ[0]]) == 1:
                    chosen = occ
                    break
        starts.append((chosen[0], expected, chosen[2]))
        prev_end = chosen[0] + 1
        search_from = chosen[0] + 1
        expected += 1

    if not starts:
        return parse_questions_unmarked(lines)

    # Text-only case clusters: a clinical vignette stated once (e.g. "CASE
    # AB" or "Case #1 (Questions 1-10 pertain to case #1)") before a run of
    # questions that each carry only a short "(CASE AB)" back-reference, no
    # image. Text before question 1 would otherwise be silently dropped;
    # a vignette introduced mid-exam would otherwise get absorbed into the
    # *previous* question's last option (see find_case_intro_split). See
    # README "Text-only case clusters".
    case_vignettes = {}
    pending_vignette = None
    preamble = lines[:starts[0][0]]
    for i, l in enumerate(preamble):
        if CASE_INTRO_TRIGGER_RE.search(l):
            tag, vignette = extract_case_vignette(preamble[i:], fallback_tag=f'_preamble@{i}')
            case_vignettes[tag] = vignette
            pending_vignette = vignette
            break

    questions = {}
    for si, (line_idx, num, first_line_rest) in enumerate(starts):
        end_idx = starts[si + 1][0] if si + 1 < len(starts) else len(lines)
        block_lines = ([first_line_rest] if first_line_rest else []) + lines[line_idx + 1:end_idx]

        split = find_case_intro_split(block_lines)
        next_pending = None
        if split is not None:
            tag, vignette = extract_case_vignette(block_lines[split:], fallback_tag=f'_q{num}@{split}')
            block_lines = block_lines[:split]
            case_vignettes[tag] = vignette
            next_pending = vignette

        qtext, options, correct_letter, attachment, blanks = parse_option_block(block_lines)

        lead_vignette = pending_vignette
        pending_vignette = next_pending
        tag_match = CASE_TAG_RE.match(qtext)
        if tag_match:
            for token in re.split(r'\s*[&,/]\s*', tag_match.group(1)):
                token = re.sub(r'^(?:CASE|Case)\s*#?\s*', '', token).strip().upper()
                vignette = case_vignettes.get(token)
                if vignette and vignette not in (lead_vignette or ''):
                    lead_vignette = (lead_vignette + '\n\n' + vignette) if lead_vignette else vignette
        if lead_vignette:
            qtext = lead_vignette + '\n\n' + qtext

        questions[num] = {'text': qtext, 'options': options, 'correct': correct_letter, 'attachment': attachment, 'blanks': blanks}
    return questions

def parse_questions_unmarked(lines):
    """Format: no question-numbering markers at all (no "Question #:", no
    plain "N."/"N)") -- each question is just stem text immediately followed
    by lettered options starting at 'a'/'A', one option per line (no
    line-wrapped option text in this format). Question boundaries are
    inferred purely from where a fresh 'a'/'A'-lettered option run begins.
    First seen in Lasers in Dentistry, Summer 2023 -- a "no questions parsed
    at all" result on an exam with visible lettered options (unlike the
    picture-based-options gotcha, where options are present but blank) is
    the symptom that this format has shown up again."""
    # Every one of these source exports opens with a banner line like
    # "Laser in Dentistry Final Exam - Confidential" before the first
    # question; with no numbering marker to split on the way the other two
    # formats have, that banner would otherwise get glued onto question 1's
    # stem as if it were part of the question text.
    i = 0
    while i < len(lines) and lines[i].rstrip().lower().endswith('confidential'):
        i += 1
    lines = lines[i:]

    questions = {}
    i = 0
    num = 0
    n = len(lines)
    while i < n:
        stem = []
        while i < n:
            m = OPT_RE.match(lines[i])
            if m and m.group(2).upper() == 'A':
                break
            stem.append(lines[i])
            i += 1
        if i >= n:
            break
        opt_lines = []
        prev_val = None
        while i < n:
            m = OPT_RE.match(lines[i])
            if not m:
                break
            val = m.group(2).upper()
            if prev_val is not None and val <= prev_val:
                break
            opt_lines.append(lines[i])
            prev_val = val
            i += 1
        num += 1
        qtext, options, correct_letter, attachment, blanks = parse_option_block(stem + opt_lines)
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
