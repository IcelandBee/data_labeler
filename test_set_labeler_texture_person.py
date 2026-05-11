import os
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from flask import Flask, request, jsonify, render_template_string, send_file
from PIL import Image

app = Flask(__name__)

STATE = {
    "src_dir": "",
    "ref_dir": "",
    "tgt_dir": "",
    "json_path": "",
    "items": [],
    "labels": {},
    "dims": ["groundtruth"],
    "page_size": 20,
}

VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

BASE_DIM = "groundtruth"
DEFAULT_EXPORT_FILENAME = "labeled_export.json"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
DIM_SPLIT_RE = re.compile(r"[\s,，;；]+")


def is_image_file(name: str) -> bool:
    return Path(name).suffix.lower() in VALID_EXTS


def safe_norm_path(p: str) -> str:
    return str(Path(p).resolve())


def get_file_name_from_path(p: str) -> str:
    return os.path.basename(p)


def read_json_records(json_path: str) -> List[Dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是 list")
    return data


def build_prompt_map(records: List[Dict]) -> Dict[str, str]:
    prompt_map = {}
    for rec in records:
        cond_1 = rec.get("cond_1", "")
        prompt = rec.get("prompt", "")
        if cond_1:
            prompt_map[get_file_name_from_path(cond_1)] = prompt
    return prompt_map


def list_common_images(src_dir: str, ref_dir: str, tgt_dir: str) -> List[str]:
    src_names = {p.name for p in Path(src_dir).iterdir() if p.is_file() and is_image_file(p.name)}
    ref_names = {p.name for p in Path(ref_dir).iterdir() if p.is_file() and is_image_file(p.name)}
    tgt_names = {p.name for p in Path(tgt_dir).iterdir() if p.is_file() and is_image_file(p.name)}
    return sorted(src_names & ref_names & tgt_names)


def get_image_size(image_path: str) -> Tuple[int, int]:
    with Image.open(image_path) as img:
        return img.size


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def copy_file(src: str, dst: str):
    shutil.copy2(src, dst)


def parse_label_dims(extra_dims_text: str) -> List[str]:
    dims = [BASE_DIM]
    seen = {BASE_DIM}

    for raw_dim in DIM_SPLIT_RE.split(extra_dims_text or ""):
        dim = raw_dim.strip()
        if not dim or dim in seen:
            continue
        dims.append(dim)
        seen.add(dim)

    return dims


def sanitize_export_filename(filename: str) -> str:
    name = os.path.basename((filename or "").strip())
    if not name:
        name = DEFAULT_EXPORT_FILENAME

    name = INVALID_FILENAME_CHARS.sub("_", name)
    if not name.lower().endswith(".json"):
        name += ".json"
    return name


def make_empty_label_record(dims: List[str] = None) -> Dict[str, str]:
    if dims is None:
        dims = STATE["dims"]

    record = {}
    for dim in dims:
        record[dim] = ""
        record[dim + "_reasoning"] = ""
    return record


def get_stats() -> Dict[str, int]:
    total = len(STATE["items"])

    stats = {
        "total": total,
    }

    for dim in STATE["dims"]:
        dim_total = sum(
            1 for v in STATE["labels"].values()
            if v.get(dim) in ("pass", "fail")
        )
        dim_pass = sum(
            1 for v in STATE["labels"].values()
            if v.get(dim) == "pass"
        )
        dim_fail = sum(
            1 for v in STATE["labels"].values()
            if v.get(dim) == "fail"
        )

        stats[dim + "_total"] = dim_total
        stats[dim + "_pass"] = dim_pass
        stats[dim + "_fail"] = dim_fail

    return stats


HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Multi-Dim Image Label Viewer</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background: #f7f7f7;
        }
        .top-panel {
            background: white;
            padding: 16px;
            border-radius: 10px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.08);
            margin-bottom: 16px;
        }
        .row {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
        .row input {
            flex: 1;
            min-width: 260px;
            padding: 8px;
        }
        button {
            padding: 8px 14px;
            cursor: pointer;
        }
        .stats {
            margin-top: 10px;
            font-size: 15px;
            font-weight: bold;
            line-height: 1.8;
        }
        .nav {
            margin-top: 10px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .group-card {
            background: white;
            border-radius: 12px;
            padding: 14px;
            margin-bottom: 18px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.08);
        }
        .img-row {
            display: flex;
            gap: 12px;
            align-items: flex-start;
            overflow-x: auto;
        }
        .img-box {
            width: 32%;
            min-width: 280px;
            text-align: center;
        }
        .img-box img {
            width: 100%;
            max-height: 360px;
            object-fit: contain;
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #fafafa;
            user-select: none;
            -webkit-user-drag: none;
        }
        .img-title {
            margin: 6px 0;
            font-weight: bold;
        }
        .meta {
            margin-top: 10px;
            font-size: 14px;
            color: #333;
            line-height: 1.6;
            word-break: break-all;
        }
        .dim-section {
            margin-top: 12px;
            padding: 10px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background: #fafafa;
        }
        .dim-title {
            font-weight: bold;
            margin-bottom: 8px;
            color: #222;
        }
        .label-buttons {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 6px;
        }
        .pass-active {
            background: #2ecc71;
            color: white;
            border: none;
        }
        .fail-active {
            background: #e74c3c;
            color: white;
            border: none;
        }
        .clear-btn {
            background: #f1f1f1;
            color: #222;
            border: 1px solid #bbb;
        }
        .normal-btn {
            background: #eee;
            border: 1px solid #ccc;
        }
        .reasoning-row {
            margin-top: 8px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .reasoning-input {
            flex: 1;
            padding: 6px 8px;
            border: 1px solid #ccc;
            border-radius: 6px;
            font-size: 13px;
        }
        .label-state {
            margin-top: 6px;
            font-size: 13px;
        }
        .label-pass {
            color: #27ae60;
        }
        .label-fail {
            color: #c0392b;
        }
        .label-none {
            color: #777;
        }
        .small-note {
            color: #666;
            font-size: 13px;
            margin-top: 6px;
        }
        .export-row {
            margin-top: 10px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .export-row input {
            flex: 1;
            min-width: 320px;
            padding: 8px;
        }
        .page-jump {
            width: 80px;
            padding: 6px;
        }
    </style>
</head>
<body>
    <div class="top-panel">
        <div class="row">
            <input id="src_dir" placeholder="src 文件夹路径">
            <input id="ref_dir" placeholder="ref 文件夹路径">
            <input id="tgt_dir" placeholder="tgt 文件夹路径">
            <input id="json_path" placeholder="json 路径">
            <button onclick="loadData()">加载</button>
        </div>

        <div class="row">
            <input id="extra_dims" placeholder="额外维度，留空则只标 groundtruth；多个维度可用逗号、空格或换行分隔">
        </div>

        <div class="stats" id="stats">
            总组数: 0 | groundtruth: pass 0 / fail 0 (已标 0)
        </div>

        <div class="nav">
            <button onclick="prevPage()">上一页</button>
            <span id="page_info">第 1 / 1 页</span>
            <button onclick="nextPage()">下一页</button>

            <span>跳转到</span>
            <input id="jump_page" class="page-jump" type="number" min="1" value="1">
            <button onclick="jumpPage()">跳转</button>
        </div>

        <div class="export-row">
            <input id="export_dir" placeholder="导出保存路径，例如 /DATA/public/data/xxx">
            <input id="export_filename" value="labeled_export.json" placeholder="导出 JSON 文件名，例如 labeled_export.json">
            <button onclick="exportLabeled()">导出已打标结果</button>
        </div>

        <div class="small-note">
            按住 tgt 图片时会临时显示 src，松开后恢复为 tgt。
        </div>
    </div>

    <div id="content"></div>

<script>
let currentPage = 1;
let totalPages = 1;
let items = [];
let labels = {};
let pageSize = 20;
let dims = ["groundtruth"];

function escapeHtml(text) {
    if (!text) return "";
    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function jsStringEscape(text) {
    if (!text) return "";
    return String(text)
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'")
        .replaceAll("\n", "\\n")
        .replaceAll("\r", "\\r");
}

function makeEmptyLabelRecord() {
    const record = {};
    for (const dim of dims) {
        record[dim] = "";
        record[dim + "_reasoning"] = "";
    }
    return record;
}

async function loadData() {
    const src_dir = document.getElementById("src_dir").value.trim();
    const ref_dir = document.getElementById("ref_dir").value.trim();
    const tgt_dir = document.getElementById("tgt_dir").value.trim();
    const json_path = document.getElementById("json_path").value.trim();
    const extra_dims = document.getElementById("extra_dims").value.trim();

    const resp = await fetch("/load", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({src_dir, ref_dir, tgt_dir, json_path, extra_dims})
    });

    const data = await resp.json();
    if (!data.ok) {
        alert(data.message);
        return;
    }

    items = data.items;
    labels = data.labels || {};
    dims = data.dims || ["groundtruth"];
    pageSize = data.page_size;
    currentPage = 1;
    totalPages = Math.max(1, Math.ceil(items.length / pageSize));

    renderPage();
    updateStats(data.stats);
}

function getCurrentStatsLocal() {
    const stats = {
        total: items.length
    };

    for (const dim of dims) {
        stats[dim + "_pass"] = 0;
        stats[dim + "_fail"] = 0;
        stats[dim + "_total"] = 0;
    }

    for (const k in labels) {
        for (const dim of dims) {
            if (labels[k][dim] === "pass") {
                stats[dim + "_pass"]++;
            } else if (labels[k][dim] === "fail") {
                stats[dim + "_fail"]++;
            }
        }
    }

    for (const dim of dims) {
        stats[dim + "_total"] = stats[dim + "_pass"] + stats[dim + "_fail"];
    }

    return stats;
}

function updateStats(stats) {
    if (!stats) stats = getCurrentStatsLocal();

    const statParts = ["总组数: " + stats.total];
    for (const dim of dims) {
        statParts.push(
            dim + ": pass " + (stats[dim + "_pass"] || 0) +
            " / fail " + (stats[dim + "_fail"] || 0) +
            " (已标 " + (stats[dim + "_total"] || 0) + ")"
        );
    }

    document.getElementById("stats").innerText = statParts.join(" | ");

    document.getElementById("page_info").innerText =
        "第 " + currentPage + " / " + totalPages + " 页";

    document.getElementById("jump_page").value = currentPage;
}

function imageUrl(path) {
    return "/image?path=" + encodeURIComponent(path);
}

function showSrcTemp(imgEl, srcPath) {
    imgEl.src = imageUrl(srcPath);
}

function restoreTgtTemp(imgEl, tgtPath) {
    imgEl.src = imageUrl(tgtPath);
}

async function setDimLabel(fileName, dim, value) {
    const resp = await fetch("/label", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({file_name: fileName, dim: dim, label: value})
    });

    const data = await resp.json();
    if (!data.ok) {
        alert(data.message);
        return;
    }

    if (!labels[fileName]) {
        labels[fileName] = makeEmptyLabelRecord();
    }

    if (value === "") {
        labels[fileName][dim] = "";
        labels[fileName][dim + "_reasoning"] = "";
    } else {
        labels[fileName][dim] = value;
    }

    renderPage();
    updateStats(data.stats);
}

async function setReasoning(fileName, dim, value) {
    if (!labels[fileName]) {
        labels[fileName] = makeEmptyLabelRecord();
    }

    labels[fileName][dim + "_reasoning"] = value;

    const resp = await fetch("/label", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            file_name: fileName,
            dim: dim,
            label: labels[fileName][dim],
            reasoning: value
        })
    });

    const data = await resp.json();
    if (!data.ok) {
        alert(data.message);
    }
}

