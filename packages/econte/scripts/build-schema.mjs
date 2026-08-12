#!/usr/bin/env node
// Generates spec/econte.schema.json (JSON Schema draft 2020-12) from the
// compiled Zod schema (dist/schema.js, built by `tsc` — this script is run
// via `npm run build:schema`, which runs `npm run build` first).
//
// NOTE: zod-to-json-schema can only express per-field constraints (types,
// formats, ranges, enums). The document-level cross-field validation rules
// described in docs/schema-spec.md — character/scene id uniqueness, GLOBAL
// shot id uniqueness across all scenes, Shot.subject referential integrity
// against declared characters, Shot.frames end > start, Lyric.endMs >
// Lyric.startMs — are NOT representable in JSON Schema and are therefore
// absent from the generated file below. Those rules are enforced by the
// reference implementations instead:
//   - packages/econte  (TypeScript / Zod: .refine() / .superRefine())
//   - python/econte     (Python / pydantic: model_validator)
// A document can pass structural validation against econte.schema.json
// alone and still be rejected by `validateStoryboard()` / `econte validate`.

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { zodToJsonSchema } from "zod-to-json-schema";
import { StoryboardSchema } from "../dist/schema.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outPath = path.resolve(__dirname, "../../../spec/econte.schema.json");

const jsonSchema = zodToJsonSchema(StoryboardSchema, {
  name: "Storyboard",
  $refStrategy: "none",
  definitionPath: "$defs", // "$defs" is the 2020-12-idiomatic name (vs. legacy "definitions")
});

// zod-to-json-schema targets JSON Schema draft 7 / 2019-09 style output by
// default; the emitted keywords are a compatible subset of 2020-12, so we
// simply declare the dialect and identity explicitly here rather than rely
// on a "target" option string.
const orderedSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "https://github.com/igashira0324/econte/spec/econte.schema.json",
  title: "econte storyboard schema",
  description:
    "Structural (per-field) JSON Schema for the econte storyboard format, generated from packages/econte (Zod). " +
    "Cross-field rules (id uniqueness, referential integrity, frames/lyric ordering — see docs/schema-spec.md) " +
    "are enforced by the reference implementations (packages/econte, python/econte), not by this file alone.",
  ...jsonSchema,
};
// zodToJsonSchema puts its own "$schema" first; overwrite with ours.
orderedSchema.$schema = "https://json-schema.org/draft/2020-12/schema";

writeFileSync(outPath, JSON.stringify(orderedSchema, null, 2) + "\n", "utf-8");
console.log(`Wrote ${outPath}`);
