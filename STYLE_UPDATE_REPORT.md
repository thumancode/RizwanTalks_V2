# RizwanTalks styles update — audit report

## Source audit
- Themes: 296.
- Style fields and distinct values used: pattern 42; frame 16; orn 14; chip 8; rule 7; rays 8; particles 13; arch 10; motion 13.
- Before changes, semantic drawing gaps in the uploaded prompt's categories affected approximately: pattern 204 theme uses; frame 70; orn 60; chip 124; rule 132; rays 216 (the field treated every non-`none` value as the same ray effect); particles 116; arch 145; motion 223.
- Implemented/extended source locations: `site/decor.js` (`RT.buildBackground`, `RT.buildFrame`, `RT.buildParticles`); `site/base.js` (`ornPath`, `MOT`, `appear`); `site/scenes.js` (`makeRule`, `archPath`, `archExt`, `arch`, intro/CTA rays); `site/style.css` (chip, card, step-number styles); `render.py` (Bengali warning for unsupported values); `tools/audit_styles.py` (style-value audit); `README.md` (registry/documentation).

## Checks actually run
- `python source/tools/audit_styles.py`: PASS, 296 themes and 0 gaps against the explicit supported-value registry.
- `node --check` on `decor.js`, `base.js`, `scenes.js`, `main.js`: PASS.
- Python byte-compilation of source Python files: command returned success.
- `python source/tools/bundle.py`: PASS; bundled `source/dist/make_video.py` was copied to root and the `source/render` files synchronized into `build/_engine`.

## Checks not completed
- Rendering stills failed because Playwright's Chromium executable is not installed in this environment. Consequently, the required pre-change/post-change pixel-identical regression test, visual contact sheets for 296 themes in both ratios, scene-by-scene visual review, pairwise image-difference test, and 60-frame speed benchmark were **not run**. No claim is made that these visual/performance tests passed.
- The audit script intentionally uses the documented explicit supported-value registry as allowed in the prompt; it checks theme values against that registry, not by parsing every drawing branch.

## Follow-up: registry vs. drawing-code audit
- Read every field's drawing code. All registry values reach a branch (explicit, `else`/default, or intentional no-op). `frame=corner` is drawn by the trailing `else` (four L-brackets).
- Fixed look-alikes: `pattern=enso` is now open brush arcs (was identical to `rings`); `wave`, `contour`, `topographic` now differ in spacing, amplitude and stroke (`wave` and `contour` were pixel-identical).
- `tools/audit_styles.py` now also checks that each non-fallback registry value appears literally in its drawing source; intentional fallbacks are listed in `FALLBACK`. Negative test (fake value) correctly fails.
- Re-run: audit PASS, `node --check` PASS on 4 JS files, Python compile PASS, bundle rebuilt and synced to root and `build/_engine`.
- Still NOT run (no Chromium): rendering/visual checks of the changed patterns, regression and speed tests. Known remaining look-alikes (not changed): `rings`/`ripple`, `checker`/`tile`, `sunburst`/`conic`, `pill` = default chip.
