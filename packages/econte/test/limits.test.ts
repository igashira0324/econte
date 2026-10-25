/**
 * Upper bounds on arrays and on the total shot count (docs/schema-spec.md,
 * rule 7). validateStoryboard() must reject an oversized document with one
 * error per offending array, without validating its elements: zod 3 keeps
 * validating every element after an array's .max() check fails
 * (GHSA-mrhx-c7xc-m3w5).
 */

import { describe, expect, it } from "vitest";
import { ARRAY_LIMITS, validateStoryboard } from "../src/index.js";

function storyboard(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: "0.1.0",
    metadata: { title: "t", fps: 24, aspectRatios: ["16:9"] },
    characters: [],
    scenes: [{ id: "S01", shots: [{ id: "S01-A", frames: [0, 120] }] }],
    ...overrides,
  };
}

function fullScenes(count: number): unknown[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `S${i}`,
    shots: Array.from({ length: ARRAY_LIMITS.shotsPerScene }, (_, j) => ({
      id: `S${i}-${j}`,
      frames: [0, 1],
    })),
  }));
}

describe("rule 7 upper bounds", () => {
  it("rejects an oversized array with one error, not one per element", () => {
    const result = validateStoryboard(
      storyboard({ metadata: { title: "t", fps: 24, aspectRatios: Array(1_000_000).fill("x") } }),
    );
    expect(result).toEqual({
      ok: false,
      errors: [`metadata.aspectRatios: must have at most ${ARRAY_LIMITS.aspectRatios} entries (got 1000000)`],
    });
  });

  it("accepts exactly the total shot budget and rejects one more scene", () => {
    const scenesAtLimit = ARRAY_LIMITS.totalShots / ARRAY_LIMITS.shotsPerScene;
    expect(validateStoryboard(storyboard({ scenes: fullScenes(scenesAtLimit) })).ok).toBe(true);

    const over = ARRAY_LIMITS.totalShots + ARRAY_LIMITS.shotsPerScene;
    expect(validateStoryboard(storyboard({ scenes: fullScenes(scenesAtLimit + 1) }))).toEqual({
      ok: false,
      errors: [`scenes: at most ${ARRAY_LIMITS.totalShots} shots in total (got ${over})`],
    });
  });
});
