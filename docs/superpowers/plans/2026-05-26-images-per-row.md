# Images Per Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toolbar control that sets how many images appear per row inside each group.

**Architecture:** Keep the backend unchanged. Add frontend state for `imagesPerRow`, persist it in `localStorage`, render all group images in one grid, and drive CSS columns through a `--images-per-row` custom property.

**Tech Stack:** Static HTML, browser JavaScript, CSS, Python `unittest` static regression tests, Node syntax check.

---

## Files

- Modify: `json_labeler/index.html`
  Add the `Images Per Row` numeric input.
- Modify: `json_labeler/static/app.js`
  Add state, localStorage handling, event binding, and unified image grid rendering.
- Modify: `json_labeler/static/style.css`
  Add unified image grid CSS using `--images-per-row`.
- Modify: `tests/test_json_labeler_backend.py`
  Add static regression tests for the UI wiring.

## Tasks

- [ ] Add failing tests that check for `#imagesPerRowInput`, `jsonLabeler.imagesPerRow`, `changeImagesPerRow`, `.image-grid`, and `--images-per-row`.
- [ ] Implement the HTML input and default display value.
- [ ] Implement JS state, clamping, localStorage persistence, grid rendering, and event binding.
- [ ] Implement CSS grid layout with responsive fallback.
- [ ] Run `python -m unittest tests.test_json_labeler_backend -v`.
- [ ] Run `node --check json_labeler/static/app.js`.
- [ ] Browser verify that changing the control reflows `cond_1`, `cond_2`, and target cards together.
- [ ] Commit the finished feature.
