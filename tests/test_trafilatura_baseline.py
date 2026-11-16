"""Tests for the external Trafilatura comparison protocol."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import trafilatura_baseline as baseline


ROOT = Path(__file__).resolve().parents[1]


class TrafilaturaBaselineHelpers(unittest.TestCase):
    def test_normalize_text_handles_unicode_whitespace_and_sphinx_marker(self):
        self.assertEqual(baseline.normalize_text("  标题\u00a0  A  B  ¶  "), "标题 A B")
        self.assertEqual(baseline.normalize_text("① 编号"), "1 编号")
        self.assertEqual(baseline.normalize_text(None), "")

    def test_ngram_scores_identity_disjoint_and_empty_inputs(self):
        self.assertEqual(baseline.ngram_scores("abcdef", "abcdef"), {
            "precision": 1.0, "recall": 1.0, "f1": 1.0,
        })
        self.assertEqual(baseline.ngram_scores("abcdef", "uvwxyz"), {
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
        })
        self.assertEqual(baseline.ngram_scores("", ""), {
            "precision": 1.0, "recall": 1.0, "f1": 1.0,
        })

    def test_reference_segments_drop_heading_and_list_markers(self):
        payload = {"title": "Title", "text": "Title\n- first\n2. second\nbody"}
        self.assertEqual(
            baseline.reference_segments(payload, "Title"),
            ["first", "second", "body"],
        )

    def test_manual_review_flag_is_not_an_accuracy_verdict(self):
        passed = {"char_ngram_precision": 0.95, "char_ngram_recall": 0.95, "char_ngram_f1": 0.95}
        review = {"char_ngram_precision": 0.70, "char_ngram_recall": 0.99, "char_ngram_f1": 0.82}
        self.assertFalse(baseline.needs_manual_review(passed))
        self.assertTrue(baseline.needs_manual_review(review))

    def test_call_trafilatura_rejects_empty_result(self):
        with mock.patch.object(baseline.trafilatura, "extract", return_value=None):
            with self.assertRaisesRegex(ValueError, "returned no result"):
                baseline.call_trafilatura(b"<html><body><p>Text</p></body></html>", None)

    def test_baseline_cli_writes_comparison_reports(self):
        source = ROOT / "samples" / "pydoc_appetite.html"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "version": 1,
                "group": "synthetic_cli_check",
                "scope": "One frozen local page used to exercise the baseline CLI.",
                "pages": [{
                    "id": "pydoc_appetite",
                    "path": str(source),
                    "template": "pydoc",
                    "url": "https://docs.python.org/zh-cn/3/tutorial/appetite.html",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "role": "test_only",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "comparison.json"
            report = root / "comparison.html"
            reference_dir = root / "reference"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(ROOT / "app.py"),
                    "baseline",
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                    "--reference-dir",
                    str(reference_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["compared"], 1)
            self.assertEqual(payload["summary"]["errors"], 0)
            self.assertEqual(payload["summary"]["review_count"], 0)
            self.assertTrue((reference_dir / "pydoc_appetite.json").exists())
            self.assertTrue(report.exists())
            self.assertTrue(report.with_suffix(".md").exists())


if __name__ == "__main__":
    unittest.main()
