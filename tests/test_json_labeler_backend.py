import http.client
import json
import os
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from unittest import mock

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


def write_fake_image(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"fake image bytes")


def make_real_record(tmp, index=0):
    source = Path(tmp) / "source" / f"{index:05d}.jpg"
    reference = Path(tmp) / "reference" / f"{index:05d}.jpg"
    target = Path(tmp) / "original-target" / f"{index:05d}.jpg"
    for path in (source, reference, target):
        write_fake_image(path)
    return {
        "file_name": str(target),
        "cond_1": str(source),
        "cond_2": str(reference),
        "prompt": f"Prompt {index}",
        "width": 1024,
        "height": 768,
    }


class JsonLabelerBackendTests(unittest.TestCase):
    def setUp(self):
        server.STATE = {
            "input_json_path": "",
            "sidecar_path": "",
            "records": [],
            "sidecar": server.empty_sidecar(""),
        }
        server.SESSIONS = {server.DEFAULT_SESSION_ID: server.STATE}

    def request_handler(self, method, path, body=None, headers=None):
        class QuietHandler(server.Handler):
            def log_message(self, format, *args):
                pass

        httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
            try:
                conn.request(method, path, body=body, headers=headers or {})
                response = conn.getresponse()
                content = response.read()
                return response.status, response.getheaders(), content
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_sample_key_is_stable_and_order_independent(self):
        record = make_record(1)
        key_1 = server.make_sample_key(record)
        key_2 = server.make_sample_key(dict(reversed(list(record.items()))))
        changed_metadata = dict(record, prompt="Changed", width=512, height=512)
        key_3 = server.make_sample_key(changed_metadata)
        self.assertEqual(key_1, key_2)
        self.assertEqual(key_1, key_3)
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

    def test_parse_target_dirs_accepts_list_and_text(self):
        parsed = server.parse_target_dirs({
            "target_dirs": [" /a/model ", "", "/b/model"],
            "target_dirs_text": "/c/model\n/d/model;/e/model,/f/model",
        })

        self.assertEqual(parsed, [
            os.path.normpath("/a/model"),
            os.path.normpath("/b/model"),
            os.path.normpath("/c/model"),
            os.path.normpath("/d/model"),
            os.path.normpath("/e/model"),
            os.path.normpath("/f/model"),
        ])

    def test_parse_target_dirs_dedupes_preserving_order(self):
        parsed = server.parse_target_dirs({
            "target_dirs": ["/a", "/b", "/a"],
            "target_dirs_text": "/b\n/c",
        })

        self.assertEqual(parsed, [os.path.normpath("/a"), os.path.normpath("/b"), os.path.normpath("/c")])

    def test_expand_records_without_target_dirs_preserves_flat_records(self):
        records = [make_record(0), make_record(1)]

        groups = server.expand_records_to_groups(records, [])

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["index"], 0)
        self.assertEqual(groups[0]["basename"], "0.jpg")
        self.assertEqual(len(groups[0]["targets"]), 1)
        self.assertEqual(groups[0]["targets"][0]["file_name"], records[0]["file_name"])
        self.assertEqual(groups[0]["targets"][0]["record"], records[0])

    def test_expand_records_with_target_dirs_matches_by_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, 8)]
            model_a = Path(tmp) / "model-a"
            model_b = Path(tmp) / "model-b"
            write_fake_image(model_a / "00008.jpg")
            write_fake_image(model_b / "00008.jpg")

            groups = server.expand_records_to_groups(records, [str(model_a), str(model_b)])

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["basename"], "00008.jpg")
            self.assertEqual(groups[0]["missing_target_dirs"], [])
            self.assertEqual([Path(t["file_name"]).parent.name for t in groups[0]["targets"]], ["model-a", "model-b"])
            self.assertEqual([t["target_dir_name"] for t in groups[0]["targets"]], ["model-a", "model-b"])
            self.assertEqual([t["record"]["prompt"] for t in groups[0]["targets"]], ["Prompt 8", "Prompt 8"])

    def test_expand_records_indexes_each_target_directory_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, index) for index in (1, 2, 3)]
            model_a = Path(tmp) / "model-a"
            model_b = Path(tmp) / "model-b"
            for name in ("00001.jpg", "00002.jpg", "00003.jpg"):
                write_fake_image(model_a / name)
                write_fake_image(model_b / name)

            with mock.patch("os.scandir", wraps=os.scandir) as scandir:
                groups = server.expand_records_to_groups(records, [str(model_a), str(model_b)])

            self.assertEqual([len(group["targets"]) for group in groups], [2, 2, 2])
            self.assertEqual(
                [os.path.normpath(call.args[0]) for call in scandir.call_args_list],
                [os.path.normpath(str(model_a)), os.path.normpath(str(model_b))],
            )

    def test_expand_records_keeps_warning_group_when_no_target_matches_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, 8)]
            model_a = Path(tmp) / "model-a"
            model_a.mkdir()

            groups = server.expand_records_to_groups(records, [str(model_a)])

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["targets"], [])
            self.assertEqual(groups[0]["missing_target_dirs"], [str(model_a)])

    def test_build_items_preserves_records_and_adds_labels(self):
        records = [make_record(0), make_record(1)]
        key = server.make_sample_key(records[1])
        sidecar = {"labels": {key: {"human_label": "fail", "updated_at": "time"}}}
        items, labels = server.build_items(records, sidecar)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["prompt"], "Prompt 0")
        self.assertEqual(items[1]["sample_key"], key)
        self.assertEqual(labels[key]["human_label"], "fail")

    def test_build_items_emits_encoded_image_query_urls(self):
        record = make_record(0)
        record["file_name"] = r"C:\images\target file.jpg"

        items, _ = server.build_items([record], {"labels": {}})
        target_url = items[0]["target"]
        parsed = urlparse(target_url)

        self.assertEqual(parsed.path, "/image")
        self.assertFalse(target_url.startswith("/img/"))
        self.assertIn("path=", target_url)
        self.assertIn("%5C", target_url)
        self.assertIn("%20", target_url)
        self.assertEqual(unquote(parse_qs(parsed.query)["path"][0]), os.path.normpath(record["file_name"]))

    def test_build_items_turns_non_dict_records_into_actionable_items(self):
        items, labels = server.build_items(["not a record"], {"labels": {}})

        self.assertEqual(labels, {})
        self.assertEqual(items[0]["index"], 0)
        self.assertTrue(items[0]["sample_key"].startswith("invalid:0:"))
        self.assertIn("record", items[0]["image_errors"])
        self.assertIn("0", items[0]["image_errors"]["record"])

    def test_build_items_gives_non_dict_records_distinct_fallback_keys(self):
        items, _ = server.build_items(["not a record", "not a record"], {"labels": {}})

        self.assertNotEqual(items[0]["sample_key"], items[1]["sample_key"])

    def test_build_items_reports_missing_and_malformed_path_fields(self):
        records = [
            {"prompt": "missing required paths"},
            {"file_name": 123, "cond_1": None, "cond_2": ["bad"]},
        ]

        items, _ = server.build_items(records, {"labels": {}})

        self.assertEqual(items[0]["prompt"], "missing required paths")
        self.assertEqual(
            set(items[0]["image_errors"]),
            {"file_name", "cond_1", "cond_2"},
        )
        self.assertTrue({"file_name", "cond_1", "cond_2"}.issubset(items[1]["image_errors"]))

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

    def test_compute_stats_counts_duplicate_current_records_per_record(self):
        records = [make_record(0), make_record(0)]
        labels = {
            server.make_sample_key(records[0]): {"human_label": "pass"},
        }

        stats = server.compute_stats(records, labels)

        self.assertEqual(stats, {
            "total": 2,
            "pass": 2,
            "fail": 0,
            "labeled": 2,
            "unlabeled": 0,
        })

    def test_apply_label_accepts_pass_fail_and_clear(self):
        record = make_record(0)
        key = server.make_sample_key(record)
        labels = {}
        server.apply_label(labels, key, "pass", now="t1")
        self.assertEqual(labels[key], {"human_label": "pass", "updated_at": "t1"})
        server.apply_label(labels, key, "fail", now="t2")
        self.assertEqual(labels[key], {"human_label": "fail", "updated_at": "t2"})
        server.apply_label(labels, key, "", now="t3")
        self.assertEqual(labels[key], {"human_label": "", "updated_at": "t3"})
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

    def test_load_sidecar_propagates_oserror_without_renaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_path = Path(tmp) / "input.labels.json"
            sidecar_path.write_text('{"labels": {}}', encoding="utf-8")

            with mock.patch("builtins.open", side_effect=OSError("permission denied")):
                with self.assertRaises(OSError):
                    server.load_sidecar(str(sidecar_path))

            self.assertTrue(sidecar_path.exists())
            corrupt_files = list(Path(tmp).glob("input.labels.corrupt-*.json"))
            self.assertEqual(corrupt_files, [])

    def test_sidecar_load_accepts_groups_progress(self):
        sidecar = {
            "labels": {"sample": {"human_label": "pass", "updated_at": "t1"}},
            "groups": {"group": {"reviewed": True, "updated_at": "t2"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.labels.json"
            path.write_text(json.dumps(sidecar), encoding="utf-8")

            loaded = server.load_sidecar(str(path))

            self.assertEqual(loaded["labels"]["sample"]["human_label"], "pass")
            self.assertEqual(loaded["groups"]["group"], {"reviewed": True, "updated_at": "t2"})

    def test_apply_label_updates_group_progress(self):
        sidecar = server.empty_sidecar("")
        group_key = "group-1"
        sample_key = "sample-1"

        label = server.apply_label_to_sidecar(sidecar, sample_key, group_key, "pass", now="t1")

        self.assertEqual(label, {"human_label": "pass", "updated_at": "t1"})
        self.assertEqual(sidecar["groups"][group_key], {"reviewed": True, "updated_at": "t1"})

    def test_compute_group_stats_counts_groups_and_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, 1), make_real_record(tmp, 2)]
            model_a = Path(tmp) / "model-a"
            model_b = Path(tmp) / "model-b"
            for name in ("00001.jpg", "00002.jpg"):
                write_fake_image(model_a / name)
                write_fake_image(model_b / name)
            groups = server.expand_records_to_groups(records, [str(model_a), str(model_b)])
            first_target = groups[0]["targets"][0]
            labels = {first_target["sample_key"]: {"human_label": "pass"}}
            group_progress = {groups[0]["group_key"]: {"reviewed": True}}

            stats = server.compute_group_stats(groups, labels, group_progress)

            self.assertEqual(stats, {
                "groups_total": 2,
                "groups_reviewed": 1,
                "groups_unreviewed": 1,
                "targets_total": 4,
                "pass": 1,
                "fail": 0,
                "unlabeled_as_fail": 3,
            })

    def test_unreviewed_group_uses_group_progress_not_each_target_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, 1), make_real_record(tmp, 2)]
            model_a = Path(tmp) / "model-a"
            model_b = Path(tmp) / "model-b"
            for name in ("00001.jpg", "00002.jpg"):
                write_fake_image(model_a / name)
                write_fake_image(model_b / name)
            groups = server.expand_records_to_groups(records, [str(model_a), str(model_b)])
            group_progress = {groups[0]["group_key"]: {"reviewed": True}}

            result = server.unreviewed_group_at(groups, group_progress)

            self.assertEqual(result["group_key"], groups[1]["group_key"])
            self.assertEqual(result["index"], 1)

    def test_export_payloads_create_three_expected_json_arrays(self):
        records = [make_record(0), make_record(1), make_record(2)]
        labels = {
            server.make_sample_key(records[0]): {"human_label": "pass"},
            server.make_sample_key(records[1]): {"human_label": "fail"},
        }
        annotated, passed, failed = server.build_export_payloads(records, labels)
        self.assertEqual([x["human_label"] for x in annotated], ["pass", "fail"])
        self.assertNotIn("human_label", passed[0])
        self.assertNotIn("human_label", failed[0])
        self.assertEqual([x["prompt"] for x in passed], ["Prompt 0"])
        self.assertEqual([x["prompt"] for x in failed], ["Prompt 1"])

    def test_export_payloads_wrap_non_dict_records_in_annotated_payload(self):
        records = ["not a record"]
        items, _ = server.build_items(records, {"labels": {}})
        item_key = items[0]["sample_key"]
        labels = {item_key: {"human_label": "pass"}}

        annotated, passed, failed = server.build_export_payloads(records, labels)

        self.assertEqual(annotated, [{"_invalid_record": "not a record", "human_label": "pass"}])
        self.assertEqual(passed, ["not a record"])
        self.assertEqual(failed, [])

    def test_export_groups_treats_unlabeled_targets_as_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [make_real_record(tmp, 8)]
            model_a = Path(tmp) / "model-a"
            model_b = Path(tmp) / "model-b"
            write_fake_image(model_a / "00008.jpg")
            write_fake_image(model_b / "00008.jpg")
            groups = server.expand_records_to_groups(records, [str(model_a), str(model_b)])
            pass_key = groups[0]["targets"][0]["sample_key"]
            labels = {pass_key: {"human_label": "pass"}}

            annotated, passed, failed = server.build_export_payloads_from_groups(groups, labels)

            self.assertEqual([item["human_label"] for item in annotated], ["pass", "fail"])
            self.assertEqual(len(passed), 1)
            self.assertEqual(len(failed), 1)
            self.assertNotIn("human_label", passed[0])
            self.assertNotIn("human_label", failed[0])
            self.assertEqual(Path(passed[0]["file_name"]).parent.name, "model-a")
            self.assertEqual(Path(failed[0]["file_name"]).parent.name, "model-b")

    def test_api_load_reads_json_initializes_state_and_resumes_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            records = [make_record(0), make_record(1)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            sidecar_path = Path(server.default_sidecar_path(str(input_path)))
            key = server.make_sample_key(records[1])
            sidecar_path.write_text(
                json.dumps({
                    "source_file": str(input_path),
                    "labels": {key: {"human_label": "fail", "updated_at": "saved"}},
                }),
                encoding="utf-8",
            )

            result = server.api_load({"input_json_path": str(input_path)})

            self.assertTrue(result["success"])
            self.assertEqual(result["progress_path"], str(sidecar_path))
            self.assertNotIn("items", result)
            self.assertIn("group_progress", result)
            self.assertEqual(result["first_unreviewed_group"]["index"], 0)
            self.assertEqual(result["stats"], {
                "groups_total": 2,
                "groups_reviewed": 1,
                "groups_unreviewed": 1,
                "targets_total": 2,
                "pass": 0,
                "fail": 1,
                "unlabeled_as_fail": 1,
            })
            self.assertEqual(server.STATE["input_json_path"], os.path.normpath(str(input_path)))
            self.assertEqual(server.STATE["sidecar_path"], str(sidecar_path))
            self.assertEqual(server.STATE["records"], records)
            self.assertEqual(server.STATE["groups"][0]["targets"][0]["record"], records[0])

    def test_api_page_returns_only_requested_items_after_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            records = [make_record(0), make_record(1), make_record(2)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            server.api_load({"input_json_path": str(input_path)})

            result = server.api_page({"page": 2, "page_size": 1})

            self.assertTrue(result["success"])
            self.assertEqual(result["page"], 2)
            self.assertEqual(result["page_size"], 1)
            self.assertEqual(result["total_pages"], 3)
            self.assertEqual(len(result["groups"]), 1)
            self.assertEqual(result["groups"][0]["prompt"], "Prompt 1")
            self.assertEqual(len(result["groups"][0]["targets"]), 1)

    def test_api_label_updates_and_writes_sidecar_then_returns_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            records = [make_record(0), make_record(1)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            load_result = server.api_load({"input_json_path": str(input_path)})
            page_result = server.api_page({"page": 1, "page_size": 20})
            sample_key = page_result["groups"][0]["targets"][0]["sample_key"]

            result = server.api_label({"sample_key": sample_key, "human_label": "pass"})

            self.assertTrue(result["success"])
            self.assertEqual(result["label"]["human_label"], "pass")
            self.assertNotIn("next_unlabeled", result)
            self.assertEqual(result["stats"]["pass"], 1)
            self.assertEqual(result["stats"]["groups_reviewed"], 1)
            saved = json.loads(Path(load_result["progress_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["labels"][sample_key]["human_label"], "pass")
            self.assertTrue(saved["groups"][result["group_key"]]["reviewed"])

    def test_api_export_writes_sanitized_custom_files_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            export_dir = Path(tmp) / "exports"
            records = [make_record(0), make_record(1), make_record(2)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            server.api_load({"input_json_path": str(input_path)})
            page_result = server.api_page({"page": 1, "page_size": 20})
            server.api_label({"sample_key": page_result["groups"][0]["targets"][0]["sample_key"], "human_label": "pass"})
            server.api_label({"sample_key": page_result["groups"][1]["targets"][0]["sample_key"], "human_label": "fail"})

            result = server.api_export({
                "export_dir": str(export_dir),
                "annotated_filename": r"..\annotated:all",
                "pass_filename": "kept",
                "fail_filename": "bad|ones.json",
            })

            self.assertTrue(result["success"])
            self.assertEqual(result["counts"], {"annotated": 3, "pass": 1, "fail": 2})
            self.assertEqual(set(Path(path).name for path in result["paths"].values()), {
                "annotated_all.json",
                "kept.json",
                "bad_ones.json",
            })
            annotated = json.loads((export_dir / "annotated_all.json").read_text(encoding="utf-8"))
            passed = json.loads((export_dir / "kept.json").read_text(encoding="utf-8"))
            failed = json.loads((export_dir / "bad_ones.json").read_text(encoding="utf-8"))
            self.assertEqual([item["human_label"] for item in annotated], ["pass", "fail", "fail"])
            self.assertEqual([item["prompt"] for item in passed], ["Prompt 0"])
            self.assertEqual([item["prompt"] for item in failed], ["Prompt 1", "Prompt 2"])

    def test_api_sessions_keep_different_loaded_datasets_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_a = Path(tmp) / "input_a.json"
            input_b = Path(tmp) / "input_b.json"
            export_a = Path(tmp) / "export_a"
            export_b = Path(tmp) / "export_b"
            records_a = [make_record(0, "a")]
            records_b = [make_record(0, "b")]
            input_a.write_text(json.dumps(records_a), encoding="utf-8")
            input_b.write_text(json.dumps(records_b), encoding="utf-8")

            load_a = server.api_load({"session_id": "alice", "input_json_path": str(input_a)})
            load_b = server.api_load({"session_id": "bob", "input_json_path": str(input_b)})
            page_a = server.api_page({"session_id": "alice", "page": 1, "page_size": 20})
            page_b = server.api_page({"session_id": "bob", "page": 1, "page_size": 20})

            server.api_label({
                "session_id": "alice",
                "sample_key": page_a["groups"][0]["targets"][0]["sample_key"],
                "human_label": "pass",
            })
            server.api_label({
                "session_id": "bob",
                "sample_key": page_b["groups"][0]["targets"][0]["sample_key"],
                "human_label": "fail",
            })

            result_a = server.api_export({"session_id": "alice", "export_dir": str(export_a)})
            result_b = server.api_export({"session_id": "bob", "export_dir": str(export_b)})

            annotated_a = json.loads(Path(result_a["paths"]["annotated"]).read_text(encoding="utf-8"))
            annotated_b = json.loads(Path(result_b["paths"]["annotated"]).read_text(encoding="utf-8"))
            self.assertEqual(annotated_a[0]["prompt"], "Prompt 0")
            self.assertEqual(annotated_a[0]["human_label"], "pass")
            self.assertEqual(annotated_b[0]["prompt"], "Prompt 0")
            self.assertEqual(annotated_b[0]["human_label"], "fail")
            self.assertEqual(Path(result_a["paths"]["annotated"]).parent, export_a)
            self.assertEqual(Path(result_b["paths"]["annotated"]).parent, export_b)

    def test_api_export_stages_all_payloads_before_promoting_final_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            export_dir = Path(tmp) / "exports"
            records = [make_record(0), make_record(1)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            server.api_load({"input_json_path": str(input_path)})
            calls = 0
            real_dump = json.dump

            def fail_second_dump(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("staging failed")
                return real_dump(*args, **kwargs)

            with mock.patch("json.dump", side_effect=fail_second_dump):
                with self.assertRaises(OSError):
                    server.api_export({"export_dir": str(export_dir)})

            self.assertFalse((export_dir / server.DEFAULT_ANNOTATED_FILENAME).exists())
            self.assertFalse((export_dir / server.DEFAULT_PASS_FILENAME).exists())
            self.assertFalse((export_dir / server.DEFAULT_FAIL_FILENAME).exists())
            self.assertEqual(list(export_dir.glob("*.tmp")), [])
            self.assertEqual(list(export_dir.glob(".*.tmp")), [])

    def test_api_export_rolls_back_promoted_files_when_later_promotion_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            export_dir = Path(tmp) / "exports"
            export_dir.mkdir()
            records = [make_record(0), make_record(1)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            server.api_load({"input_json_path": str(input_path)})
            originals = {
                server.DEFAULT_ANNOTATED_FILENAME: [{"old": "annotated"}],
                server.DEFAULT_PASS_FILENAME: [{"old": "pass"}],
                server.DEFAULT_FAIL_FILENAME: [{"old": "fail"}],
            }
            for filename, payload in originals.items():
                (export_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

            calls = 0
            real_replace = os.replace

            def fail_second_promotion(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("promotion failed")
                return real_replace(src, dst)

            with mock.patch("os.replace", side_effect=fail_second_promotion):
                with self.assertRaises(OSError):
                    server.api_export({"export_dir": str(export_dir)})

            for filename, payload in originals.items():
                restored = json.loads((export_dir / filename).read_text(encoding="utf-8"))
                self.assertEqual(restored, payload)
            self.assertEqual(list(export_dir.glob("*.tmp")), [])
            self.assertEqual(list(export_dir.glob(".*.tmp")), [])
            self.assertEqual(list(export_dir.glob("*.bak")), [])
            self.assertEqual(list(export_dir.glob(".*.bak")), [])

    def test_api_export_preserves_backup_when_rollback_restore_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            export_dir = Path(tmp) / "exports"
            export_dir.mkdir()
            records = [make_record(0), make_record(1)]
            input_path.write_text(json.dumps(records), encoding="utf-8")
            server.api_load({"input_json_path": str(input_path)})
            for filename in (
                server.DEFAULT_ANNOTATED_FILENAME,
                server.DEFAULT_PASS_FILENAME,
                server.DEFAULT_FAIL_FILENAME,
            ):
                (export_dir / filename).write_text(json.dumps([{"old": filename}]), encoding="utf-8")

            calls = 0
            real_replace = os.replace

            def fail_promotion_then_restore(src, dst):
                nonlocal calls
                calls += 1
                if calls in (2, 3):
                    raise OSError("replace failed")
                return real_replace(src, dst)

            with mock.patch("os.replace", side_effect=fail_promotion_then_restore):
                with self.assertRaises(Exception) as raised:
                    server.api_export({"export_dir": str(export_dir)})

            backups = list(export_dir.glob(".*.bak"))
            self.assertTrue(backups)
            self.assertIn("backups preserved", str(raised.exception))
            self.assertTrue(any(path.read_text(encoding="utf-8") for path in backups))

    def test_http_handler_serves_task3_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "sample.bmp"
            image_path.write_bytes(b"BMminimal")

            status, headers, _ = self.request_handler("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", dict(headers).get("Content-Type", ""))

            status, headers, _ = self.request_handler("GET", "/static/app.js")
            self.assertEqual(status, 200)
            self.assertIn("javascript", dict(headers).get("Content-Type", ""))

            status, _, _ = self.request_handler("GET", "/static/missing.js")
            self.assertEqual(status, 404)

            status, _, _ = self.request_handler("GET", "/../server.py")
            self.assertNotEqual(status, 200)

            status, headers, _ = self.request_handler("GET", f"/image?path={quote(str(image_path), safe='')}")
            self.assertEqual(status, 200)
            self.assertEqual(dict(headers).get("Content-Type"), "image/bmp")

            status, _, _ = self.request_handler("GET", f"/image?path={quote(str(Path(tmp) / 'missing.bmp'), safe='')}")
            self.assertEqual(status, 404)

            status, headers, body = self.request_handler(
                "POST",
                "/api/unknown",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 404)
            self.assertIn("application/json", dict(headers).get("Content-Type", ""))
            self.assertFalse(json.loads(body.decode("utf-8"))["success"])

            status, headers, body = self.request_handler(
                "POST",
                "/api/load",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            self.assertNotEqual(status, 200)
            self.assertIn("application/json", dict(headers).get("Content-Type", ""))
            self.assertFalse(json.loads(body.decode("utf-8"))["success"])


if __name__ == "__main__":
    unittest.main()
