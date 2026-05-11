# JSON Labeler Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `json_labeler` into a reusable JSON triplet labeling tool with static frontend files, automatic sidecar resume, keyboard-driven pass/fail labeling, adjustable page size, image comparison/zoom, and three JSON exports.

**Architecture:** Keep `json_labeler/server.py` as a standard-library Python backend that serves static files, image bytes, and JSON APIs. Move browser UI into `json_labeler/index.html`, `json_labeler/static/app.js`, and `json_labeler/static/style.css`. Put data parsing, sidecar persistence, label updates, and export payload construction behind small testable helper functions before wiring them to HTTP handlers.

**Tech Stack:** Python standard library `http.server`, JSON files, browser JavaScript, CSS, Python `unittest`. Commands below use `python`; on this Windows machine that command currently points at the Microsoft Store alias, so before execution either install Python or replace `python` in commands with the exact interpreter that runs this project.

---

## File Structure

- Modify: `json_labeler/server.py`
  Backend HTTP server, static file serving, image serving, API routing, and pure helper functions for JSON records, sidecar labels, stats, and export payloads.
- Create: `json_labeler/index.html`
  Static document shell for the labeler UI.
- Create: `json_labeler/static/app.js`
  Frontend state, API calls, pagination, dynamic page size, keyboard shortcuts, label actions, image zoom, image comparison, and export form.
- Create: `json_labeler/static/style.css`
  Dense labeling workspace styles, responsive three-image layout, card states, controls, and error placeholders.
- Create: `tests/test_json_labeler_backend.py`
  Unit tests for backend helper behavior independent of the HTTP server.

## Task 1: Backend Helper Tests

**Files:**
- Create: `tests/test_json_labeler_backend.py`
- Modify: none

- [ ] **Step 1: Create the failing backend helper test file**

Create `tests/test_json_labeler_backend.py` with these tests:

```python
import json
import os
import tempfile
import unittest
from pathlib import Path

from json_labeler import server


def make_record(index=0, label_suffix=""):
    return {
        "file_name": f"/tmp/target/{index}{label_suffix}.jpg",
        "cond_1": f"/tmp/source/{index}{label_suffix}.jpg",
        "cond_2": f"/tmp/ref/{index}{label_suffix}.jpg",
        "prompt": f"Prompt {index}",
        "width": 1024,
        "height": 768,
    }


class JsonLabelerBackendTests(unittest.TestCase):
    def test_sample_key_is_stable_and_order_independent(self):
        record = make_record(1)
        key_1 = server.make_sample_key(record)
        key_2 = server.make_sample_key(dict(reversed(list(record.items()))))
        self.assertEqual(key_1, key_2)
        self.assertEqual(len(key_1), 40)

    def test_default_sidecar_path(self):
        self.assertEqual(
            server.default_sidecar_path(r"D:\data\input_data_file.json"),
            os.path.normpath(r"D:\data\input_data_file.labels.json"),
        )

    def test_sanitize_export_filename_strips_dirs_replaces_bad_chars_and_adds_json(self):
        self.assertEqual(
            server.sanitize_export_filename(r"..\bad:name"),
            "bad_name.json",
        )
        self.assertEqual(
            server.sanitize_export_filename("accepted_pass.json"),
            "accepted_pass.json",
        )

    def test_validate_export_filenames_rejects_duplicates_after_sanitizing(self):
        with self.assertRaises(ValueError):
            server.validate_export_filenames("same", "same.json", "other.json")

    def test_build_items_preserves_records_and_adds_labels(self):
        records = [make_record(0), make_record(1)]
        key = server.make_sample_key(records[1])
        sidecar = {"labels": {key: {"human_label": "fail", "updated_at": "time"}}}
        items, labels = server.build_items(records, sidecar)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["prompt"], "Prompt 0")
        self.assertEqual(items[1]["sample_key"], key)
        self.assertEqual(labels[key]["human_label"], "fail")

    def test_compute_stats_counts_pass_fail_and_unlabeled_current_records_only(self):
        records = [make_record(0), make_record(1), make_record(2)]
        labels = {
            server.make_sample_key(records[0]): {"human_label": "pass"},
            server.make_sample_key(records[1]): {"human_label": "fail"},
            "removed-record": {"human_label": "pass"},
        }
        stats = server.compute_stats(records, labels)
        self.assertEqual(stats, {
            "total": 3,
            "pass": 1,
            "fail": 1,
            "labeled": 2,
            "unlabeled": 1,
        })

    def test_apply_label_accepts_pass_fail_and_clear(self):
        record = make_record(0)
        key = server.make_sample_key(record)
        labels = {}
        server.apply_label(labels, key, "pass", now="t1")
        self.assertEqual(labels[key]["human_label"], "pass")
        server.apply_label(labels, key, "fail", now="t2")
        self.assertEqual(labels[key]["human_label"], "fail")
        server.apply_label(labels, key, "", now="t3")
        self.assertEqual(labels[key]["human_label"], "")
        with self.assertRaises(ValueError):
            server.apply_label(labels, key, "reject", now="t4")

    def test_load_sidecar_recovers_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_path = Path(tmp) / "input.labels.json"
            sidecar_path.write_text("{not valid json", encoding="utf-8")
            loaded = server.load_sidecar(str(sidecar_path))
            self.assertEqual(loaded["labels"], {})
            corrupt_files = list(Path(tmp).glob("input.labels.corrupt-*.json"))
            self.assertEqual(len(corrupt_files), 1)

    def test_export_payloads_create_three_expected_json_arrays(self):
        records = [make_record(0), make_record(1), make_record(2)]
        labels = {
            server.make_sample_key(records[0]): {"human_label": "pass"},
            server.make_sample_key(records[1]): {"human_label": "fail"},
        }
        annotated, passed, failed = server.build_export_payloads(records, labels)
        self.assertEqual([x["human_label"] for x in annotated], ["pass", "fail", ""])
        self.assertNotIn("human_label", passed[0])
        self.assertNotIn("human_label", failed[0])
        self.assertEqual([x["prompt"] for x in passed], ["Prompt 0"])
        self.assertEqual([x["prompt"] for x in failed], ["Prompt 1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_json_labeler_backend -v
```

