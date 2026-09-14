# BenchWeave SDK README Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a polished BenchWeave SDK README banner that matches the main project family and integrate it at the top of the SDK README.

**Architecture:** Generate one wide PNG from the approved visual specification, inspect the rendered output for copy and composition, then store it as a project-owned documentation asset. Add one relative Markdown reference at the start of the README and verify both the file and link.

**Tech Stack:** Built-in OpenAI image generation, PNG, Markdown, Git

## Global Constraints

- Title text must be exactly `BenchWeave SDK`.
- Tagline text must be exactly `Build. Validate. Integrate.`.
- Use a dark navy technical grid, polished 3D instrumentation, cyan and amber connection lighting, strong white title typography and a restrained pale-blue subtitle.
- Keep the title and tagline on the left and the technical scene on the right.
- Avoid third-party logos, watermarks, tiny illegible labels and unsafe laboratory imagery.
- Save the final asset as `docs/assets/benchweave-sdk-banner.png`.
- Use descriptive alt text and place the image at the top of `README.md`.

---

### Task 1: Generate and validate the banner asset

**Files:**
- Create: `docs/assets/benchweave-sdk-banner.png`
- Reference: `docs/superpowers/specs/2026-09-15-readme-banner-design.md`

**Interfaces:**
- Consumes: approved title, tagline, composition, palette and scene constraints from the design specification.
- Produces: a wide PNG at `docs/assets/benchweave-sdk-banner.png` suitable for a GitHub README hero.

- [ ] **Step 1: Generate the banner**

Use the built-in image-generation tool with this prompt:

```text
Use case: ads-marketing
Asset type: wide GitHub README hero banner for a developer SDK
Primary request: Create a sibling banner for the BenchWeave plugin developer SDK, visibly in the same visual family as the main BenchWeave project banner without duplicating its exact scene.
Scene/backdrop: dark navy technical grid fading into a clean deep-blue background
Subject: on the right, a polished 3D modular plugin package flows through build, validation and integration stages into a compact BenchWeave gateway connected to representative electronic bench instruments; express stages with clear package, check/test and connection motifs rather than dense labels
Style/medium: premium polished 3D technical illustration, credible laboratory and developer-tool aesthetic
Composition/framing: very wide landscape banner; left 45 percent reserved for large title and subtitle; technical scene concentrated on the right; generous margins; readable at GitHub README width
Lighting/mood: precise cyan and amber connection glow, controlled highlights, confident and professional
Color palette: deep navy, cyan, amber, white and pale blue
Text (verbatim): "BenchWeave SDK" and "Build. Validate. Integrate."
Constraints: spell visible text exactly; strong white title; restrained pale-blue subtitle; safe and tidy bench setup; no other visible words
Avoid: third-party logos, watermarks, tiny interface labels, clutter, playful cartoon styling, duplicated objects, malformed cables or unsafe laboratory imagery
```

Expected: one wide banner with accurate title and tagline and clear negative space around the copy.

- [ ] **Step 2: Inspect the generated image**

Open the generated output at original detail and confirm:

```text
[ ] Title reads exactly “BenchWeave SDK”
[ ] Tagline reads exactly “Build. Validate. Integrate.”
[ ] Copy remains legible at README width
[ ] Scene is concentrated on the right
[ ] Cyan/amber lighting and dark navy grid match the project family
[ ] No third-party logos, watermarks, stray text or unsafe imagery
```

Expected: all checks pass. If one check fails, regenerate once with a targeted correction naming only the failed invariant.

- [ ] **Step 3: Save the approved output in the repository**

Copy the selected generated PNG to:

```text
docs/assets/benchweave-sdk-banner.png
```

Expected: the file exists and is a valid PNG.

- [ ] **Step 4: Verify the asset**

Run:

```bash
file docs/assets/benchweave-sdk-banner.png
```

Expected: output identifies `PNG image data` with a landscape width greater than height.

- [ ] **Step 5: Commit the asset**

```bash
git add docs/assets/benchweave-sdk-banner.png
git commit -m "docs: add SDK README banner"
```

### Task 2: Integrate the banner into the README

**Files:**
- Modify: `README.md:1`
- Test: `README.md`

**Interfaces:**
- Consumes: `docs/assets/benchweave-sdk-banner.png` from Task 1.
- Produces: a README hero image reference resolving to the committed PNG.

- [ ] **Step 1: Add the banner reference**

Insert this exact line before the existing first heading, followed by one blank line:

```markdown
![BenchWeave SDK — Build. Validate. Integrate. A plugin package moving through build and validation into the BenchWeave gateway and connected instruments.](docs/assets/benchweave-sdk-banner.png)
```

Expected: the existing README content remains unchanged below the new hero image.

- [ ] **Step 2: Verify the Markdown path and copy**

Run:

```bash
test -f docs/assets/benchweave-sdk-banner.png && grep -F '](docs/assets/benchweave-sdk-banner.png)' README.md
```

Expected: exit status `0` and the banner Markdown line is printed once.

- [ ] **Step 3: Review the final diff**

Run:

```bash
git diff --check
git diff -- README.md
```

Expected: `git diff --check` has no output, and the README diff contains only the new image line and blank line.

- [ ] **Step 4: Commit the README integration**

```bash
git add README.md
git commit -m "docs: feature SDK banner in README"
```
