import unittest
from voice.evaluation import word_error_rate


class SpeechEvaluationTests(unittest.TestCase):
    def test_alignment_retains_substitution_deletion_and_insertion_counts(self):
        self.assertEqual(
            word_error_rate("Atlas is ready", "Adless is ready")["substitutions"], 1
        )
        self.assertEqual(
            word_error_rate("Atlas is ready", "Atlas ready")["deletions"], 1
        )
        self.assertEqual(
            word_error_rate("Atlas is ready", "Atlas is very ready")["insertions"], 1
        )
        self.assertAlmostEqual(
            word_error_rate("Atlas is ready", "Adless is ready")["wer"], 1 / 3
        )

    def test_case_punctuation_and_empty_reference_have_explicit_semantics(self):
        self.assertEqual(word_error_rate("Hello, Atlas!", "hello atlas")["wer"], 0)
        self.assertEqual(word_error_rate("", "")["wer"], 0)
        self.assertIsNone(word_error_rate("", "hallucinated speech")["wer"])
        self.assertGreater(word_error_rate("hello", "hello extra words")["wer"], 1)
