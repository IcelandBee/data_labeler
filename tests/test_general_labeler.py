import unittest

from test_set_labeler_texture_person import (
    DEFAULT_EXPORT_FILENAME,
    make_empty_label_record,
    parse_label_dims,
    sanitize_export_filename,
)


class GeneralLabelerConfigTest(unittest.TestCase):
    def test_empty_extra_dims_keeps_only_groundtruth(self):
        self.assertEqual(parse_label_dims(""), ["groundtruth"])

    def test_extra_dims_are_split_deduped_and_keep_order(self):
        dims = parse_label_dims(
            "quality, style；groundtruth\nquality texture_consistency"
        )

        self.assertEqual(
            dims,
            ["groundtruth", "quality", "style", "texture_consistency"],
        )

    def test_empty_label_record_uses_dynamic_dims(self):
        record = make_empty_label_record(["groundtruth", "quality"])

        self.assertEqual(
            record,
            {
                "groundtruth": "",
                "groundtruth_reasoning": "",
                "quality": "",
                "quality_reasoning": "",
            },
        )

    def test_export_filename_defaults_and_adds_json_suffix(self):
        self.assertEqual(sanitize_export_filename(""), DEFAULT_EXPORT_FILENAME)
        self.assertEqual(sanitize_export_filename("task_a"), "task_a.json")

    def test_export_filename_is_basename_and_filesystem_safe(self):
        self.assertEqual(
            sanitize_export_filename("../bad:name?.json"),
            "bad_name_.json",
        )


if __name__ == "__main__":
    unittest.main()