Expected: FAIL with missing functions such as `make_sample_key`, `default_sidecar_path`, and `build_export_payloads`.

- [ ] **Step 3: Commit the failing tests**

Run:

```powershell
git add tests/test_json_labeler_backend.py
git commit -m "test: cover json labeler backend helpers"
```

Expected: commit succeeds and contains only the new test file.

## Task 2: Backend Data Helpers

**Files:**
- Modify: `json_labeler/server.py`
- Test: `tests/test_json_labeler_backend.py`

- [ ] **Step 1: Add constants and pure helper functions near the top of `server.py`**

Add this code after imports and before the `Handler` class:

```python
import copy
import hashlib
import re
import tempfile
from datetime import datetime, timezone

ALLOWED_LABELS = {"", "pass", "fail"}
DEFAULT_ANNOTATED_FILENAME = "annotated_all.json"
DEFAULT_PASS_FILENAME = "accepted_pass.json"
DEFAULT_FAIL_FILENAME = "rejected_fail.json"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\\\|?*\\x00-\\x1f]+')


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json_records(json_path):
    json_path = safe_path(json_path)
    if not json_path or not os.path.isfile(json_path):
        raise FileNotFoundError(f"Input JSON file does not exist: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Input JSON must be a JSON array")
    return data


def make_sample_key(record):
    parts = [
        str(record.get("file_name", "")),
        str(record.get("cond_1", "")),
        str(record.get("cond_2", "")),
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def default_sidecar_path(input_json_path):
    input_json_path = os.path.normpath(input_json_path)
    root, ext = os.path.splitext(input_json_path)
    if ext.lower() == ".json":
        return root + ".labels.json"
    return input_json_path + ".labels.json"


def sanitize_export_filename(name, default_name=None):
    name = (name or default_name or "").strip()
    name = os.path.basename(name.replace("\\", os.sep).replace("/", os.sep))
    name = INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    if not name:
        name = default_name or "export.json"
    if not name.lower().endswith(".json"):
        name += ".json"
    return name


def validate_export_filenames(annotated_name, pass_name, fail_name):
    names = [
        sanitize_export_filename(annotated_name, DEFAULT_ANNOTATED_FILENAME),
        sanitize_export_filename(pass_name, DEFAULT_PASS_FILENAME),
        sanitize_export_filename(fail_name, DEFAULT_FAIL_FILENAME),
    ]
    lowered = [name.lower() for name in names]
    if len(set(lowered)) != len(lowered):
        raise ValueError("Export filenames must be unique")
    return tuple(names)


def atomic_write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def empty_sidecar(source_file=""):
    source_mtime = os.path.getmtime(source_file) if source_file and os.path.exists(source_file) else None
    return {
        "source_file": source_file,
        "source_mtime": source_mtime,
        "updated_at": now_iso(),
        "labels": {},
    }


def load_sidecar(sidecar_path, source_file=""):
    if not os.path.exists(sidecar_path):
        return empty_sidecar(source_file)
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("labels", {}), dict):
            raise ValueError("Sidecar root must be an object with labels")
        data.setdefault("source_file", source_file)
        data.setdefault("source_mtime", os.path.getmtime(source_file) if source_file and os.path.exists(source_file) else None)
        data.setdefault("updated_at", now_iso())
        data.setdefault("labels", {})
        return data
    except Exception:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        root, ext = os.path.splitext(sidecar_path)
        corrupt_path = f"{root}.corrupt-{timestamp}{ext or '.json'}"
        os.replace(sidecar_path, corrupt_path)
        return empty_sidecar(source_file)


def save_sidecar(sidecar_path, sidecar):
    sidecar["updated_at"] = now_iso()
    atomic_write_json(sidecar_path, sidecar)


def normalize_record_for_item(record, index):
    item = copy.deepcopy(record)
    item["index"] = index
    item["sample_key"] = make_sample_key(record)
    item["source_path"] = safe_path(record.get("cond_1", ""))
    item["reference_path"] = safe_path(record.get("cond_2", ""))
    item["target_path"] = safe_path(record.get("file_name", ""))
    item["source"] = to_img_url(item["source_path"]) if item["source_path"] else None
    item["reference"] = to_img_url(item["reference_path"]) if item["reference_path"] else None
    item["target"] = to_img_url(item["target_path"]) if item["target_path"] else None
    item["image_errors"] = {}
    for field, path_value in (
        ("cond_1", item["source_path"]),
        ("cond_2", item["reference_path"]),
        ("file_name", item["target_path"]),
    ):
        if not is_valid_image_file(path_value):
            item["image_errors"][field] = f"Image not found or unsupported: {path_value}"
    return item


def build_items(records, sidecar):
    items = [normalize_record_for_item(record, idx) for idx, record in enumerate(records)]
    current_keys = {item["sample_key"] for item in items}
    raw_labels = sidecar.get("labels", {})
    labels = {
        key: {"human_label": value.get("human_label", ""), "updated_at": value.get("updated_at", "")}
        for key, value in raw_labels.items()
        if key in current_keys and isinstance(value, dict)
    }
    return items, labels


def compute_stats(records, labels):
    keys = {make_sample_key(record) for record in records}
    pass_count = 0
    fail_count = 0
    for key in keys:
        value = labels.get(key, {}).get("human_label", "")
        if value == "pass":
            pass_count += 1
        elif value == "fail":
            fail_count += 1
    labeled = pass_count + fail_count
    total = len(records)
    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "labeled": labeled,
        "unlabeled": total - labeled,
    }


def apply_label(labels, sample_key, human_label, now=None):
    if human_label not in ALLOWED_LABELS:
        raise ValueError("human_label must be pass, fail, or empty")
    labels[sample_key] = {
        "human_label": human_label,
        "updated_at": now or now_iso(),
    }


def build_export_payloads(records, labels):
    annotated = []
    passed = []
    failed = []
    for record in records:
        key = make_sample_key(record)
        label = labels.get(key, {}).get("human_label", "")
        annotated_record = copy.deepcopy(record)
        annotated_record["human_label"] = label
        annotated.append(annotated_record)
        if label == "pass":
            passed.append(copy.deepcopy(record))
        elif label == "fail":
            failed.append(copy.deepcopy(record))
    return annotated, passed, failed
```

