# @econte/schema

TypeScript/Zod schema and validator for the [econte](../../README.md)
storyboard format. This package is the **source of truth** for the schema:
[`spec/econte.schema.json`](../../spec/econte.schema.json) is generated from
it (`npm run build:schema`), and [`python/econte/models.py`](../../python/econte/models.py)
is a hand-maintained pydantic mirror validated against the same fixtures in
[`spec/fixtures/`](../../spec/fixtures/).

See [`docs/schema-spec.md`](../../docs/schema-spec.md) at the repository
root for the authoritative field-by-field specification.

## Install

```bash
npm install @econte/schema
```

## Usage

```ts
import { validateStoryboard } from "@econte/schema";
import { readFileSync } from "node:fs";

const data = JSON.parse(readFileSync("storyboard.json", "utf-8"));
const result = validateStoryboard(data);

if (result.ok) {
  // result.value is a fully-typed `Storyboard`
  console.log(`${result.value.scenes.length} scene(s)`);
} else {
  // result.errors is string[], each formatted as "path: message"
  console.error(result.errors.join("\n"));
  process.exit(1);
}
```

`validateStoryboard` never throws — it wraps `StoryboardSchema.safeParse`
and flattens Zod issues into readable strings. It enforces both the
per-field constraints (types, formats, ranges, enums) and the
document-level cross-field rules from `docs/schema-spec.md`:

- `Character.id` unique within `characters[]`.
- `Scene.id` unique within `scenes[]`.
- `Shot.id` unique **across the entire document**, not just within its scene.
- `Shot.frames[1]` (end) `> Shot.frames[0]` (start).
- `Shot.subject`, when it starts with `"@"`, must reference a declared
  `Character.id`.
- `Lyric.endMs > Lyric.startMs`.
- Non-empty array constraints (`scenes`, `scene.shots`, `metadata.aspectRatios`, …).

If you only need the Zod schema (e.g. to build your own error formatting,
or to compose it into a larger schema), import it directly:

```ts
import { StoryboardSchema, type Storyboard } from "@econte/schema";

const storyboard: Storyboard = StoryboardSchema.parse(data); // throws on failure
```

Every sub-schema is also exported individually (`MetadataSchema`,
`CharacterSchema`, `GlobalStyleSchema`, `SceneSchema`, `ShotSchema`,
`CameraSchema`, `SourceSchema`, `RenderSchema`, `LyricSchema`), each with a
matching `z.infer` type export (`Metadata`, `Character`, `GlobalStyle`,
`Scene`, `Shot`, `Camera`, `Source`, `Render`, `Lyric`).

## Development

```bash
npm install
npm run build         # tsc -> dist/
npm run build:schema  # builds, then regenerates ../../spec/econte.schema.json
npm test               # vitest run — includes spec/fixtures/*.json golden tests
npm run lint            # eslint .
```

## License

Apache-2.0 — see [`LICENSE`](../../LICENSE) at the repository root.
