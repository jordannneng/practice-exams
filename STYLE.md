# TCDM Practice Exams: Style Guide

This is the visual and interaction spec for the practice exam site. Hand it to
whoever (or whatever) is building a new exam page and the result should look
and behave like the existing site. Everything here is pulled straight from
`index.html`. Where the spec and your instincts disagree, follow the spec.

The quiz screen matters most. A student moving between the main site and a
new artifact should not notice a difference while taking an exam.

---

## 1. The overall feel

Flat, quiet, clinical. Light gray page, white cards with thin blue-gray
borders, big soft 16px corners, one dark navy accent. No gradients, no
illustrations, no emoji in UI chrome (the flag glyph ⚑ is the one exception).
Color only shows up to mean something: navy for "selected / primary", green
for correct, red for wrong, amber for flagged.

Light theme only. There is no dark mode on the site, so don't add one unless
you're asked.

---

## 2. Design tokens

Copy this block verbatim. Every color in the UI comes from these variables.

```css
:root {
  --bg: #ebebeb;            /* page background */
  --card: #ffffff;          /* cards, buttons, inputs */
  --border: #cdd5df;        /* default card border, dividers */
  --border-strong: #b7c1ce; /* button/option/input borders, hover borders */
  --text: #21314d;          /* body text (same navy as the accent) */
  --text-secondary: #57657a;/* subtitles, "Question X of Y", labels */
  --text-muted: #8a95a6;    /* meta lines, hints, semester headings */
  --accent: #21314d;        /* navy: primary buttons, selection, focus */
  --accent-light: #f1f1f1;  /* selected option fill, hover fill */
  --accent-dark: #2c3f61;   /* primary button hover */
  --success: #1e6b3e;       /* correct border/text */
  --success-light: #e6f3ea; /* correct fill */
  --danger: #a3282d;        /* incorrect border/text, issue badge */
  --danger-light: #fbe9ea;  /* incorrect fill */
  --flag: #b9791a;          /* flagged question (amber) */
  --radius: 16px;           /* used on almost everything */
}
```

A few things worth knowing about the palette:

- Text and accent are the same navy (`#21314d`). That's deliberate. The site
  reads as one color plus grays.
- `--accent-light` is a neutral light gray, not a tinted blue. Selected
  options are signalled by the navy border, the fill is just a hint.
- Shadows are always navy-tinted, never pure black:
  - hover lift on cards: `0 6px 16px rgba(33, 49, 77, 0.12)`
  - floating menus/popovers: `0 8px 24px rgba(20, 30, 45, 0.15)`

---

## 3. Typography

```css
body {
  font-family: Helvetica, Arial, "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif;
  line-height: 1.5;
  color: var(--text);
}
```

Plain Helvetica stack, nothing fancy. The site's `<head>` also loads Oswald 600
from Google Fonts, but nothing actually uses it right now. Skip it unless you
have a reason.

Type scale (all px, there is no rem system):

| Use | Size | Weight | Color |
|---|---|---|---|
| Score on results screen | 40 | 600 | `--text` |
| Page heading `h1` | 22 | 600 | `--text` |
| Question stem | 16 | 500 | `--text` |
| Card title (category / exam name) | 16 | 600 | `--text` |
| Body, buttons, answer options, inputs | 14 | 500 for buttons, 400 otherwise | `--text` |
| Subtitle under `h1` | 14 | 400 | `--text-secondary` |
| "Question X of Y", back link, toggle labels | 13 | 400/500 | `--text-secondary` |
| Meta lines ("12 questions · Best: 80%") | 13 | 400 | `--text-muted` |
| Semester heading | 13 | 700, UPPERCASE, `letter-spacing: 0.04em` | `--text-muted` |
| Small button | 13 | 500 | |
| Fill-blank "Accepted answer" hint | 12 | 400 | `--text-muted` |
| Footer text | 12.5 | 400 | `--text-muted` |

Buttons and inputs set `font-family: inherit` so they don't fall back to the
browser's system font.

---

## 4. Layout and spacing

