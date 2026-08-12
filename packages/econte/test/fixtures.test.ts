/**
 * Golden fixture conformance test.
 *
 * Loads every file in spec/fixtures/*.json and asserts the expected
 * accept/reject verdict encoded in the filename, per
 * docs/schema-spec.md's "Fixtures" section:
 *   - `valid-*.json`          must PASS validation.
 *   - `invalid-<rule>.json`   must FAIL validation.
 *
 * This intentionally does not hand-pick a subset — every fixture file in
 * the directory is exercised.
 */

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { validateStoryboard } from "../src/index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixturesDir = path.resolve(__dirname, "../../../spec/fixtures");

const fixtureFiles = readdirSync(fixturesDir)
  .filter((name) => name.endsWith(".json"))
  .sort();

describe("spec/fixtures golden fixtures", () => {
  it("discovered at least one fixture file", () => {
    expect(fixtureFiles.length).toBeGreaterThan(0);
  });

  it("every fixture filename declares its expected verdict", () => {
    const unlabeled = fixtureFiles.filter(
      (name) => !name.startsWith("valid-") && !name.startsWith("invalid-"),
    );
    expect(unlabeled, `Fixtures with no valid-/invalid- prefix: ${unlabeled.join(", ")}`).toEqual([]);
  });

  for (const filename of fixtureFiles) {
    const expectValid = filename.startsWith("valid-");

    it(`${filename} should ${expectValid ? "VALIDATE" : "FAIL validation"}`, () => {
      const raw = readFileSync(path.join(fixturesDir, filename), "utf-8");
      const data = JSON.parse(raw);
      const result = validateStoryboard(data);

      if (expectValid && !result.ok) {
        throw new Error(
          `Expected fixture "${filename}" to be VALID, but validateStoryboard() rejected it:\n` +
            result.errors.map((message) => `  - ${message}`).join("\n"),
        );
      }

      if (!expectValid && result.ok) {
        throw new Error(
          `Expected fixture "${filename}" to be INVALID, but validateStoryboard() accepted it.`,
        );
      }

      expect(result.ok).toBe(expectValid);
    });
  }
});
