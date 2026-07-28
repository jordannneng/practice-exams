#!/usr/bin/env node
// Converts exams-csv/*.csv into exams.json.
// Each CSV: row 1 = "title,<Exam Title>", row 2 = column header,
// remaining rows = question,option_a,option_b,option_c,option_d,correct(A-D).
// Run: node scripts/build-exams.js

const fs = require('fs');
const path = require('path');

const CSV_DIR = path.join(__dirname, '..', 'exams-csv');
const OUTPUT_PATH = path.join(__dirname, '..', 'exams.json');

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

function letterToIndex(letter) {
  const idx = 'ABCD'.indexOf(letter.trim().toUpperCase());
  if (idx === -1) throw new Error(`Invalid "correct" value: "${letter}" (expected A, B, C, or D)`);
  return idx;
}

function csvFileToExam(filePath) {
  const rows = parseCsv(fs.readFileSync(filePath, 'utf8'));
  const [titleRow, , ...dataRows] = rows;
  if (!titleRow || titleRow[0].trim().toLowerCase() !== 'title') {
    throw new Error(`${filePath}: first row must be "title,<Exam Title>"`);
  }
  const title = titleRow[1];
  const questions = dataRows.map(r => ({
    text: r[0],
    options: [r[1], r[2], r[3], r[4]],
    correct: letterToIndex(r[5]),
  }));
  return { title, questions };
}

function formatExamsJson(exams) {
  const examEntries = Object.keys(exams).map(id => {
    const e = exams[id];
    const questionEntries = e.questions.map(q => {
      const optionsStr = q.options.map(o => JSON.stringify(o)).join(', ');
      return `      {
        "text": ${JSON.stringify(q.text)},
        "options": [${optionsStr}],
        "correct": ${q.correct}
      }`;
    }).join(',\n');
    return `  ${JSON.stringify(id)}: {
    "title": ${JSON.stringify(e.title)},
    "questions": [
${questionEntries}
    ]
  }`;
  }).join(',\n');
  return `{\n${examEntries}\n}\n`;
}

const files = fs.readdirSync(CSV_DIR).filter(f => f.endsWith('.csv')).sort();
const exams = {};
for (const file of files) {
  const id = file.replace(/\.csv$/, '');
  exams[id] = csvFileToExam(path.join(CSV_DIR, file));
}

fs.writeFileSync(OUTPUT_PATH, formatExamsJson(exams));
console.log(`Wrote ${OUTPUT_PATH} from ${files.length} CSV file(s): ${files.join(', ')}`);
