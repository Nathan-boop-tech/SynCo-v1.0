#!/usr/bin/env node
"use strict";

const readline = require("node:readline");
const { stdin, stdout } = require("node:process");

const QUESTIONS = [
  {
    prompt: "Which keyword declares a block-scoped variable in JavaScript?",
    choices: [
      { label: "A", text: "var" },
      { label: "B", text: "let" },
      { label: "C", text: "define" },
      { label: "D", text: "dim" },
    ],
    answer: "B",
  },
  {
    prompt: "Which array method creates a new array by transforming each item?",
    choices: [
      { label: "A", text: "map()" },
      { label: "B", text: "push()" },
      { label: "C", text: "pop()" },
      { label: "D", text: "join()" },
    ],
    answer: "A",
  },
  {
    prompt: "What does JSON.parse() do?",
    choices: [
      { label: "A", text: "Turns an object into a JSON string" },
      { label: "B", text: "Checks whether a variable exists" },
      { label: "C", text: "Turns a JSON string into a JavaScript value" },
      { label: "D", text: "Sorts a JSON array" },
    ],
    answer: "C",
  },
];

function scoreAnswers(answers, questions = QUESTIONS) {
  const score = questions.reduce((total, question, index) => {
    const answer = String(answers[index] ?? "").trim().toUpperCase();
    return total + (answer === question.answer ? 1 : 0);
  }, 0);

  return { score, total: questions.length };
}

function formatQuestion(question, index) {
  const options = question.choices
    .map(({ label, text }) => `  ${label}) ${text}`)
    .join("\n");
  return `\nQuestion ${index + 1}: ${question.prompt}\n${options}\nYour answer (A-D): `;
}

async function runQuiz({ input = stdin, output = stdout } = {}) {
  const terminal = readline.createInterface({ input, output });
  const inputLines = terminal[Symbol.asyncIterator]();
  const answers = [];

  output.write("JavaScript Quiz\nAnswer each question with A, B, C, or D.\n");
  try {
    for (let index = 0; index < QUESTIONS.length; index += 1) {
      const question = QUESTIONS[index];
      let answer;
      do {
        output.write(formatQuestion(question, index));
        const nextLine = await inputLines.next();
        if (nextLine.done) {
          throw new Error("Input closed before the quiz was finished.");
        }
        answer = nextLine.value.trim().toUpperCase();
        if (!question.choices.some((choice) => choice.label === answer)) {
          output.write("Please enter A, B, C, or D.\n");
        }
      } while (!question.choices.some((choice) => choice.label === answer));

      answers.push(answer);
      output.write(
        answer === question.answer ? "Correct!\n" : `Not quite. The answer is ${question.answer}.\n`,
      );
    }

    const result = scoreAnswers(answers);
    output.write(`\nFinal score: ${result.score}/${result.total}\n`);
    return result;
  } finally {
    terminal.close();
  }
}

if (require.main === module) {
  runQuiz().catch((error) => {
    console.error(`Quiz ended unexpectedly: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { QUESTIONS, scoreAnswers, runQuiz };
