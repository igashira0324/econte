# Why econte

This document summarizes the landscape review (conducted 2026-08-13) that
motivated this project, so the reasoning survives independent of any one
conversation or issue thread.

## The gap

1. **No standard storyboard interchange format.** Practitioners fall back
   to PDF/image boards, spreadsheets for shot lists, and — in AI-video
   circles — one-off JSON schemas per tool or per project. The closest
   thing to a public schema attempt, `context-notation/video-notation-schema`,
   is a single-maintainer project with low adoption. Nothing treats
   *approval state* or *lyric/beat sync* as first-class.
2. **Hosted AI storyboard tools keep your data.** LTX Studio, Google Flow,
   Kling 3.0's multi-shot mode, Freepik/Magnific — all capable, all lock
   the storyboard inside their own product. OpenAI's Sora shipped a
   storyboard UI and shut the whole product down 84 days later (April
   2026), which is as good an argument as any for owning your own format.
3. **The OSS "script → storyboard → video" agents that exist are cloud-only.**
   ViMax (11.9k★, most active as of 2026-07) and VideoClaw both orchestrate
   Veo/Seedance/Kling-class APIs. Neither targets a local ComfyUI backend,
   let alone a 12GB-class consumer GPU. Research-stage projects that *do*
   use local models (MovieAgent, Anim-Director) are unmaintained and were
   never sized for consumer hardware.
4. **ComfyUI's own ecosystem is converging on this idea, but as closed
   products, not a shared format.** LTX Director, its MiniMax-H3 port, and
   Velorn (formerly ComfyStudio) all added timeline/storyboard UIs in 2026 —
   evidence the need is real, but each keeps its own internal project
   format. They're GPL-3.0; econte does not copy their code, only observes
   their JSON shapes for interoperability ideas.

## What that leaves as the useful thing to build

Not another end-to-end product — the thing every one of the above already
is. What's missing is the layer underneath all of them: a schema that
takes `approved` and `lyric` seriously, and a manifest-driven runner that
turns storyboard shots into ComfyUI jobs against *whatever* model you
already have downloaded, with the shot chaining/reframing semantics that
video generation with limited context windows actually needs (a single
generation chain is one long take — cutaways and reframes require the
storyboard to know about multiple material types, not just a shot list).

See the main [README](../README.md) for the resulting pipeline.
