#!/usr/bin/env node
// Automated replacement for "click through the app in a browser and eyeball
// it" — the manual verification step the shipping workflow requires before
// merging a batch of newly-imported (or edited) exams. See README.md
// section 4.
//
// For each exam id given, this:
//   1. Cross-checks exams.json's question count against the source CSV's
//      data-row count (catches "forgot to re-run build-exams.js").
//   2. Loads index.html in headless Chromium and drives the app's own
//      `quizState`/`view`/`render()` globals directly to jump to every
//      question of that exam (no UI clicking needed).
//   3. For each question: asserts the question text isn't empty, that the
//      rendered option count (or blank count, for FILL questions) matches
//      what's in exams.json, and — if the question has an image — that the
//      <img> actually loaded (network response, not a 404/500).
//   4. Screenshots one representative question per exam (the first one with
//      an image, else question 1) for a quick human/Claude skim.
//
// Requires the `playwright` package + its Chromium browser (both
// pre-installed in this environment). If `require('playwright')` fails
// here, re-run with:
//   NODE_PATH="$(npm root -g)" node scripts/exam_import/verify_batch.js ...
//
// Usage:
//   node scripts/exam_import/verify_batch.js <exam-id> [exam-id...]
//   node scripts/exam_import/verify_batch.js --all
//   node scripts/exam_import/verify_batch.js --out=/tmp/screens pcod2-final-spring-2024
//
// Exits non-zero if any exam fails a check.

const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');

let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (e) {
  console.error('Could not require("playwright"). Try:\n  NODE_PATH="$(npm root -g)" node ' + process.argv[1] + ' ' + process.argv.slice(2).join(' '));
  process.exit(1);
}

const REPO_ROOT = path.join(__dirname, '..', '..');
const CSV_DIR = path.join(REPO_ROOT, 'exams-csv');
const EXAMS_JSON_PATH = path.join(REPO_ROOT, 'exams.json');
const PORT = process.env.VERIFY_PORT ? parseInt(process.env.VERIFY_PORT, 10) : 8000;

// Minimal copy of build-exams.js's CSV parser, used only to count data rows
// for the "did you rebuild?" cross-check -- keep in sync with that file if
// its CSV grammar ever changes.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += c;
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter(r => r.some(f => f.trim() !== ''));
}

function parseArgs(argv) {
  let outDir = path.join(os.tmpdir(), 'exam-verify-screenshots');
  let all = false;
  const ids = [];
  for (const a of argv) {
    if (a.startsWith('--out=')) outDir = a.slice('--out='.length);
    else if (a === '--all') all = true;
    else if (!a.startsWith('--')) ids.push(a);
  }
  return { outDir, all, ids };
}

function fetchOk(url) {
  return new Promise(resolve => {
    const req = http.get(url, res => { res.resume(); resolve(res.statusCode >= 200 && res.statusCode < 300); });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });
}

async function ensureServer() {
  const url = `http://localhost:${PORT}/exams.json`;
  if (await fetchOk(url)) return { proc: null, base: `http://localhost:${PORT}` };
  const proc = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: REPO_ROOT, stdio: 'ignore' });
  for (let i = 0; i < 50; i++) {
    if (await fetchOk(url)) return { proc, base: `http://localhost:${PORT}` };
    await new Promise(r => setTimeout(r, 100));
  }
  proc.kill();
  throw new Error(`local server on port ${PORT} never came up`);
}