- Page container `.app`: `max-width: 760px; margin: 0 auto; padding: 24px;`
- Browsing screens (home, category, exam list) widen to `960px` via `.app.wide`.
  **The quiz and results screens use the narrow 760px column.**
- Cards: `padding: 20px; margin-bottom: 16px; border: 1px solid var(--border); border-radius: 16px; background: #fff;`
- Grids: `display: grid; gap: 12px;` with `repeat(auto-fill, minmax(230px, 1fr))`
  for category cards and `minmax(260px, 1fr)` for exam cards.
- Top row (back link or quiz toolbar): flex, space-between, `margin-bottom: 16px`
  (24px on the quiz screen).
- Footer row (Previous / Next): flex, space-between, `margin-top: 20px`,
  right-hand group uses `gap: 12px`.
- Answer options stack with `margin-bottom: 8px` between them.
- `h1` has `margin: 0 0 4px`, subtitle below it has `margin: 0 0 24px`.

Common spacing values: 4, 6, 8, 10, 12, 14, 16, 20, 24, 28. Stick to these.

Global resets:

```css
* { box-sizing: border-box; }
html { touch-action: manipulation; }
body { margin: 0; background: var(--bg); -webkit-tap-highlight-color: transparent; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

---

## 5. Components

### Buttons

```css
button {
  font-family: inherit; font-size: 14px; font-weight: 500; padding: 8px 14px;
  border-radius: var(--radius); border: 1px solid var(--border-strong); background: var(--card);
  color: var(--text); cursor: pointer;
  touch-action: manipulation; -webkit-user-select: none; user-select: none;
}
button.primaryDark  { background: var(--accent); color: white; border-color: var(--accent); }
button.primaryLight { background: var(--card); color: var(--accent); border-color: var(--border); }
button.small { padding: 5px 10px; font-size: 13px; }
button:disabled { opacity: 0.5; cursor: default; }
```

Rule of thumb: the forward action (Next, Submit exam, Take exam, Retake exam)
is `primaryDark`. Backward or secondary (Previous, Start over) is
`primaryLight`. Disabled buttons stay visible at half opacity, they don't
disappear.

**Back link** (top of non-quiz screens): text-only, no border, no background,
13px/500 in `--text-secondary`, label starts with an arrow: `← Back to exams`.

```css
.back-btn { background: none; border: none; padding: 4px 0; margin: 0;
  color: var(--text-secondary); font-size: 13px; font-weight: 500; }
```

**Bare icon button** (hamburger menu, flag): 38×38, no border, no background,
26px glyph, `--text` color, 16px radius on hover.

### Cards

Plain `.card` is described above. Clickable cards (category and exam cards)
add a hover lift:

```css
transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
/* on hover */
border-color: var(--border-strong);
box-shadow: 0 6px 16px rgba(33, 49, 77, 0.12);
transform: translateY(-1px);
```

Exam card internals: column flex with `gap: 14px`, padding `16px 18px`. Title
(16/600) over a meta line (13px muted), then a right-aligned action row
(`gap: 10px`) with the primary button.

### Toggle switch

Used for "Grade immediately", "Auto next", and similar boolean settings.

```css
.toggle-switch { position: relative; width: 34px; height: 20px; border-radius: 10px;
  background: var(--border-strong); flex-shrink: 0; transition: background 0.15s; }
