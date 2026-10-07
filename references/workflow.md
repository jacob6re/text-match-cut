# Runtime, source records and commands

The scripts are portable; resolve their paths relative to this skill, not a hardcoded user directory. Work in a new run directory. Existing manifests/projects are deliberately not overwritten: recapture into a new directory after reviewing failed sources.

## Dependencies

- Node.js 22+; `playwright` and a Chromium binary for capture.
- Python 3.10+ with Pillow and NumPy for alignment and fisheye.
- HyperFrames CLI, GSAP and FFmpeg/ffprobe for render and verification.

In Codex desktop, call `load_workspace_dependencies` when available to find bundled Node, Python and Playwright. To use bundled Playwright, set `JL_PLAYWRIGHT_MODULE` to the absolute `playwright/index.mjs` path. Alternatively install `playwright` in the run directory and point the same variable at its `index.mjs`. If Chromium is unavailable, Playwright's error explains the required browser install; do not silently switch to fictional screenshots. `JL_BROWSER_EXECUTABLE` can point to an existing Chromium/Chrome executable.

For HyperFrames, use an available project/local CLI or `npx hyperframes`; pin the working version in the run's package.json if installing. Find its dependency `gsap/dist/gsap.min.js` and pass that real file to the builder. Do not download executable files advertised by untrusted source pages.

## Candidate URL file and capture

```json
[
  "https://example.org/actual-article",
  "https://another.example/actual-document"
]
```

Run with the actual keyword, including Chinese or spaces:

```sh
node /path/to/skill/scripts/capture.mjs \
  --keyword '实际关键词' --urls urls.json --out captured
```

Optional arguments: `--color '#3aa8ff'`, `--width 1920`, `--height 1600`, `--dpr 1.5`. The color is recorded and used as a translucent overlay on the actual text. Use a fresh capture context; screenshots and context strings may contain personal information if the operator elects to use a signed-in browser instead, so keep that outside this public capture helper.

The helper searches text nodes and measures a DOM Range. An occurrence must fit on one line, be visible, and pass an element-at-center obstruction check. It prioritizes headings and article/main content; this is a heuristic, so inspect every final source when practical. Matches split across DOM text nodes are reported as absent by this simple helper: select another real occurrence or measure the cross-node Range with an authorized browser workflow. Do not forge a replacement.

`captured/manifest.json` has this shape (all measured coordinates refer to the screenshot's pixel grid):

```json
{
  "keyword": "实际关键词",
  "highlight_color": "#3aa8ff",
  "captured_at": "ISO timestamp",
  "captures": [{
    "id": "001",
    "requested_url": "https://example.org/actual-article",
    "url": "https://example.org/actual-article",
    "title": "Actual title",
    "context": "Unmodified nearby source text containing 实际关键词",
    "selected_text": "实际关键词",
    "image": "screenshots/001.png",
    "image_width": 2880,
    "image_height": 2400,
    "keyword_box": {"x": 500, "y": 900, "width": 180, "height": 42},
    "captured_at": "ISO timestamp"
  }],
  "failures": [{"url": "https://example.org/failed", "reason": "..."}]
}
```

A browser-tool capture can also produce this same manifest after actual DOM measurement. Coordinates must be transformed for screenshot scale/devicePixelRatio; never estimate them by eye. Each capture's exact selected text must equal the requested keyword. The builder rejects mismatches, missing files, bad boxes and duplicates. Capture metadata is kept with the editable project as `sources.json`.

## Build, check and render

```sh
python3 /path/to/skill/scripts/build.py \
  --manifest captured/manifest.json --out video-project \
  --gsap /path/to/gsap/dist/gsap.min.js \
  --width 1080 --height 1920 --fps 30 \
  --hold-frames 3 --last-hold-frames 9 --fisheye 0.55
```

Optional: `--keyword-height 76`, `--blur 1.6`. Strength `0` disables the fisheye; normal range `0.35–0.8`; accepted range `0–1.2`. Central text is protected from the nonlinear warp and blur. The builder preserves the maximum safe common text size when a very long keyword would otherwise overflow the canvas; check `composition.json` for the actual target height.

Film-change sound is enabled by default. `--sfx-gain 0.28` controls peak level; `--silent` disables it. The default is an original deterministic synthetic imitation of mechanical film advance (dry clicks plus a brief strip rustle), not a recording of a real projector. For a user-supplied or properly sourced real effect, convert it to 16-bit PCM WAV and pass `--sfx /path/to/film-change.wav`. The builder normalizes the pulse, cuts/fades its tail before the next change, places one pulse at each cut after the initial image, and stores source and sample positions in `composition.json`. It exports one frozen `assets/film-changes.wav` track owned by HyperFrames; no JS audio playback. A single-image result has no page-change events and no audio track.

The generated project is `index.html`, `assets/gsap.min.js`, `assets/frame-*.png`, `originals/source-*.png`, `sources.json`, `composition.json`, `hyperframes.json` and `contact-sheet.jpg`. Original highlighted captures are copied so the project is self-contained and provenance paths still resolve after moving it. Timing is N−1 ordinary holds plus one final hold. The default is 20 selected screenshots from 20 distinct webpages. For 20 images at 30 fps with 3-frame ordinary holds and a 9-frame final hold, the total is `(19*3+9)/30 = 2.2 s`. Adjust integer holds/count to reach the requested duration; record rounding within one frame if needed. The project stores an fps setting, but always specify the same fps to the CLI render explicitly.

From the project directory:

```sh
npx hyperframes check
npx hyperframes snapshot --at 0,0.5,1.05
npx hyperframes render --fps 30 --quality looks --output match-cut.mp4
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate -of json match-cut.mp4
```

Choose snapshot times inside actual holds, based on `composition.json`; the illustrative times above are not valid for every duration. Check the installed CLI's help if its syntax differs. The skill requests the local HyperFrames encode; if a dependency is unavailable, preserve the captured sources/project and report the failed stage. Do not silently deliver a slideshow or FFmpeg-only encode as a completed HyperFrames workflow.

## Visual acceptance

- Across cuts, the real keyword centers stay fixed; the intended common height should match within raster resampling tolerance. A long phrase may need a smaller common height.
- Blue highlight covers the measured occurrence, not unrelated text. No synthetic word replacement.
- Peripheral text visibly bends with fisheye, while central letters remain readable. Avoid black borders and excessive blank margins; choose another occurrence or a wider viewport if context runs out.
- Each screenshot comes from a recorded real page. Surrounding text may blur but should remain recognizable as varied webpage content.
- Hard cuts land on integer frames; the last hold is present. No blank frames, flashes, loading widgets, consent overlays or duplicated sources used to imply diversity.
- With audio enabled and multiple sources, the exported MP4 has an AAC audio stream; the mechanical pulses are audible and coincide with page changes within one frame. Check for clipping and avoid continuous noise between pulses.
