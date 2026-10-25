/**
 * @econte/schema — Zod schema and validator for the econte storyboard
 * format. See docs/schema-spec.md at the repository root for the
 * authoritative field-by-field specification this package implements.
 */

export * from "./schema.js";

import { ARRAY_LIMITS, StoryboardSchema, type Storyboard } from "./schema.js";

export type ValidateStoryboardResult =
  | { ok: true; value: Storyboard }
  | { ok: false; errors: string[] };

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/**
 * Check the upper bounds from docs/schema-spec.md rule 7 (`ARRAY_LIMITS`) on
 * the raw value, before zod sees it. zod 3 keeps validating every element of
 * an array after that array's `.max()` check has failed
 * (GHSA-mrhx-c7xc-m3w5), so without this an oversized array in an untrusted
 * document still costs one issue, and its memory, per element.
 */
function findOversizedArrays(data: unknown): string[] {
  const errors: string[] = [];
  const exceeds = (value: unknown, limit: number, path: string): boolean => {
    if (!Array.isArray(value) || value.length <= limit) return false;
    errors.push(`${path}: must have at most ${limit} entries (got ${value.length})`);
    return true;
  };

  const doc = asRecord(data);
  if (doc === undefined) return errors;

  exceeds(asRecord(doc.metadata)?.aspectRatios, ARRAY_LIMITS.aspectRatios, "metadata.aspectRatios");
  const style = asRecord(doc.globalStyle);
  exceeds(style?.palette, ARRAY_LIMITS.palette, "globalStyle.palette");
  exceeds(style?.negative, ARRAY_LIMITS.negative, "globalStyle.negative");

  const characters = doc.characters;
  if (Array.isArray(characters) && !exceeds(characters, ARRAY_LIMITS.characters, "characters")) {
    characters.forEach((character: unknown, index) => {
      exceeds(asRecord(character)?.refs, ARRAY_LIMITS.refs, `characters.${index}.refs`);
    });
  }

  const scenes = doc.scenes;
  if (Array.isArray(scenes) && !exceeds(scenes, ARRAY_LIMITS.scenes, "scenes")) {
    let totalShots = 0;
    scenes.forEach((scene: unknown, index) => {
      const shots = asRecord(scene)?.shots;
      if (Array.isArray(shots)) {
        totalShots += shots.length;
        exceeds(shots, ARRAY_LIMITS.shotsPerScene, `scenes.${index}.shots`);
      }
    });
    if (totalShots > ARRAY_LIMITS.totalShots) {
      errors.push(`scenes: at most ${ARRAY_LIMITS.totalShots} shots in total (got ${totalShots})`);
    }
  }

  return errors;
}

/**
 * Validate an arbitrary value against the Storyboard schema.
 *
 * Never throws — wraps `StoryboardSchema.safeParse` and flattens any Zod
 * issues into readable `"path: message"` strings (e.g.
 * `"scenes.0.shots.1.frames.1: Shot.frames[1] (end) must be greater than
 * Shot.frames[0] (start)"`). A root-level issue (empty path) is reported as
 * `"(root): message"`.
 *
 * Arrays above the documented bounds are rejected before zod parses anything
 * (see `findOversizedArrays`), so use this function rather than
 * `StoryboardSchema.safeParse` for untrusted input.
 */
export function validateStoryboard(data: unknown): ValidateStoryboardResult {
  const oversized = findOversizedArrays(data);
  if (oversized.length > 0) {
    return { ok: false, errors: oversized };
  }

  const result = StoryboardSchema.safeParse(data);

  if (result.success) {
    return { ok: true, value: result.data };
  }

  const errors = result.error.issues.map((issue) => {
    const path = issue.path.length > 0 ? issue.path.join(".") : "(root)";
    return `${path}: ${issue.message}`;
  });

  return { ok: false, errors };
}