.toggle-switch.on { background: var(--accent); }
.toggle-switch::after { content: ''; position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: left 0.15s; }
.toggle-switch.on::after { left: 16px; }
```

The label text goes to the left of the switch, 13px `--text-secondary`,
`gap: 8px`, and the whole label is the click target.

### Dropdown menu (quiz options)

Anchored under the hamburger, `top: calc(100% + 6px); left: 0;`,
`min-width: 230px`, white, `1px solid var(--border)`, 16px radius, the
floating shadow, `padding: 8px`. Items are 14px, `padding: 9px 10px`,
`border-radius: 6px`, hover fill `--accent-light`. A divider is a 1px
`--border` line with `margin: 6px 2px`. A transparent fixed overlay
(`inset: 0; z-index: 20`) behind it closes the menu on outside click; the
menu itself is `z-index: 30`.

### Skeleton loading

Gray blocks in `--border` color with the 16px radius, pulsing opacity
1 → 0.5 → 1 over 1.4s ease-in-out.

---

## 6. The quiz screen (match this exactly)

### Structure, top to bottom

```
┌───────────────────────────────────────────────────────────────┐
│ [☰]                                    [⚑]  Question 3 of 40 │  toolbar
├───────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ Which nerve supplies the ...?          (16px / 500)       │ │  question card
│ │ [optional figure, full width]                             │ │
│ │ ┌───────────────────────────────────────────────────────┐ │ │
│ │ │ ○ Inferior alveolar                               👁   │ │ │  option rows
│ │ └───────────────────────────────────────────────────────┘ │ │
│ │ ┌───────────────────────────────────────────────────────┐ │ │
│ │ │ ○ Lingual                                         👁   │ │ │
│ │ └───────────────────────────────────────────────────────┘ │ │
│ └───────────────────────────────────────────────────────────┘ │
│ [Previous]                         Auto next [◯━]   [Next]   │  footer row
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ (1)(2)(3)(4)(5)(6)(7)(8)(9)(10)(11) ...  → scrolls        │ │  question nav
│ └───────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

Reference markup (trimmed from `renderQuiz`):

```html
<div class="top-row quiz-top-row">
  <div class="options-wrap">
    <button class="bare-icon" title="Options"><!-- 26px hamburger SVG --></button>
  </div>
  <div style="display:flex; align-items:center; gap:12px;">
    <button class="bare-icon flag-btn" title="Flag question">⚑</button>
    <span style="font-size:13px; color: var(--text-secondary);">Question 3 of 40</span>
  </div>
</div>

<div class="card">
  <p style="font-size:16px; font-weight:500; margin-top:0;">Question stem…</p>
  <img class="question-image" src="…" alt="Figure for this question">
  <label class="quiz-option" data-oi="0">
    <span class="option-main">
      <input type="radio" name="quiz-answer"> Option text
    </span>
    <button type="button" class="eye-toggle" title="Hide option"><!-- eye SVG --></button>
  </label>
  <!-- more options -->
</div>

<div class="footer-row">
  <button class="primaryLight">Previous</button>
  <div class="footer-row-right">
    <label class="auto-next-toggle"><span>Auto next</span><span class="toggle-switch"></span></label>
    <button class="primaryDark">Next</button>   <!-- "Submit exam" on the last question -->
  </div>
</div>

<div class="card qnav-wrap"><div class="qnav"><!-- .qnav-btn × N --></div></div>
```

### Answer options

```css
.quiz-option {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 12px 14px; border: 1px solid var(--border-strong); border-radius: var(--radius);
  margin-bottom: 8px; cursor: pointer; font-size: 14px;
  touch-action: manipulation; -webkit-user-select: none; user-select: none; -webkit-touch-callout: none;
}
.quiz-option.selected { border-color: var(--accent); background: var(--accent-light); }
.quiz-option.locked { cursor: default; }
.option-main { display: flex; align-items: center; flex: 1; min-width: 0; }
.quiz-option input { margin-right: 10px; flex-shrink: 0; accent-color: var(--accent); }
.quiz-option.correct-answer   { border-color: var(--success); background: var(--success-light); }
.quiz-option.incorrect-answer { border-color: var(--danger);  background: var(--danger-light); }
.quiz-option.crossed-out { cursor: default; border-color: var(--border); }
.quiz-option.crossed-out .option-main { text-decoration: line-through; color: var(--text-muted); opacity: 0.7; }
/* hover, pointer devices only */
.quiz-option:not(.locked, .crossed-out):hover { background: var(--accent-light); }
```

Things that matter here:

- The whole row is a `<label>`, so clicking anywhere on it picks the answer.
  The native radio is visible and tinted navy with `accent-color`.
- **No A/B/C/D letters.** Options are shown as plain text with a radio. That's
  also why option order gets shuffled (see section 7).
