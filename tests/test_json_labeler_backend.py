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