- [ ] **Step 2: Run backend helper tests**

Run:

```powershell
python -m unittest tests.test_json_labeler_backend -v
```

Expected: PASS for helper tests. If `json_labeler` import fails because the directory is not treated as a namespace package, create an empty `json_labeler/__init__.py` and rerun.

- [ ] **Step 3: Commit the helper implementation**

Run:

```powershell
git add json_labeler/server.py json_labeler/__init__.py tests/test_json_labeler_backend.py
git commit -m "feat: add json labeler backend helpers"
```

Expected: commit succeeds. If `json_labeler/__init__.py` was not needed, omit it from `git add`.

## Task 3: Backend API And Static Serving

**Files:**
- Modify: `json_labeler/server.py`
- Create: `json_labeler/index.html`
- Create: `json_labeler/static/app.js`
- Create: `json_labeler/static/style.css`
- Test: `tests/test_json_labeler_backend.py`

- [ ] **Step 1: Replace old scan/export endpoints with JSON API state**

In `server.py`, add this global state after the helper functions from Task 2, before API functions and before `start_server`:

```python
STATE = {
    "input_json_path": "",
    "sidecar_path": "",
    "records": [],
    "sidecar": empty_sidecar(""),
}
```

Then update `Handler.handle_api` to route by method and path:

```python
def handle_api(self):
    from urllib.parse import urlparse

    parsed = urlparse(self.path)
    path = parsed.path
    try:
        if path == "/api/health" and self.command == "GET":
            self.write_json({"success": True, "status": "ok"})
        elif path == "/api/load" and self.command == "POST":
            self.write_json(api_load(self.read_json_body()))
        elif path == "/api/label" and self.command == "POST":
            self.write_json(api_label(self.read_json_body()))
        elif path == "/api/export" and self.command == "POST":
            self.write_json(api_export(self.read_json_body()))
        else:
            self.write_json({"success": False, "error": "Unknown endpoint"}, status=404)
    except Exception as e:
        import traceback
        self.write_json(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )
```

- [ ] **Step 2: Add request/response helpers to `Handler`**

Add these methods inside `Handler`:

```python
def do_POST(self):
    if self.path.startswith("/api/"):
        self.handle_api()
    else:
        self.send_error(404, "Not Found")


def read_json_body(self):
    length = int(self.headers.get("Content-Length", "0"))
    raw = self.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def write_json(self, payload, status=200):
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(content)))
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(content)
```

- [ ] **Step 3: Serve the new static frontend paths**

Update `do_GET` so `/` serves `index.html`, `/static/...` serves files under `json_labeler/static`, `/image?path=...` serves images, and `/api/...` still routes to `handle_api`:

```python
def do_GET(self):
    if self.path.startswith("/api/"):
        self.handle_api()
    elif self.path.startswith("/image"):
        self.serve_image_query()
    else:
        path = self.path.split("?", 1)[0].lstrip("/")
        if path == "":
            path = "index.html"
        if ".." in path:
            self.send_error(403, "Forbidden")
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, path)
        if os.path.isfile(filepath):
            self.serve_file(filepath)
        else:
            self.send_error(404, "Not Found")
```