async function verifyExam(page, examJson, id, outDir, failedImageUrls) {
  const problems = [];
  if (!examJson[id]) {
    return { id, problems: [`not present in exams.json`] };
  }
  const csvPath = path.join(CSV_DIR, `${id}.csv`);
  if (!fs.existsSync(csvPath)) {
    problems.push(`no matching CSV at exams-csv/${id}.csv`);
  } else {
    const rows = parseCsv(fs.readFileSync(csvPath, 'utf8'));
    const csvDataRowCount = Math.max(0, rows.length - 2); // minus title + header rows
    const jsonCount = examJson[id].questions.length;
    if (csvDataRowCount !== jsonCount) {
      problems.push(`exams.json has ${jsonCount} question(s) but exams-csv/${id}.csv has ${csvDataRowCount} data row(s) -- did you run node scripts/build-exams.js?`);
    }
  }

  const questions = (examJson[id] && examJson[id].questions) || [];
  failedImageUrls.length = 0;
  await page.evaluate((examId) => {
    quizState = { examId, current: 0, answers: {}, flags: {}, crossed: {}, optionOrder: buildOptionOrder(exams[examId]) };
    view = { screen: 'quiz' };
    render();
  }, id);

  let screenshotIdx = questions.findIndex(q => q.image);
  if (screenshotIdx === -1) screenshotIdx = questions.length ? 0 : -1;

  for (let i = 0; i < questions.length; i++) {
    const q = questions[i];
    await page.evaluate((i) => { quizState.current = i; render(); }, i);
    const info = await page.evaluate(() => {
      const p = document.querySelector('.card p');
      return {
        text: p ? p.textContent.trim() : '',
        optCount: document.querySelectorAll('.quiz-option').length,
        blankCount: document.querySelectorAll('.fill-blank-input').length,
        hasImgEl: !!document.querySelector('img.question-image'),
      };
    });
    if (!info.text) problems.push(`q${i + 1}: empty question text`);
    if (q.type === 'fill') {
      if (info.blankCount !== q.blanks.length) problems.push(`q${i + 1}: rendered ${info.blankCount} blank(s), expected ${q.blanks.length}`);
    } else {
      if (info.optCount !== q.options.length) problems.push(`q${i + 1}: rendered ${info.optCount} option(s), expected ${q.options.length}`);
    }
    if (q.image && !info.hasImgEl) problems.push(`q${i + 1}: exams.json has an image but none rendered`);
    if (i === screenshotIdx) {
      fs.mkdirSync(outDir, { recursive: true });
      await page.screenshot({ path: path.join(outDir, `${id}.png`) });
    }
  }
  // let any in-flight image requests for the last question settle
  await page.waitForTimeout(200);
  for (const url of failedImageUrls) problems.push(`broken image: ${url}`);

  return { id, problems };
}

(async () => {
  const { outDir, all, ids: idArgs } = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(EXAMS_JSON_PATH)) {
    console.error('exams.json not found -- run `node scripts/build-exams.js` first.');
    process.exit(1);
  }
  const examJson = JSON.parse(fs.readFileSync(EXAMS_JSON_PATH, 'utf8'));
  const ids = all ? Object.keys(examJson) : idArgs;
  if (!ids.length) {
    console.error('Usage: node scripts/exam_import/verify_batch.js <exam-id> [exam-id...] | --all');
    process.exit(1);
  }

  const { proc: serverProc, base } = await ensureServer();
  const browser = await chromium.launch();
  let exitCode = 0;
  try {
    const page = await browser.newPage();
    const failedImageUrls = [];
    page.on('response', res => {
      const url = res.url();
      if (url.includes('/images/') && res.status() >= 400) failedImageUrls.push(`${url} -> ${res.status()}`);
    });
    await page.goto(`${base}/index.html`);
    await page.waitForFunction(() => typeof exams !== 'undefined' && Object.keys(exams).length > 0, undefined, { timeout: 15000 });

    console.log(`Checking ${ids.length} exam(s), screenshots -> ${outDir}\n`);
    const results = [];
    for (const id of ids) {
      const result = await verifyExam(page, examJson, id, outDir, failedImageUrls);
      results.push(result);
      if (result.problems.length) {
        exitCode = 1;
        console.log(`FAIL ${id}`);
        result.problems.forEach(p => console.log(`  - ${p}`));
      } else {
        console.log(`PASS ${id} (${examJson[id].questions.length} questions)`);
      }
    }
    const failCount = results.filter(r => r.problems.length).length;
    console.log(`\n${results.length - failCount}/${results.length} passed.`);
  } finally {
    await browser.close();
    if (serverProc) serverProc.kill();
  }
  process.exit(exitCode);
})().catch(e => {
  console.error(e);
  process.exit(1);
});