async function clearDim(fileName, dim) {
    await setDimLabel(fileName, dim, "");
}

function getStateClass(value) {
    if (value === "pass") return "label-pass";
    if (value === "fail") return "label-fail";
    return "label-none";
}

function getStateText(value) {
    if (value === "pass") return "PASS";
    if (value === "fail") return "FAIL";
    return "未标";
}

function renderDimSection(fileName, dim, labelValue, reasoningValue) {
    const passClass = labelValue === "pass" ? "pass-active" : "normal-btn";
    const failClass = labelValue === "fail" ? "fail-active" : "normal-btn";

    const safeFileHtml = escapeHtml(fileName);
    const safeFileJs = jsStringEscape(fileName);
    const safeDimJs = jsStringEscape(dim);
    const safeDimHtml = escapeHtml(dim);
    const safeReasoning = escapeHtml(reasoningValue);

    return '' +
        '<div class="dim-section">' +
            '<div class="dim-title">' + safeDimHtml + '</div>' +
            '<div class="label-buttons">' +
                '<button class="' + passClass + '" onclick="setDimLabel(\'' + safeFileJs + '\', \'' + safeDimJs + '\', \'pass\')">pass</button>' +
                '<button class="' + failClass + '" onclick="setDimLabel(\'' + safeFileJs + '\', \'' + safeDimJs + '\', \'fail\')">fail</button>' +
                '<button class="clear-btn" onclick="clearDim(\'' + safeFileJs + '\', \'' + safeDimJs + '\')">clear</button>' +
            '</div>' +
            '<div class="reasoning-row">' +
                '<input type="text" class="reasoning-input" id="' + safeDimHtml + '_reasoning_' + safeFileHtml + '" placeholder="reasoning（fail 时填写原因）" value="' + safeReasoning + '" onchange="setReasoning(\'' + safeFileJs + '\', \'' + safeDimJs + '\', this.value)">' +
            '</div>' +
            '<div class="label-state ' + getStateClass(labelValue) + '">' + getStateText(labelValue) + '</div>' +
        '</div>';
}