Add image query serving:

```python
def serve_image_query(self):
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(self.path)
    img_path = parse_qs(parsed.query).get("path", [""])[0]
    self.serve_image_path(img_path)


def serve_image_path(self, img_path):
    img_path = safe_path(img_path)
    if not img_path or ".." in img_path:
        self.send_error(403, "Forbidden")
        return
    if not os.path.isfile(img_path):
        self.send_error(404, "Image not found")
        return
    ext = os.path.splitext(img_path)[1].lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    content_type = mime_types.get(ext, "application/octet-stream")
    with open(img_path, "rb") as f:
        content = f.read()
    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(content)))
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(content)
```

- [ ] **Step 4: Add API functions**

Add these functions below helper functions:

```python
def api_load(data):
    input_json_path = safe_path(data.get("input_json_path", ""))
    records = read_json_records(input_json_path)
    sidecar_path = default_sidecar_path(input_json_path)
    sidecar = load_sidecar(sidecar_path, input_json_path)
    items, labels = build_items(records, sidecar)
    STATE["input_json_path"] = input_json_path
    STATE["sidecar_path"] = sidecar_path
    STATE["records"] = records
    STATE["sidecar"] = sidecar
    return {
        "success": True,
        "items": items,
        "labels": labels,
        "progress_path": sidecar_path,
        "stats": compute_stats(records, sidecar.get("labels", {})),
    }


def api_label(data):
    sample_key = str(data.get("sample_key", "")).strip()
    human_label = data.get("human_label", "")
    if not sample_key:
        raise ValueError("sample_key is required")
    if not STATE["records"] or not STATE["sidecar_path"]:
        raise ValueError("Load an input JSON before labeling")
    valid_keys = {make_sample_key(record) for record in STATE["records"]}
    if sample_key not in valid_keys:
        raise ValueError("sample_key is not part of the loaded dataset")
    labels = STATE["sidecar"].setdefault("labels", {})
    apply_label(labels, sample_key, human_label)
    save_sidecar(STATE["sidecar_path"], STATE["sidecar"])
    return {
        "success": True,
        "labels": {sample_key: labels[sample_key]},
        "stats": compute_stats(STATE["records"], labels),
    }


def api_export(data):
    if not STATE["records"]:
        raise ValueError("Load an input JSON before exporting")
    export_dir = safe_path(data.get("export_dir", ""))
    if not export_dir:
        raise ValueError("export_dir is required")
    names = validate_export_filenames(
        data.get("annotated_filename", DEFAULT_ANNOTATED_FILENAME),
        data.get("pass_filename", DEFAULT_PASS_FILENAME),
        data.get("fail_filename", DEFAULT_FAIL_FILENAME),
    )
    os.makedirs(export_dir, exist_ok=True)
    annotated, passed, failed = build_export_payloads(
        STATE["records"], STATE["sidecar"].get("labels", {})
    )
    final_paths = [os.path.join(export_dir, name) for name in names]
    payloads = [annotated, passed, failed]
    temp_paths = []
    try:
        for final_path, payload in zip(final_paths, payloads):
            fd, temp_path = tempfile.mkstemp(
                prefix=".tmp-export-", suffix=".json", dir=export_dir
            )
            temp_paths.append(temp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        for temp_path, final_path in zip(temp_paths, final_paths):
            os.replace(temp_path, final_path)
        return {
            "success": True,
            "paths": {
                "annotated": final_paths[0],
                "pass": final_paths[1],
                "fail": final_paths[2],
            },
            "counts": {
                "annotated": len(annotated),
                "pass": len(passed),
                "fail": len(failed),
            },
        }
    except Exception:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        raise
```

- [ ] **Step 5: Add placeholder static files so the server can start**

Create `json_labeler/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JSON Labeler</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main id="app">JSON Labeler loading...</main>
  <script src="/static/app.js"></script>
</body>
</html>
```

Create `json_labeler/static/app.js`:

```javascript
document.getElementById("app").textContent = "JSON Labeler";
```

Create `json_labeler/static/style.css`:

```css
body {
  margin: 0;
  font-family: Arial, sans-serif;
}
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest tests.test_json_labeler_backend -v
```

Expected: PASS.

- [ ] **Step 7: Smoke test the server**

Run:

```powershell
python json_labeler/server.py -p 5000
```

Open `http://127.0.0.1:5000/` and verify it shows `JSON Labeler`. Stop the server with `Ctrl+C`.

- [ ] **Step 8: Commit API and static serving**

Run:

```powershell
git add json_labeler/server.py json_labeler/index.html json_labeler/static/app.js json_labeler/static/style.css tests/test_json_labeler_backend.py
git commit -m "feat: add json labeler api shell"
```

Expected: commit succeeds.

## Task 4: Frontend Layout And Data Loading

**Files:**
- Modify: `json_labeler/index.html`
- Modify: `json_labeler/static/app.js`
- Modify: `json_labeler/static/style.css`

- [ ] **Step 1: Replace `index.html` with the full layout shell**

