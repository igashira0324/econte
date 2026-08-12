/**
 * Zod schema for the econte storyboard format.
 *
 * This module is the source of truth for the schema described in
 * `docs/schema-spec.md`. `spec/econte.schema.json` (JSON Schema 2020-12) is
 * generated from this file via `npm run build:schema`
 * (see `scripts/build-schema.mjs`), and `python/econte/models.py` is a
 * hand-maintained pydantic mirror validated against the same golden
 * fixtures in `spec/fixtures/`.
 *
 * Per-field constraints (types, formats, ranges) are expressed directly on
 * the relevant `z.object()` schemas below. Cross-field ("document-level")
 * rules that need to see more than one field/object at once — id
 * uniqueness, referential integrity, `end > start` style ordering — are
 * implemented with `.refine()` / `.superRefine()`, per
 * "Document-level (cross-field) validation rules" in docs/schema-spec.md.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

/** `^\d+\.\d+\.\d+$` — semver `x.y.z`. */
const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

/** `^[a-z][a-z0-9_-]*$` — Character.id. */
const CHARACTER_ID_PATTERN = /^[a-z][a-z0-9_-]*$/;

/** `^[A-Za-z0-9_-]+$` — Scene.id and Shot.id. */
const SLUG_ID_PATTERN = /^[A-Za-z0-9_-]+$/;

/** `^\d+:\d+$` — Metadata.aspectRatios entries, e.g. `"16:9"`. */
const ASPECT_RATIO_PATTERN = /^\d+:\d+$/;

/** `^#[0-9a-fA-F]{6}$` — GlobalStyle.palette entries. */
const HEX_COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/;

/** A `Shot.subject` referencing a character must start with `"@"`. */
const SUBJECT_PATTERN = /^@.+$/;

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export const MetadataSchema = z.object({
  title: z.string().min(1, "Metadata.title must be non-empty"),
  artist: z.string().optional(),
  audio: z.string().optional(),
  durationInSeconds: z
    .number()
    .positive("Metadata.durationInSeconds must be > 0 if present")
    .optional(),
  fps: z.number().int("Metadata.fps must be an integer").positive("Metadata.fps must be > 0"),
  aspectRatios: z
    .array(
      z
        .string()
        .regex(ASPECT_RATIO_PATTERN, 'Metadata.aspectRatios entries must match ^\\d+:\\d+$ (e.g. "16:9")'),
    )
    .min(1, "Metadata.aspectRatios must be non-empty"),
  concept: z.string().optional(),
});
export type Metadata = z.infer<typeof MetadataSchema>;

// ---------------------------------------------------------------------------
// Character
// ---------------------------------------------------------------------------

export const CharacterSchema = z.object({
  id: z
    .string()
    .regex(CHARACTER_ID_PATTERN, "Character.id must match ^[a-z][a-z0-9_-]*$"),
  identity: z.string().min(1, "Character.identity must be non-empty"),
  refs: z.array(z.string()).min(1, "Character.refs must be non-empty"),
});
export type Character = z.infer<typeof CharacterSchema>;

// ---------------------------------------------------------------------------
// GlobalStyle
// ---------------------------------------------------------------------------

export const GlobalStyleSchema = z.object({
  palette: z
    .array(
      z
        .string()
        .regex(HEX_COLOR_PATTERN, 'GlobalStyle.palette entries must be 6-digit hex colors (e.g. "#00e5ff")'),
    )
    .optional(),
  grade: z.string().optional(),
  negative: z.array(z.string()).optional(),
});
export type GlobalStyle = z.infer<typeof GlobalStyleSchema>;

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------

export const CameraFramingEnum = z.enum([
  "ECU",
  "CU",
  "MCU",
  "MS",
  "MLS",
  "WS",
  "EWS",
  "OTS",
  "POV",
  "2S",
  "INS",
  "FS",
  "BEV",
]);
export type CameraFraming = z.infer<typeof CameraFramingEnum>;

export const CameraSchema = z.object({
  framing: CameraFramingEnum.optional(),
  movement: z.string().optional(),
});
export type Camera = z.infer<typeof CameraSchema>;

// ---------------------------------------------------------------------------
// Source
// ---------------------------------------------------------------------------

export const SourceTypeEnum = z.enum(["generate", "asset", "remotion"]);
export type SourceType = z.infer<typeof SourceTypeEnum>;

export const SourceMaterialEnum = z.enum(["chain", "chain_start", "standalone"]);
export type SourceMaterial = z.infer<typeof SourceMaterialEnum>;

export const SourceSchema = z.object({
  type: SourceTypeEnum,
  backend: z.string().optional(),
  keyframe: z.string().optional(),
  seed: z.number().int().optional(),
  prompt: z.string().optional(),
  // Required in the schema sense (always present on output) but defaults to
  // `false` when omitted on input — see docs/schema-spec.md's Source.approved
  // note: implementations must always emit this field explicitly.
  approved: z.boolean().default(false),
  material: SourceMaterialEnum.optional(),
});
export type Source = z.infer<typeof SourceSchema>;

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export const RenderSchema = z.object({
  file: z.string().optional(),
  actualSeconds: z
    .number()
    .positive("Render.actualSeconds must be > 0 if present")
    .optional(),
  renderedAt: z
    .string()
    .datetime({ offset: true, message: "Render.renderedAt must be an ISO 8601 datetime" })
    .optional(),
});
export type Render = z.infer<typeof RenderSchema>;

// ---------------------------------------------------------------------------
// Lyric
// ---------------------------------------------------------------------------