function renderPage() {
    const content = document.getElementById("content");
    content.innerHTML = "";

    const start = (currentPage - 1) * pageSize;
    const end = Math.min(start + pageSize, items.length);
    const pageItems = items.slice(start, end);

    for (const item of pageItems) {
        const fileName = item.file_name;
        const labelData = labels[fileName] || {};

        const div = document.createElement("div");
        div.className = "group-card";

        const safeSrcPathJs = jsStringEscape(item.src_path);
        const safeTgtPathJs = jsStringEscape(item.tgt_path);

        let dimsHtml = "";
        for (const dim of dims) {
            const labelValue = labelData[dim] || "";
            const reasoningValue = labelData[dim + "_reasoning"] || "";
            dimsHtml += renderDimSection(fileName, dim, labelValue, reasoningValue);
        }

        div.innerHTML = '' +
            '<div class="img-row">' +
                '<div class="img-box"><div class="img-title">src</div><img src="' + imageUrl(item.src_path) + '" alt="src"></div>' +
                '<div class="img-box"><div class="img-title">ref</div><img src="' + imageUrl(item.ref_path) + '" alt="ref"></div>' +
                '<div class="img-box"><div class="img-title">tgt（按住查看 src）</div>' +
                    '<img src="' + imageUrl(item.tgt_path) + '" alt="tgt" style="cursor:pointer" ' +
                    'onmousedown="showSrcTemp(this, \'' + safeSrcPathJs + '\')" ' +
                    'onmouseup="restoreTgtTemp(this, \'' + safeTgtPathJs + '\')" ' +
                    'onmouseleave="restoreTgtTemp(this, \'' + safeTgtPathJs + '\')" ' +
                    'ontouchstart="showSrcTemp(this, \'' + safeSrcPathJs + '\')" ' +
                    'ontouchend="restoreTgtTemp(this, \'' + safeTgtPathJs + '\')" ' +
                    'ontouchcancel="restoreTgtTemp(this, \'' + safeTgtPathJs + '\')">' +
                '</div>' +
            '</div>' +
            '<div class="meta">' +
                '<div><b>文件名:</b> ' + escapeHtml(fileName) + '</div>' +
                '<div><b>Prompt:</b> ' + escapeHtml(item.prompt || "") + '</div>' +
            '</div>' +
            dimsHtml;

        content.appendChild(div);
    }

    updateStats();
}

