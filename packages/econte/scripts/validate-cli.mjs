#!/usr/bin/env node
// Minimal CLI wrapper around validateStoryboard(), for use by anything that
// needs to invoke the TypeScript/Zod validator out-of-process (e.g.
// scripts/cross_check_goldens.py at the repo root, which shells out to this
// script rather than reimplementing the schema in a second language).
//
// Usage: node scripts/validate-cli.mjs <path-to-storyboard.json>
// Exit code 0 + "OK" on stdout  => valid.
// Exit code 1 + error lines on stderr => invalid (or unreadable/bad JSON).

import { readFileSync } from "node:fs";
import { validateStoryboard } from "../dist/index.js";

const path = process.argv[2];

if (!path) {
  console.error("usage: node scripts/validate-cli.mjs <path-to-storyboard.json>");
  process.exit(2);
}

let data;
try {
  const raw = readFileSync(path, "utf-8");
  data = JSON.parse(raw);
} catch (err) {
  console.error(`error: could not read/parse ${path}: ${err.message}`);
  process.exit(1);
}

const result = validateStoryboard(data);

if (result.ok) {
  console.log("OK");
  process.exit(0);
} else {
  for (const error of result.errors) {
    console.error(error);
  }
  process.exit(1);
}
