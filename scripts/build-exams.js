#!/usr/bin/env node
// Converts exams-csv/*.csv into exams.json.
// Each CSV: row 1 = "title,<Exam Title>,<type>", row 2 = column header, remaining rows = data.
// <type> must be one of KNOWN_TYPES below — add a new category there before using it in a CSV.
// Header must include "question", "correct", and two or more "option_*" columns
// (e.g. question,option_a,option_b,option_c,option_d,option_e,correct) — a single
// header can mix row lengths, so true/false rows just leave the unused option
// columns blank and five-way rows use all of them. "correct" is a letter (A, B, C, ...)
// matching the answer's position among that row's non-blank options. An optional
// "image" column gives a path (relative to the site root, e.g. images/<exam>/fig1.jpg)
// to a figure shown with that question; leave it blank for questions with no figure.
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

const KNOWN_TYPES = ['gda', 'testing'];

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

function letterToIndex(letter, optionCount, filePath, rowNum) {
  const idx = LETTERS.indexOf(letter.trim().toUpperCase());
  if (idx === -1 || idx >= optionCount) {
    throw new Error(`${filePath} row ${rowNum}: "correct" value "${letter}" is not valid for ${optionCount} option(s)`);
  }
  return idx;
}

function csvFileToExam(filePath) {
  const rows = parseCsv(fs.readFileSync(filePath, 'utf8'));
  const [titleRow, headerRow, ...dataRows] = rows;
  if (!titleRow || titleRow[0].trim().toLowerCase() !== 'title') {
    throw new Error(`${filePath}: first row must be "title,<Exam Title>,<type>"`);
  }
  const title = titleRow[1];
  const type = (titleRow[2] || '').trim().toLowerCase();
  if (!KNOWN_TYPES.includes(type)) {
    throw new Error(`${filePath}: type "${type}" must be one of ${KNOWN_TYPES.join(', ')}`);
  }
  if (!headerRow) throw new Error(`${filePath}: missing header row`);
  const header = headerRow.map(h => h.trim().toLowerCase());
  const questionCol = header.indexOf('question');
  const correctCol = header.indexOf('correct');
  const imageCol = header.indexOf('image');
  const optionCols = header.reduce((cols, h, i) => (h.startsWith('option') ? [...cols, i] : cols), []);
  if (questionCol === -1 || correctCol === -1 || optionCols.length < 2) {
    throw new Error(`${filePath}: header row must include "question", two or more "option_*" columns, and "correct"`);
  }
  const questions = dataRows.map((r, i) => {
    const rowNum = i + 3; // 1-indexed, after the title and header rows
    const options = optionCols.map(c => (r[c] || '').trim()).filter(v => v !== '');
    if (options.length < 2) throw new Error(`${filePath} row ${rowNum}: needs at least 2 non-blank options`);
    const image = imageCol !== -1 ? (r[imageCol] || '').trim() : '';
    return {
      text: r[questionCol],
      options,
      correct: letterToIndex(r[correctCol] || '', options.length, filePath, rowNum),
      ...(image ? { image } : {}),
    };
  });
  return { title, type, questions };
}

function formatExamsJson(exams) {
  const examEntries = Object.keys(exams).map(id => {
    const e = exams[id];
    const questionEntries = e.questions.map(q => {
      const optionsStr = q.options.map(o => JSON.stringify(o)).join(', ');
      const imageLine = q.image ? `,\n        "image": ${JSON.stringify(q.image)}` : '';
      return `      {
        "text": ${JSON.stringify(q.text)},
        "options": [${optionsStr}],
        "correct": ${q.correct}${imageLine}
      }`;
    }).join(',\n');
    return `  ${JSON.stringify(id)}: {
    "title": ${JSON.stringify(e.title)},
    "type": ${JSON.stringify(e.type)},
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