function prevPage() {
    if (currentPage > 1) {
        currentPage--;
        renderPage();
    }
}

function nextPage() {
    if (currentPage < totalPages) {
        currentPage++;
        renderPage();
    }
}

function jumpPage() {
    const val = parseInt(document.getElementById("jump_page").value);
    if (!isNaN(val) && val >= 1 && val <= totalPages) {
        currentPage = val;
        renderPage();
    }
}

async function exportLabeled() {
    const export_dir = document.getElementById("export_dir").value.trim();
    const export_filename = document.getElementById("export_filename").value.trim();
    if (!export_dir) {
        alert("请先输入导出路径");
        return;
    }

    const resp = await fetch("/export", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({export_dir: export_dir, export_filename: export_filename})
    });

    const data = await resp.json();
    if (!data.ok) {
        alert(data.message);
        return;
    }

    alert(data.message);
}
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML)


@app.route("/image", methods=["GET"])
def serve_image():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return "Image not found", 404
    return send_file(path)


@app.route("/load", methods=["POST"])
def load_data():
    try:
        data = request.get_json(force=True)
        src_dir = data.get("src_dir", "").strip()
        ref_dir = data.get("ref_dir", "").strip()
        tgt_dir = data.get("tgt_dir", "").strip()
        json_path = data.get("json_path", "").strip()
        extra_dims = data.get("extra_dims", "").strip()

        if not all([src_dir, ref_dir, tgt_dir, json_path]):
            return jsonify(ok=False, message="请把 src/ref/tgt/json 路径都填完整")

        if not os.path.isdir(src_dir):
            return jsonify(ok=False, message="src 文件夹不存在: " + src_dir)
        if not os.path.isdir(ref_dir):
            return jsonify(ok=False, message="ref 文件夹不存在: " + ref_dir)
        if not os.path.isdir(tgt_dir):
            return jsonify(ok=False, message="tgt 文件夹不存在: " + tgt_dir)
        if not os.path.isfile(json_path):
            return jsonify(ok=False, message="json 文件不存在: " + json_path)

        src_dir = safe_norm_path(src_dir)
        ref_dir = safe_norm_path(ref_dir)
        tgt_dir = safe_norm_path(tgt_dir)
        json_path = safe_norm_path(json_path)

        records = read_json_records(json_path)
        prompt_map = build_prompt_map(records)
        common_names = list_common_images(src_dir, ref_dir, tgt_dir)

        items = []
        for name in common_names:
            items.append({
                "file_name": name,
                "src_path": os.path.join(src_dir, name),
                "ref_path": os.path.join(ref_dir, name),
                "tgt_path": os.path.join(tgt_dir, name),
                "prompt": prompt_map.get(name, ""),
            })

        STATE["src_dir"] = src_dir
        STATE["ref_dir"] = ref_dir
        STATE["tgt_dir"] = tgt_dir
        STATE["json_path"] = json_path
        STATE["items"] = items
        STATE["dims"] = parse_label_dims(extra_dims)
        STATE["labels"] = {}

        return jsonify(
            ok=True,
            items=items,
            labels=STATE["labels"],
            dims=STATE["dims"],
            page_size=STATE["page_size"],
            stats=get_stats(),
        )

    except Exception as e:
        return jsonify(ok=False, message="加载失败: " + str(e))


