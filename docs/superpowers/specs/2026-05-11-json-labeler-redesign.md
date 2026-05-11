# JSON Labeler Redesign Design

## Goal

Redesign `json_labeler` as a reusable JSON triplet labeling tool. The tool loads an input JSON array whose records contain `file_name`, `cond_1`, `cond_2`, `prompt`, `width`, and `height`; shows the three related images plus the edit prompt; supports efficient manual `pass` / `fail` labeling; resumes long annotation sessions automatically; and exports three JSON files.

The `json_labeler` directory is a tool directory and sample workspace, not the required location for real datasets. Real input JSON files and images may live anywhere on disk.

## Architecture

Use a small static frontend plus Python API backend:

```text
json_labeler/
  server.py
  index.html
  static/
    app.js
    style.css
  input_data_file.json
```

`server.py` serves the static files, image bytes, and JSON API endpoints. `index.html`, `static/app.js`, and `static/style.css` own the browser experience. This split keeps the backend focused on filesystem-safe data operations and makes the frontend easier to extend.

No Flask dependency is required unless implementation later finds the existing `http.server` approach too limiting. The preferred implementation is still standard-library Python.

## Input Model

The input file is a JSON array. Each record is expected to include:

- `file_name`: target/output image path
- `cond_1`: source image path
- `cond_2`: reference image path
- `prompt`: edit prompt shown in the UI
- `width` and `height`: retained as source metadata

Additional fields are preserved. The loader should not fail the whole dataset when one record has a missing image or malformed path. Instead, return the record with image-level error metadata so the page can show an empty/error image area while still allowing a human label.

Each sample receives a stable key:

```text
sha1(file_name + "\n" + cond_1 + "\n" + cond_2)
```

This key is used only for matching labels to records. It is not exported into pass/fail filtered files.

## Sidecar Resume File

The default progress file is derived from the input JSON path:

```text
input_data_file.json -> input_data_file.labels.json
```

When the user loads an input JSON, the backend loads this sidecar if it exists. Labels are matched by stable sample key. Each label action immediately updates the same sidecar file, so browser refreshes, server restarts, and multi-day labeling sessions can continue without manual checkpointing.

The sidecar shape is:

```json
{
  "source_file": ".../input_data_file.json",
  "source_mtime": 1778490000.123,
  "updated_at": "2026-05-11T17:40:00+08:00",
  "labels": {
    "stable_sample_key": {
      "human_label": "pass",
      "updated_at": "2026-05-11T17:39:12+08:00"
    }
  }
}
```

Allowed `human_label` values are `pass`, `fail`, and empty string. If the input JSON later changes, matching records recover old labels, new records start unlabeled, and labels for removed records remain in the sidecar but are not shown or exported.

Sidecar writes must be atomic: write a temporary file, flush it, then replace the old sidecar. If a sidecar cannot be parsed, rename it to a timestamped `.corrupt-<timestamp>.json` file and start with an empty sidecar instead of overwriting evidence.

## Export Behavior

The export panel contains:

- export directory
- annotated-all filename, default `annotated_all.json`
- pass filename, default `accepted_pass.json`
- fail filename, default `rejected_fail.json`

Users may customize any filename. If `.json` is omitted, the backend appends it. Directory components are stripped, and filesystem-unsafe filename characters are replaced with `_`. Duplicate output filenames are an error and must prevent export.

Export creates exactly three JSON files:

1. Annotated all file: includes every input record, preserving original fields and adding `human_label`. Unlabeled records use `human_label: ""`.
2. Pass file: includes only records labeled `pass`, in the same format as the input JSON, without `human_label`.
3. Fail file: includes only records labeled `fail`, in the same format as the input JSON, without `human_label`.

The export operation should avoid partial results. Write outputs to temporary files in the export directory first, then replace the final files only after all three payloads are prepared successfully.

## Frontend Experience

The page removes prior confusion-matrix, metric, and report UI. The primary workspace includes:

- input JSON path and `Load / Resume`
- read-only progress sidecar path
- export directory and three export filename inputs
- summary stats: total, labeled, pass, fail, unlabeled
- pagination controls and jump-to-page
- dynamic page size control
- repeated sample groups

Each sample group shows:

- `cond_1` image
- `cond_2` image
- `file_name` image
- edit prompt
- file/path metadata
- `pass`, `fail`, and `clear` controls

The page size control defaults to `20` and supports common choices such as `10`, `20`, `50`, `100`, plus a custom value. Changing page size recalculates pagination while keeping the current sample in view when possible. The selected page size is saved in browser `localStorage`.

## Keyboard And Image Interactions

Keyboard shortcuts:

- Left arrow: previous page
- Right arrow: next page
- `A`: mark current sample `pass`
- `D`: mark current sample `fail`
- `C`: clear current sample label
- `+`: zoom images in
- `-`: zoom images out
- `0`: reset zoom

Global shortcuts are disabled while focus is inside an input or editable control.

The current sample is the clicked card, the hovered card, or the first card on the current page if no card has focus. After labeling, focus advances to the next unlabeled sample, crossing page boundaries when needed.

Retain image comparison behavior: clicking or pressing on the target image can temporarily show `cond_1`, then restore the target image on release/leave. Retain image zoom in/out/reset.

## API Design

Endpoints:

```text
GET  /
GET  /static/app.js
GET  /static/style.css
GET  /image?path=...
GET  /api/health
POST /api/load
POST /api/label
POST /api/export
```

`POST /api/load` accepts the input JSON path and returns items, labels, the progress sidecar path, and stats. It should auto-resume from the sidecar.

`POST /api/label` accepts a stable sample key and `human_label` value. It validates the value, updates server state, writes the sidecar atomically, and returns updated stats.

`POST /api/export` accepts export directory and three filenames. It validates paths and duplicate names, merges original records with sidecar labels, and writes the three output files.

## Error Handling

Errors should be specific and actionable:

- missing input JSON: show the exact path
- non-array JSON: explain that the input must be a JSON array
- malformed record: include record index and missing fields
- missing image: show an image-level placeholder, not a fatal load failure
- corrupt sidecar: preserve it with a `.corrupt-<timestamp>.json` suffix and continue with empty labels
- duplicate export filenames: reject before writing anything
- export directory permission failure: reject before partial final outputs are produced

## Verification

Add focused Python unit tests for:

- input JSON reading and validation
- stable sample key generation
- sidecar default path derivation
- sidecar merge behavior
- sidecar corrupt-file recovery
- pass/fail/clear label validation
- three-file export shape
- filename sanitization and duplicate detection

Manual browser verification should cover:

- loading the sample JSON
- showing all three images and prompt
- labeling with buttons and `A` / `D` / `C`
- left/right page shortcuts
- page-size changes
- image zoom and target/source comparison
- refresh/restart resume from sidecar
- custom export directory and filenames
- exported all/pass/fail JSON contents

## Out Of Scope

This redesign does not add multi-user locking, database storage, model metrics, confusion matrices, or copying image files during export. Exported JSON paths remain the original paths from the input records.
