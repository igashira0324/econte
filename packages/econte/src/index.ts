/**
 * @econte/schema — Zod schema and validator for the econte storyboard
 * format. See docs/schema-spec.md at the repository root for the
 * authoritative field-by-field specification this package implements.
 */

export * from "./schema.js";

import { StoryboardSchema, type Storyboard } from "./schema.js";

export type ValidateStoryboardResult =
  | { ok: true; value: Storyboard }
  | { ok: false; errors: string[] };

/**
 * Validate an arbitrary value against the Storyboard schema.
 *
 * Never throws — wraps `StoryboardSchema.safeParse` and flattens any Zod
 * issues into readable `"path: message"` strings (e.g.
 * `"scenes.0.shots.1.frames.1: Shot.frames[1] (end) must be greater than
 * Shot.frames[0] (start)"`). A root-level issue (empty path) is reported as
 * `"(root): message"`.
 */
export function validateStoryboard(data: unknown): ValidateStoryboardResult {
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
