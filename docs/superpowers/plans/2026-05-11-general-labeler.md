# General Labeler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the task-specific texture-person labeler into a configurable labeler with fixed `groundtruth`, user-defined extra dimensions, and a configurable export JSON filename.

**Architecture:** Keep the single Flask script. Add small backend helpers for dimension parsing and export filename normalization, store active dimensions in `STATE`, and have the frontend render statistics and label controls from the backend-provided dimensions.

**Tech Stack:** Python, Flask, Pillow, browser JavaScript, unittest.

---

### Task 1: Backend Helpers And Tests

**Files:**
- Create: `tests/test_general_labeler.py`
- Modify: `test_set_labeler_texture_person.py`

- [ ] **Step 1: Write failing tests**

Create tests for `parse_label_dims`, `sanitize_export_filename`, and dynamic empty label records.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_general_labeler -v`
Expected: fail because helper functions do not exist yet.

- [ ] **Step 3: Implement helpers**

Add `BASE_DIM`, `DEFAULT_EXPORT_FILENAME`, `parse_label_dims`, `sanitize_export_filename`, and update `make_empty_label_record` to accept a dynamic dimensions list.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_general_labeler -v`
Expected: pass.

### Task 2: Dynamic Flask State

**Files:**
- Modify: `test_set_labeler_texture_person.py`

- [ ] **Step 1: Replace fixed dimensions**

Replace fixed `DIMS` usage in stats, label validation, load, and export with `STATE["dims"]`.

- [ ] **Step 2: Accept page configuration**

Read `extra_dims` in `/load` and `export_filename` in `/export`.

- [ ] **Step 3: Return dimensions to frontend**

Include `dims` in the `/load` response.

### Task 3: Frontend Dynamic Rendering

**Files:**
- Modify: `test_set_labeler_texture_person.py`

- [ ] **Step 1: Add inputs**

Add an empty extra dimensions input near the load controls and an export JSON filename input near the export directory.

- [ ] **Step 2: Render from dynamic dimensions**

Change frontend `DIMS` from a constant to dynamic `dims`, and update empty records, stats, dimension sections, and export requests to use it.

- [ ] **Step 3: Verify manually**

Run the Flask app and load a small dataset. Confirm empty extra dimensions shows only `groundtruth`, custom dimensions render, and export uses the selected filename.
