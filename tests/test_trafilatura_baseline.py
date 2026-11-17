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

    def test_block_similarity_ignores_markdown_pipe_and_whitespace(self):
        reference = "| September 2004 Remember the essays you had to write"
        candidate = "September 2004 Remember the essays you had to write"
        self.assertGreaterEqual(baseline.block_similarity(reference, candidate), baseline.BLOCK_MATCH_THRESHOLD)
        self.assertEqual(baseline.block_similarity(">>> 2 + 2 4 >>> 50 - 5*6 20", ">>> 2 + 2 4 >>> 50 - 5*6 20"), 1.0)

    def test_segment_alignment_counts_small_string_difference_as_approximate_match(self):
        alignment = baseline.segment_alignment(
            ["What an essay real"],
            ["What an essay really"],
        )
        self.assertEqual(alignment["exact_block_matches"], 0)
        self.assertEqual(alignment["approximate_block_matches"], 2)
        self.assertEqual(alignment["approximate_reference_blocks"], 1)
        self.assertEqual(alignment["approximate_candidate_blocks"], 1)
        self.assertEqual(alignment["unmatched_reference"], 0)
        self.assertEqual(alignment["unmatched_candidate"], 0)
        self.assertGreaterEqual(alignment["block_f1"], baseline.BLOCK_MATCH_THRESHOLD)
        self.assertLessEqual(alignment["block_f1"], 1.0)
        self.assertEqual(alignment["reference_only"], [])
        self.assertEqual(alignment["candidate_only"], [])

    def test_segment_alignment_keeps_real_content_difference_unmatched(self):
        alignment = baseline.segment_alignment(
            ["东西问精选: 2026年11月03日 15:05:01"],
            ["2026年7月20日,上海,参观者。中新社发 陈玉宇 摄"],
        )
        self.assertEqual(alignment["approximate_block_matches"], 0)
        self.assertEqual(alignment["unmatched_reference"], 1)
        self.assertEqual(alignment["unmatched_candidate"], 1)
        self.assertEqual(alignment["block_f1"], 0.0)
        self.assertEqual(len(alignment["reference_only"]), 1)
        self.assertEqual(len(alignment["candidate_only"]), 1)

    def test_segment_alignment_threshold_is_inclusive(self):
        left = "abcdefghij"
        right = "abcdefghik"
        self.assertEqual(round(baseline.block_similarity(left, right), 4), 0.9)
        boundary = baseline.segment_alignment([left], [right])
        self.assertEqual(boundary["approximate_block_matches"], 2)
        self.assertEqual(boundary["unmatched_reference"], 0)

    def test_segment_alignment_allows_one_long_reference_to_cover_many_blocks(self):
        reference = ["alpha beta gamma delta epsilon zeta eta theta iota kappa"]
        candidate = ["alpha beta", "gamma delta", "epsilon zeta", "eta theta iota kappa"]
        alignment = baseline.segment_alignment(reference, candidate)
        self.assertEqual(alignment["unmatched_reference"], 0)
        self.assertEqual(alignment["unmatched_candidate"], 0)
        self.assertEqual(alignment["block_precision"], 1.0)
        self.assertEqual(alignment["block_recall"], 1.0)
        self.assertEqual(alignment["block_f1"], 1.0)

    def test_manual_review_flag_is_not_an_accuracy_verdict(self):
        passed = {"char_ngram_precision": 0.95, "char_ngram_recall": 0.95, "char_ngram_f1": 0.95}
        review = {"char_ngram_precision": 0.70, "char_ngram_recall": 0.99, "char_ngram_f1": 0.82}
        self.assertFalse(baseline.needs_manual_review(passed))
        self.assertTrue(baseline.needs_manual_review(review))
        self.assertFalse(
            baseline.needs_manual_review(dict(passed, block_f1=0.20)),
            "block-level segmentation mismatch alone must not trigger the review gate",
        )

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
            self.assertIn("average_block_f1", payload["summary"])
            self.assertIn("block_match_threshold", payload)
            self.assertNotIn("approximate_pairs", payload["pages"][0]["comparison"])
            self.assertTrue((reference_dir / "pydoc_appetite.json").exists())
            self.assertTrue(report.exists())
            self.assertTrue(report.with_suffix(".md").exists())
            self.assertTrue(report.with_suffix(".md").read_text(encoding="utf-8").find("块级") >= 0)


if __name__ == "__main__":
    unittest.main()