- Each row has an eye toggle on the right (30×30, no border, navy icon,
  turns `--text-muted` when active) that crosses the option out. A
  crossed-out option gets a strikethrough, fades to 70%, and can't be
  selected. Clicking the eye again restores it. The eye icons are 16px
  Feather-style stroke SVGs (`stroke-width="2"`, round caps/joins):
  eye open and eye with a slash.
- Once graded, rows get `.locked`, the eye toggles go away on the review
  screen, and only two rows light up: the correct one green, and the student's
  pick red if it was wrong. Every other row stays plain.

### Fill-in-the-blank questions

Same card, but instead of options, one row per blank:

```css
.fill-blank-row { margin-bottom: 12px; }
.fill-blank-label { font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; display: block; }
.fill-blank-input {
  width: 100%; padding: 10px 12px; border: 1px solid var(--border-strong); border-radius: var(--radius);
  font-size: 14px; font-family: inherit; color: var(--text); background: var(--card);
}
.fill-blank-input:focus { outline: none; border-color: var(--accent); }
.fill-blank-input.correct-answer   { border-color: var(--success); background: var(--success-light); }
.fill-blank-input.incorrect-answer { border-color: var(--danger);  background: var(--danger-light); }
.fill-blank-accepted { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
```

Label reads "Your answer" for a single blank, "Answer 1", "Answer 2"… for
several. Inputs have `autocomplete="off" spellcheck="false"`. When a blank is
wrong, show `Accepted answer: <first accepted value>` under it. Matching is
trimmed and case-insensitive against a list of accepted alternatives.

### Figures

```css
.question-image { display: block; max-width: 100%; height: auto; margin: 4px 0 16px; }
```

Sits between the stem and the options. No border, no caption, no zoom.
`alt="Figure for this question"`.

### Question navigator

A horizontally scrolling row of numbered circles inside its own card under the
footer row (`margin-top: 20px`).

```css
.qnav { display: flex; align-items: center; gap: 10px;
  overflow-x: auto; overflow-y: hidden; padding: 2px 2px 8px;
  scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
.qnav::-webkit-scrollbar { height: 6px; }
.qnav::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
.qnav-btn { position: relative; flex-shrink: 0; width: 38px; height: 38px; border-radius: 50%;
  padding: 0; font-size: 13px; border: 1px solid var(--border-strong); background: var(--card); color: var(--text); }
.qnav-btn.current   { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); font-weight: 600; }
.qnav-btn.correct   { background: var(--success-light); border-color: var(--success); color: var(--success); }
.qnav-btn.incorrect { background: var(--danger-light);  border-color: var(--danger);  color: var(--danger); }
.qnav-btn.answered  { background: var(--accent-light);  border-color: var(--accent);  color: var(--accent); }
.qnav-btn.flagged::after { content: ''; position: absolute; top: -4px; right: -4px; width: 10px; height: 10px;
  border-radius: 50%; background: var(--flag); border: 1px solid var(--card); }
```

States stack: a circle can be current + correct + flagged at once. "Current"
is a double-weight navy ring. Flagged is a small amber dot on the top-right
corner. When immediate grading is on, answered circles go green/red; when
it's off they go neutral `.answered` until submission. After every render,
scroll the current circle into view, centered
(`scrollIntoView({ block: 'nearest', inline: 'center' })`).

### Flag

The ⚑ glyph in a bare icon button, `--text` normally, `--flag` amber when the
question is flagged. On the review screen a flagged question shows
`⚑ Flagged` in 13px amber at the top-right of the question card.

---

## 7. Quiz behavior (part of the look and feel)

- **Grade immediately** (default on, toggle in the ☰ menu). With it on,
  picking an option instantly shows green/red and locks the question. With it
  off, the pick stays navy-selected and can be changed until submit.
- **Auto next** (default off, toggle in the footer). After picking an option,
  wait 600ms then advance. Never auto-advances off the last question.
- **Fill-in grading** happens on Enter (when immediate grading is on) or when
  the student navigates away. Don't re-render on every keystroke or blur, it
  eats focus between blanks.
