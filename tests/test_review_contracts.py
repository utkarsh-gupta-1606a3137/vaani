"""Independent regressions from implementation review; no inference required."""
import tempfile
import unittest
from pathlib import Path

from vaani.input import prepare
from vaani.chunking import plan
from vaani.resources import Lease
from vaani.types import VaaniError

ROOT = Path(__file__).resolve().parents[1]


class InputPreservationReview(unittest.TestCase):
    def test_long_fence_contains_short_fences_without_speaking_code(self):
        source = "Intro.\n\n````python\nsecret()\n```\nstill_secret()\n````\n\nOutro."
        self.assertEqual(prepare(source, "markdown"), "Intro.\n\nOutro.")

    def test_frontmatter_requires_an_exact_closing_line(self):
        with self.assertRaises(VaaniError) as failure:
            prepare("---\nkey: value\n---not-a-delimiter\nBody.", "markdown")
        self.assertEqual(failure.exception.code, 2)

    def test_inline_code_identifiers_survive_emphasis_cleanup(self):
        source = "Use `foo__bar`, `a**b`, and **clear speech**."
        self.assertEqual(prepare(source, "markdown"), "Use foo__bar, a**b, and clear speech.")

    def test_plain_text_preserves_identifiers_and_paragraphs(self):
        source = "\ufeffUse foo__bar and a**b.\r\nThis line wraps.\r\n\r\nअगला paragraph."
        self.assertEqual(prepare(source), "Use foo__bar and a**b. This line wraps.\n\nअगला paragraph.")

    def test_only_code_is_not_a_spoken_script(self):
        with self.assertRaises(VaaniError) as failure:
            prepare("```python\nprint('not narration')\n```", "markdown")
        self.assertEqual(failure.exception.code, 2)


class ChunkBoundaryReview(unittest.TestCase):
    def test_approved_paragraph_is_one_complete_unit(self):
        text = prepare((ROOT / "examples/audition.txt").read_text())
        chunks = plan(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], text)
        self.assertEqual(text[chunks[0]["start_character"]:chunks[0]["end_character"]], text)

    def test_long_script_preserves_order_and_actual_source_spans(self):
        text = prepare(" ".join(f"Step {n} preserves identifier_{n} and its exact value." for n in range(50)))
        chunks = plan(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(c["text"] for c in chunks).split(), text.split())
        last_end = 0
        for chunk in chunks:
            start, end = chunk["start_character"], chunk["end_character"]
            self.assertGreaterEqual(start, last_end)
            self.assertEqual(text[start:end], chunk["text"])
            last_end = end


class LeaseReview(unittest.TestCase):
    def test_second_worker_is_refused_and_exception_releases_lease(self):
        parent = ROOT / "tmp"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="review-lease-", dir=parent) as directory:
            try:
                with Lease(directory):
                    with self.assertRaises(VaaniError) as failure:
                        with Lease(directory):
                            self.fail("A second lease must not succeed")
                    self.assertEqual(failure.exception.code, 5)
                    raise RuntimeError("simulated interrupted job")
            except RuntimeError:
                pass
            with Lease(directory):
                pass


if __name__ == "__main__":
    unittest.main()