@app.route("/label", methods=["POST"])
def set_label_route():
    try:
        data = request.get_json(force=True)
        file_name = data.get("file_name", "").strip()
        dim = data.get("dim", "").strip()
        label = data.get("label", "")
        reasoning = data.get("reasoning", None)

        if not file_name:
            return jsonify(ok=False, message="file_name 为空")

        if dim not in STATE["dims"]:
            return jsonify(
                ok=False,
                message="dim 只能是: " + "、".join(STATE["dims"])
            )

        if file_name not in STATE["labels"]:
            STATE["labels"][file_name] = make_empty_label_record()

        if reasoning is not None:
            STATE["labels"][file_name][dim + "_reasoning"] = reasoning

        if label == "":
            if reasoning is None:
                STATE["labels"][file_name][dim] = ""
                STATE["labels"][file_name][dim + "_reasoning"] = ""
        elif label in ("pass", "fail"):
            STATE["labels"][file_name][dim] = label
        else:
            return jsonify(ok=False, message="label 只能是 pass、fail 或空字符串")

        return jsonify(ok=True, stats=get_stats())

    except Exception as e:
        return jsonify(ok=False, message="打标失败: " + str(e))


@app.route("/export", methods=["POST"])
def export_labeled():
    try:
        data = request.get_json(force=True)
        export_dir = data.get("export_dir", "").strip()
        export_filename = sanitize_export_filename(data.get("export_filename", ""))

        if not export_dir:
            return jsonify(ok=False, message="导出路径为空")

        if not STATE["items"]:
            return jsonify(ok=False, message="请先加载数据")

        export_dir = safe_norm_path(export_dir)
        gen_dir = os.path.join(export_dir, "gen")
        ref_dir_export = os.path.join(export_dir, "ref")
        tgt_dir = os.path.join(export_dir, "tgt")

        ensure_dir(export_dir)
        ensure_dir(gen_dir)
        ensure_dir(ref_dir_export)
        ensure_dir(tgt_dir)

        labeled_items = [x for x in STATE["items"] if x["file_name"] in STATE["labels"]]
        if not labeled_items:
            return jsonify(ok=False, message="当前没有已打标样本可导出")

        out_json = []
        for item in labeled_items:
            name = item["file_name"]
            src_path = item["src_path"]
            ref_path = item["ref_path"]
            tgt_path = item["tgt_path"]
            prompt = item.get("prompt", "")
            label_data = STATE["labels"][name]

            out_gen_path = os.path.join(gen_dir, name)
            out_ref_path = os.path.join(ref_dir_export, name)
            out_tgt_path = os.path.join(tgt_dir, name)

            copy_file(src_path, out_gen_path)
            copy_file(ref_path, out_ref_path)
            copy_file(tgt_path, out_tgt_path)

            width, height = get_image_size(out_tgt_path)

            out_record = {
                "file_name": out_tgt_path,
                "cond_1": out_gen_path,
                "cond_2": out_ref_path,
                "prompt": prompt,
                "width": width,
                "height": height,
            }

            for dim in STATE["dims"]:
                out_record[dim] = label_data.get(dim, "")
                out_record[dim + "_reasoning"] = label_data.get(dim + "_reasoning", "")

            out_json.append(out_record)

        json_save_path = os.path.join(export_dir, export_filename)
        with open(json_save_path, "w", encoding="utf-8") as f:
            json.dump(out_json, f, ensure_ascii=False, indent=2)

        return jsonify(
            ok=True,
            message="导出完成。\n已导出 " + str(len(out_json)) + " 组。\njson 保存为: " + json_save_path
        )

    except Exception as e:
        return jsonify(ok=False, message="导出失败: " + str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9001, debug=True)