- The last question swaps **Next** for **Submit exam**. Previous is disabled
  on question 1.
- **Option shuffling**: each attempt shuffles answer order, except:
  - "All of the above" / "None of the above" style options stay in their
    original slot.
  - Questions with options like "A and C" or "Both B and D" don't shuffle at
    all (unless the stem itself defines those letters).
  - Questions where every option is a true/false verdict don't shuffle.
- ☰ menu contains: Grade immediately (toggle), divider, Reset exam, Exit exam.
  Reset uses a native `confirm()`.
- Settings (grading, auto next) persist across exams in `localStorage`, and
  so does in-progress state so a student can leave and resume. Wrap storage
  access in try/catch.

---

## 8. Results screen

Narrow 760px column.

1. Back link: `← Back to exams`
2. A card with the score: `40px / 600` percentage centered
   (`margin: 10px 0`), then `N of M correct` in 14px `--text-secondary`
   centered (`margin-bottom: 20px`), then a centered `primaryDark`
   **Retake exam** button.
3. A review card for the current question: small header row with
   "Question X of Y" left and "⚑ Flagged" right if flagged, then the stem,
   figure, and options in their locked, graded state (no eye toggles).
4. Footer row: Previous (`primaryLight`) and Next (`primaryDark`), disabled
   at the ends.
5. The question navigator card, always in graded green/red mode.

Score is `Math.round(correct / total * 100)`.

---

## 9. Browsing screens (lower priority, for completeness)

- Home groups categories under semester headings: 13px, bold, uppercase,
  `letter-spacing: 0.04em`, `--text-muted`, 1px `--border` underline,
  `margin: 28px 0 10px` (first one has no top margin).
- Category cards: title 16/600 over "N exams" in 13px muted.
- Exam list: `h1` with category name, subtitle "Pick an exam below to start
  practicing.", optional "Random Practice Exam" card, then the exam grid.
  Exam meta reads `40 questions · Best: 85% · Last: 70%` or
  `Not attempted yet`, or `In progress, question 12 of 40` with a
  **Resume exam** + **Start over** pair.
- Known-issue badge: 24px circle with "!", muted by default, red on hover or
  when open. Its popover is 260px wide with a red 1px border and the floating
  shadow.
- Empty and error states: centered text, `padding: 40px 20px`,
  `--text-secondary` / `--text-muted`.

---

## 10. Hover and touch rules

All hover styles live inside
`@media (hover: hover) and (pointer: fine) { … }` so phones never get stuck
hover states after a tap. The hover set:

```css
button.primaryLight:hover { background: var(--accent-light); border-color: var(--border-strong); }
button.primaryDark:hover  { background: var(--accent-dark); }
.category-card:hover, .exam-card:hover { /* lift, see Cards */ }
.quiz-option:not(.locked, .crossed-out):hover { background: var(--accent-light); }
.bare-icon:hover { background: var(--bg); }
.options-menu-item:hover { background: var(--accent-light); }
.back-btn:hover { background: none; color: var(--accent); }
```

Interactive elements also get `touch-action: manipulation` (kills double-tap
zoom delay) and `user-select: none` so fast tapping on options doesn't
highlight text.

---

## 11. Quick checklist for a new artifact

- [ ] Token block from section 2 pasted in, no new colors invented
- [ ] Helvetica stack, 1.5 line height, sizes from the type table
- [ ] Everything rounded at 16px (except menu items at 6px, circles at 50%)
- [ ] Quiz column is 760px max with 24px padding
- [ ] Options are full-width bordered rows with a navy radio and an eye
      toggle, no letters
- [ ] Green/red feedback only on the correct pick and the wrong pick
- [ ] Toolbar: ☰ left, ⚑ + "Question X of Y" right
- [ ] Footer: Previous left, Auto next toggle + Next/Submit right
- [ ] Numbered circle navigator in its own card at the bottom, amber dot for
      flags
- [ ] Hover styles gated behind `(hover: hover) and (pointer: fine)`
- [ ] Works at phone width with no horizontal page scroll (only the
      navigator scrolls sideways)