export const LyricSchema = z
  .object({
    text: z.string(),
    startMs: z.number().int().min(0, "Lyric.startMs must be >= 0"),
    endMs: z.number().int(),
    animation: z.string().optional(),
  })
  .refine((lyric) => lyric.endMs > lyric.startMs, {
    message: "Lyric.endMs must be greater than Lyric.startMs",
    path: ["endMs"],
  });
export type Lyric = z.infer<typeof LyricSchema>;

// ---------------------------------------------------------------------------
// Shot
// ---------------------------------------------------------------------------

/** `[start, end]`, both `>= 0`, `end > start`. */
export const FramesSchema = z
  .tuple([
    z.number().int().min(0, "Shot.frames[0] (start) must be >= 0"),
    z.number().int().min(0, "Shot.frames[1] (end) must be >= 0"),
  ])
  .refine((frames) => frames[1] > frames[0], {
    message: "Shot.frames[1] (end) must be greater than Shot.frames[0] (start)",
    path: [1],
  });
export type Frames = z.infer<typeof FramesSchema>;

/**
 * Either `null`/absent, or `"@" + <characters[].id>`. The `"@"` prefix is
 * validated here; that the referenced character actually exists is a
 * cross-field concern handled in `StoryboardSchema`'s `superRefine` below,
 * since it requires seeing `characters[]` from the rest of the document.
 */
export const SubjectSchema = z
  .string()
  .regex(SUBJECT_PATTERN, 'Shot.subject must start with "@" (e.g. "@haruka") when present')
  .nullable()
  .optional();

export const ShotSchema = z.object({
  id: z.string().regex(SLUG_ID_PATTERN, "Shot.id must match ^[A-Za-z0-9_-]+$"),
  frames: FramesSchema,
  idea: z.string().optional(),
  subject: SubjectSchema,
  action: z.string().optional(),
  camera: CameraSchema.optional(),
  heroMotion: z.string().optional(),
  audioSync: z.string().optional(),
  source: SourceSchema.optional(),
  render: RenderSchema.optional(),
  lyric: LyricSchema.nullable().optional(),
});
export type Shot = z.infer<typeof ShotSchema>;

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

export const SceneSchema = z.object({
  id: z.string().regex(SLUG_ID_PATTERN, "Scene.id must match ^[A-Za-z0-9_-]+$"),
  section: z.string().optional(),
  shots: z.array(ShotSchema).min(1, "Scene.shots must be non-empty"),
});
export type Scene = z.infer<typeof SceneSchema>;

// ---------------------------------------------------------------------------
// Storyboard (root)
// ---------------------------------------------------------------------------

const StoryboardObjectSchema = z.object({
  version: z.string().regex(VERSION_PATTERN, "Storyboard.version must be semver x.y.z (e.g. \"0.1.0\")"),
  metadata: MetadataSchema,
  characters: z.array(CharacterSchema),
  globalStyle: GlobalStyleSchema.optional(),
  audioAnalysis: z.string().optional(),
  scenes: z.array(SceneSchema).min(1, "Storyboard.scenes must be non-empty"),
});

/**
 * The full Storyboard schema, including the document-level (cross-field)
 * validation rules from docs/schema-spec.md:
 *
 *   1. Every `Character.id` is unique within `characters[]`.
 *   2. Every `Scene.id` is unique within `scenes[]`.
 *   3. Every `Shot.id` is unique across the WHOLE document (all scenes).
 *   4. `Shot.frames[1] > Shot.frames[0]` — enforced on `FramesSchema` itself.
 *   5. `Shot.subject`, if it starts with `"@"`, must reference an existing
 *      `Character.id`.
 *   6. `Lyric.endMs > Lyric.startMs` — enforced on `LyricSchema` itself.
 *   7. Non-empty array constraints — enforced per-field above.
 */
export const StoryboardSchema = StoryboardObjectSchema.superRefine((doc, ctx) => {
  // Rule 1: Character.id uniqueness within characters[].
  const characterIds = new Set<string>();
  doc.characters.forEach((character, index) => {
    if (characterIds.has(character.id)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Duplicate character id "${character.id}" — Character.id must be unique within characters[]`,
        path: ["characters", index, "id"],
      });
    } else {
      characterIds.add(character.id);
    }
  });

  // Rule 2: Scene.id uniqueness within scenes[].
  const sceneIds = new Set<string>();
  doc.scenes.forEach((scene, sceneIndex) => {
    if (sceneIds.has(scene.id)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Duplicate scene id "${scene.id}" — Scene.id must be unique within scenes[]`,
        path: ["scenes", sceneIndex, "id"],
      });
    } else {
      sceneIds.add(scene.id);
    }
  });

  // Rule 3 (shot id global uniqueness) and Rule 5 (subject referential
  // integrity) both require walking every shot in every scene.
  const shotIds = new Set<string>();
  doc.scenes.forEach((scene, sceneIndex) => {
    scene.shots.forEach((shot, shotIndex) => {
      if (shotIds.has(shot.id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Duplicate shot id "${shot.id}" — Shot.id must be unique across the entire document, not just within its scene`,
          path: ["scenes", sceneIndex, "shots", shotIndex, "id"],
        });
      } else {
        shotIds.add(shot.id);
      }

      if (shot.subject != null) {
        const referencedCharacterId = shot.subject.slice(1); // strip leading "@"
        if (!characterIds.has(referencedCharacterId)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Shot.subject "${shot.subject}" references unknown character id "${referencedCharacterId}" — no matching entry in characters[]`,
            path: ["scenes", sceneIndex, "shots", shotIndex, "subject"],
          });
        }
      }
    });
  });
});

export type Storyboard = z.infer<typeof StoryboardSchema>;