Use:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JSON Labeler</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="toolbar">
    <section class="toolbar-section">
      <label>输入 JSON 路径</label>
      <div class="inline-row">
        <input id="inputJsonPath" type="text" placeholder="D:\data\input_data_file.json">
        <button id="loadBtn">加载/继续标注</button>
      </div>
      <div class="readonly-line">Sidecar: <span id="progressPath">未加载</span></div>
    </section>

    <section class="toolbar-section">
      <label>导出</label>
      <div class="export-grid">
        <input id="exportDir" type="text" placeholder="导出目录">
        <input id="annotatedFilename" type="text" value="annotated_all.json" aria-label="带标注全量文件名">
        <input id="passFilename" type="text" value="accepted_pass.json" aria-label="通过样本文件名">
        <input id="failFilename" type="text" value="rejected_fail.json" aria-label="失败样本文件名">
        <button id="exportBtn">导出三个 JSON</button>
      </div>
    </section>

    <section class="statusbar">
      <span id="statsText">总数 0 | 已标 0 | pass 0 | fail 0 | 未标 0</span>
      <span id="pageText">当前页 1 / 1</span>
      <label class="page-size-label">每页
        <input id="pageSizeInput" type="number" min="1" max="500" value="20">
      </label>
    </section>

    <section class="pager">
      <button id="prevBtn">上一页</button>
      <input id="pageJumpInput" type="number" min="1" value="1">
      <button id="jumpBtn">跳转</button>
      <button id="nextBtn">下一页</button>
    </section>
  </header>

  <main id="content" class="content"></main>
  <div id="toast" class="toast" hidden></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Add frontend state and API helpers to `app.js`**

Replace the placeholder script with:

```javascript
const state = {
  items: [],
  labels: {},
  stats: { total: 0, pass: 0, fail: 0, labeled: 0, unlabeled: 0 },
  currentPage: 1,
  pageSize: Number(localStorage.getItem("jsonLabelerPageSize") || "20"),
  selectedKey: "",
  hoverKey: "",
  zoom: 1,
};

const els = {};

function initElements() {
  for (const id of [
    "inputJsonPath", "loadBtn", "progressPath", "exportDir",
    "annotatedFilename", "passFilename", "failFilename", "exportBtn",
    "statsText", "pageText", "pageSizeInput", "prevBtn",
    "pageJumpInput", "jumpBtn", "nextBtn", "content", "toast"
  ]) {
    els[id] = document.getElementById(id);
  }
  els.pageSizeInput.value = String(state.pageSize);
}

async function postJson(url, payload) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!data.success) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 2600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
```

- [ ] **Step 3: Add load, stats, and pagination rendering**

Append:

```javascript
function totalPages() {
  return Math.max(1, Math.ceil(state.items.length / state.pageSize));
}

function clampPage() {
  state.currentPage = Math.min(Math.max(1, state.currentPage), totalPages());
}

function updateStats(stats = state.stats) {
  state.stats = stats;
  els.statsText.textContent =
    `总数 ${stats.total || 0} | 已标 ${stats.labeled || 0} | pass ${stats.pass || 0} | fail ${stats.fail || 0} | 未标 ${stats.unlabeled || 0}`;
  els.pageText.textContent = `当前页 ${state.currentPage} / ${totalPages()}`;
  els.pageJumpInput.value = String(state.currentPage);
}

function currentPageItems() {
  const start = (state.currentPage - 1) * state.pageSize;
  return state.items.slice(start, start + state.pageSize);
}

async function loadData() {
  const inputJsonPath = els.inputJsonPath.value.trim();
  if (!inputJsonPath) {
    showToast("请先输入 JSON 路径");
    return;
  }
  const data = await postJson("/api/load", { input_json_path: inputJsonPath });
  state.items = data.items || [];
  state.labels = data.labels || {};
  state.stats = data.stats || state.stats;
  state.currentPage = 1;
  state.selectedKey = firstUnlabeledKey() || (state.items[0] && state.items[0].sample_key) || "";
  if (state.selectedKey) {
    state.currentPage = pageForKey(state.selectedKey);
  }
  els.progressPath.textContent = data.progress_path || "未加载";
  render();
  showToast("数据已加载，已恢复 sidecar 标注");
}

function firstUnlabeledKey() {
  const item = state.items.find((candidate) => {
    const label = state.labels[candidate.sample_key]?.human_label || "";
    return label === "";
  });
  return item ? item.sample_key : "";
}

function pageForKey(sampleKey) {
  const index = state.items.findIndex((item) => item.sample_key === sampleKey);
  if (index < 0) return state.currentPage;
  return Math.floor(index / state.pageSize) + 1;
}
```

- [ ] **Step 4: Add sample card rendering with prompt and image placeholders**

Append:

```javascript
function imageBlock(title, path, url, error, extraClass = "") {
  if (error) {
    return `<div class="image-box ${extraClass}">
      <div class="image-title">${escapeHtml(title)}</div>
      <div class="image-error">${escapeHtml(error)}</div>
    </div>`;
  }
  return `<div class="image-box ${extraClass}">
    <div class="image-title">${escapeHtml(title)}</div>
    <img src="${escapeHtml(url)}" alt="${escapeHtml(title)}" data-original="${escapeHtml(url)}" data-source-path="${escapeHtml(path || "")}">
  </div>`;
}

function renderCard(item) {
  const key = item.sample_key;
  const label = state.labels[key]?.human_label || "";
  const selected = key === state.selectedKey ? " selected" : "";
  const labelClass = label ? ` label-${label}` : "";
  return `<article class="sample-card${selected}${labelClass}" data-key="${escapeHtml(key)}">
    <div class="card-header">
      <strong>#${item.index + 1}</strong>
      <span>${escapeHtml(item.file_name || item.target_path || "")}</span>
      <span class="label-pill">${escapeHtml(label || "未标")}</span>
    </div>
    <div class="image-row" style="--zoom:${state.zoom}">
      ${imageBlock("cond_1", item.source_path, item.source, item.image_errors?.cond_1)}
      ${imageBlock("cond_2", item.reference_path, item.reference, item.image_errors?.cond_2)}
      ${imageBlock("file_name", item.target_path, item.target, item.image_errors?.file_name, "target-image")}
    </div>
    <div class="prompt"><b>Prompt:</b> ${escapeHtml(item.prompt || "")}</div>
    <div class="actions">
      <button data-action="label" data-label="pass" data-key="${escapeHtml(key)}">pass</button>
      <button data-action="label" data-label="fail" data-key="${escapeHtml(key)}">fail</button>
      <button data-action="label" data-label="" data-key="${escapeHtml(key)}">clear</button>
    </div>
  </article>`;
}

function render() {
  clampPage();
  els.content.innerHTML = currentPageItems().map(renderCard).join("");
  updateStats();
}
```

- [ ] **Step 5: Add basic pagination and event binding**

Append:

```javascript
function prevPage() {
  if (state.currentPage > 1) {
    state.currentPage -= 1;
    state.selectedKey = (currentPageItems()[0] && currentPageItems()[0].sample_key) || "";
    render();
  }
}

function nextPage() {
  if (state.currentPage < totalPages()) {
    state.currentPage += 1;
    state.selectedKey = (currentPageItems()[0] && currentPageItems()[0].sample_key) || "";
    render();
  }
}

function jumpPage() {
  const value = Number(els.pageJumpInput.value);
  if (Number.isFinite(value)) {
    state.currentPage = Math.min(Math.max(1, Math.floor(value)), totalPages());
    state.selectedKey = (currentPageItems()[0] && currentPageItems()[0].sample_key) || "";
    render();
  }
}

function changePageSize() {
  const previousKey = state.selectedKey || (currentPageItems()[0] && currentPageItems()[0].sample_key) || "";
  const value = Number(els.pageSizeInput.value);
  if (!Number.isFinite(value) || value < 1) {
    els.pageSizeInput.value = String(state.pageSize);
    return;
  }
  state.pageSize = Math.min(500, Math.floor(value));
  localStorage.setItem("jsonLabelerPageSize", String(state.pageSize));
  if (previousKey) {
    state.currentPage = pageForKey(previousKey);
    state.selectedKey = previousKey;
  }
  render();
}

function bindEvents() {
  els.loadBtn.addEventListener("click", () => loadData().catch((err) => showToast(err.message)));
  els.prevBtn.addEventListener("click", prevPage);
  els.nextBtn.addEventListener("click", nextPage);
  els.jumpBtn.addEventListener("click", jumpPage);
  els.pageSizeInput.addEventListener("change", changePageSize);
  els.content.addEventListener("click", onContentClick);
  els.content.addEventListener("mouseover", onContentHover);
  els.content.addEventListener("mouseout", onContentLeave);
}

function onContentClick(event) {
  const card = event.target.closest(".sample-card");
  if (card) state.selectedKey = card.dataset.key;
  const button = event.target.closest("button[data-action='label']");
  if (button) {
    showToast("标注功能将在下一步启用");
  } else {
    render();
  }
}

function onContentHover(event) {
  const card = event.target.closest(".sample-card");
  if (card) state.hoverKey = card.dataset.key;
}

function onContentLeave(event) {
  if (!event.relatedTarget || !els.content.contains(event.relatedTarget)) {
    state.hoverKey = "";
  }
}

initElements();
bindEvents();
render();
```

- [ ] **Step 6: Add initial CSS for layout**

Replace `style.css` with:

```css
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #f5f6f8;
  color: #20242a;
  font-family: Arial, "Microsoft YaHei", sans-serif;
}

.toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: grid;
  gap: 10px;
  padding: 12px 16px;
  background: #ffffff;
  border-bottom: 1px solid #d9dee7;
}

.toolbar-section {
  display: grid;
  gap: 6px;
}

label {
  font-size: 13px;
  font-weight: 700;
}

.inline-row,
.pager {
  display: flex;
  gap: 8px;
  align-items: center;
}

input {
  min-height: 34px;
  padding: 7px 9px;
  border: 1px solid #b8c0cc;
  border-radius: 4px;
  font-size: 14px;
}

button {
  min-height: 34px;
  padding: 7px 12px;
  border: 1px solid #9099a8;
  border-radius: 4px;
  background: #ffffff;
  cursor: pointer;
}

button:hover {
  background: #eef3f8;
}

#inputJsonPath,
#exportDir {
  flex: 1;
}

.export-grid {
  display: grid;
  grid-template-columns: minmax(240px, 1.4fr) repeat(3, minmax(150px, 1fr)) auto;
  gap: 8px;
}

.readonly-line,
.statusbar {
  color: #53606f;
  font-size: 13px;
}

.statusbar {
  display: flex;
  gap: 18px;
  align-items: center;
  flex-wrap: wrap;
}

.page-size-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

#pageSizeInput,
#pageJumpInput {
  width: 86px;
}

.content {
  display: grid;
  gap: 14px;
  padding: 16px;
}

.sample-card {
  border: 2px solid #d5dbe4;
  border-radius: 6px;
  background: #ffffff;
  padding: 12px;
}

.sample-card.selected {
  border-color: #3267d6;
}

.card-header {
  display: flex;
  gap: 10px;
  align-items: center;
  overflow-wrap: anywhere;
}

.label-pill {
  margin-left: auto;
  padding: 3px 8px;
  border-radius: 999px;
  background: #e8ebef;
  font-size: 12px;
}

.label-pass .label-pill {
  background: #d9f2df;
  color: #156c2f;
}

.label-fail .label-pill {
  background: #fde0df;
  color: #9d1f1a;
}

.image-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.image-box {
  min-height: 180px;
  border: 1px solid #d5dbe4;
  border-radius: 6px;
  background: #f8fafc;
  overflow: auto;
}

.image-title {
  padding: 6px 8px;
  color: #53606f;
  font-size: 12px;
  border-bottom: 1px solid #d5dbe4;
}

.image-box img {
  display: block;
  width: calc(100% * var(--zoom));
  max-width: none;
}

.image-error {
  padding: 18px;
  color: #9d1f1a;
  overflow-wrap: anywhere;
}

.prompt {
  margin-top: 10px;
  line-height: 1.45;
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.toast {
  position: fixed;
  right: 16px;
  bottom: 16px;
  max-width: 520px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #20242a;
  color: #ffffff;
}

@media (max-width: 900px) {
  .export-grid,
  .image-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 7: Run server and manually load the sample JSON**

Run:

```powershell
python json_labeler/server.py -p 5000
```

Open `http://127.0.0.1:5000/`, enter:

```text
D:\Project\data_labeler\json_labeler\input_data_file.json
```

Expected: the page loads records, shows prompt text, displays image placeholders if the sample image paths do not exist locally, and shows the sidecar path.

- [ ] **Step 8: Commit frontend load UI**

Run:

```powershell
git add json_labeler/index.html json_labeler/static/app.js json_labeler/static/style.css
git commit -m "feat: add json labeler loading ui"
```

Expected: commit succeeds.

## Task 5: Frontend Labeling, Pagination, Export, Zoom, And Shortcuts

**Files:**
- Modify: `json_labeler/static/app.js`
- Modify: `json_labeler/static/style.css`

- [ ] **Step 1: Add label mutation and focus advancement to `app.js`**

Append:

```javascript
function activeKey() {
  return state.hoverKey || state.selectedKey || (currentPageItems()[0] && currentPageItems()[0].sample_key) || "";
}

async function setLabel(sampleKey, humanLabel) {
  if (!sampleKey) return;
  const data = await postJson("/api/label", {
    sample_key: sampleKey,
    human_label: humanLabel,
  });
  state.labels[sampleKey] = data.labels[sampleKey];
  state.stats = data.stats;
  if (humanLabel) {
    advanceAfterLabel(sampleKey);
  } else {
    state.selectedKey = sampleKey;
  }
  render();
}

function advanceAfterLabel(sampleKey) {
  const start = Math.max(0, state.items.findIndex((item) => item.sample_key === sampleKey));
  for (let offset = 1; offset <= state.items.length; offset += 1) {
    const index = (start + offset) % state.items.length;
    const item = state.items[index];
    const label = state.labels[item.sample_key]?.human_label || "";
    if (!label) {
      state.selectedKey = item.sample_key;
      state.currentPage = pageForKey(item.sample_key);
      return;
    }
  }
  state.selectedKey = sampleKey;
}
```

- [ ] **Step 2: Extend event binding for export, image comparison, and keyboard shortcuts**

Replace `bindEvents` in `app.js` with this version:

```javascript
function bindEvents() {
  els.loadBtn.addEventListener("click", () => loadData().catch((err) => showToast(err.message)));
  els.prevBtn.addEventListener("click", prevPage);
  els.nextBtn.addEventListener("click", nextPage);
  els.jumpBtn.addEventListener("click", jumpPage);
  els.pageSizeInput.addEventListener("change", changePageSize);
  els.exportBtn.addEventListener("click", () => exportData().catch((err) => showToast(err.message)));
  els.content.addEventListener("click", onContentClick);
  els.content.addEventListener("mouseover", onContentHover);
  els.content.addEventListener("mouseout", onContentLeave);
  els.content.addEventListener("mousedown", onImageCompareStart);
  els.content.addEventListener("mouseup", onImageCompareEnd);
  els.content.addEventListener("mouseleave", onImageCompareEnd);
  document.addEventListener("keydown", onKeyDown);
}
```

- [ ] **Step 3: Update content click handling to save labels**

Replace `onContentClick` with:

```javascript
function onContentClick(event) {
  const card = event.target.closest(".sample-card");
  if (card) state.selectedKey = card.dataset.key;
  const button = event.target.closest("button[data-action='label']");
  if (button) {
    setLabel(button.dataset.key, button.dataset.label).catch((err) => showToast(err.message));
  } else {
    render();
  }
}
```

- [ ] **Step 4: Add export function**

Append:

```javascript
async function exportData() {
  const exportDir = els.exportDir.value.trim();
  if (!exportDir) {
    showToast("请先输入导出目录");
    return;
  }
  const data = await postJson("/api/export", {
    export_dir: exportDir,
    annotated_filename: els.annotatedFilename.value.trim(),
    pass_filename: els.passFilename.value.trim(),
    fail_filename: els.failFilename.value.trim(),
  });
  showToast(`导出完成: all ${data.counts.annotated}, pass ${data.counts.pass}, fail ${data.counts.fail}`);
}
```

- [ ] **Step 5: Add image comparison and zoom behavior**

Append:

```javascript
function onImageCompareStart(event) {
  const box = event.target.closest(".target-image");
  if (!box) return;
  const card = event.target.closest(".sample-card");
  const item = state.items.find((candidate) => candidate.sample_key === card?.dataset.key);
  const img = box.querySelector("img");
  if (img && item?.source) {
    img.dataset.target = img.src;
    img.src = item.source;
  }
}

function onImageCompareEnd(event) {
  const imgs = els.content.querySelectorAll(".target-image img[data-target]");
  imgs.forEach((img) => {
    img.src = img.dataset.target;
    delete img.dataset.target;
  });
}

function zoomBy(delta) {
  state.zoom = Math.min(3, Math.max(0.5, Number((state.zoom + delta).toFixed(2))));
  render();
}

function resetZoom() {
  state.zoom = 1;
  render();
}
```

- [ ] **Step 6: Add keyboard shortcuts**

Append:

```javascript
function isEditingText(event) {
  const target = event.target;
  return target && (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.isContentEditable
  );
}

function onKeyDown(event) {
  if (isEditingText(event)) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    prevPage();
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    nextPage();
  } else if (event.key.toLowerCase() === "a") {
    event.preventDefault();
    setLabel(activeKey(), "pass").catch((err) => showToast(err.message));
  } else if (event.key.toLowerCase() === "d") {
    event.preventDefault();
    setLabel(activeKey(), "fail").catch((err) => showToast(err.message));
  } else if (event.key.toLowerCase() === "c") {
    event.preventDefault();
    setLabel(activeKey(), "").catch((err) => showToast(err.message));
  } else if (event.key === "+" || event.key === "=") {
    event.preventDefault();
    zoomBy(0.1);
  } else if (event.key === "-") {
    event.preventDefault();
    zoomBy(-0.1);
  } else if (event.key === "0") {
    event.preventDefault();
    resetZoom();
  }
}
```

- [ ] **Step 7: Improve button state styles**

Add to `style.css`:

```css
.actions button[data-label="pass"] {
  border-color: #49a463;
}

.actions button[data-label="fail"] {
  border-color: #d75b54;
}

.sample-card.label-pass {
  border-left-color: #49a463;
}

.sample-card.label-fail {
  border-left-color: #d75b54;
}
```

- [ ] **Step 8: Manual verification**

Run:

```powershell
python json_labeler/server.py -p 5000
```

Open `http://127.0.0.1:5000/`, load the sample JSON, then verify:

- `A` labels current sample as `pass`
- `D` labels current sample as `fail`
- `C` clears the current sample
- sidecar file appears beside `input_data_file.json`
- refresh and reload restore labels
- left and right arrows change pages
- changing page size recalculates pages and persists after refresh
- `+`, `-`, and `0` change image zoom
- target image mousedown temporarily shows `cond_1`
- export writes the three requested JSON files to a chosen directory

- [ ] **Step 9: Commit completed frontend interactions**

Run:

```powershell
git add json_labeler/static/app.js json_labeler/static/style.css
git commit -m "feat: add json labeler interactions"
```

Expected: commit succeeds.

## Task 6: Final Verification And Cleanup

**Files:**
- Modify only if verification exposes bugs.

- [ ] **Step 1: Run all unit tests**

Run:

```powershell
python -m unittest discover -v
```

Expected: all tests pass, including `tests.test_json_labeler_backend`.

- [ ] **Step 2: Run server smoke test**

Run:

```powershell
python json_labeler/server.py -p 5000
```

Expected: the server starts and prints a local URL. Open it and repeat the manual checklist from Task 5 Step 7.

- [ ] **Step 3: Inspect generated sidecar/export artifacts**

If the manual test created sample progress or export files inside the repo, inspect them. Keep intentional examples only if useful; otherwise remove generated artifacts with targeted `Remove-Item -LiteralPath <path>` after confirming they are generated test output.

- [ ] **Step 4: Check git status**

Run:

```powershell
git status --short
```

Expected: only intentional source/test files are modified or untracked. `.superpowers/` remains untracked unless the user explicitly asks to keep brainstorming artifacts.

- [ ] **Step 5: Commit final fixes if any**

If verification required fixes, commit them:

```powershell
git add json_labeler tests
git commit -m "fix: polish json labeler verification issues"
```

Expected: commit succeeds or no commit is needed because no final fixes were made.
