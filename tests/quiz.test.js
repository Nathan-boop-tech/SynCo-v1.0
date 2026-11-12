"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { QUESTIONS, scoreAnswers } = require("../quiz");

test("scores correct answers without depending on letter case", () => {
  const answers = QUESTIONS.map((question) => question.answer.toLowerCase());

  assert.deepEqual(scoreAnswers(answers), {
    score: QUESTIONS.length,
    total: QUESTIONS.length,
  });
});

test("counts incorrect and missing answers as incorrect", () => {
  assert.deepEqual(scoreAnswers(["A", "D"]), {
    score: 0,
    total: QUESTIONS.length,
  });
});

test("scores a partial result correctly", () => {
  assert.deepEqual(scoreAnswers(["B", "A", "A"]), {
    score: 2,
    total: QUESTIONS.length,
  });
});
