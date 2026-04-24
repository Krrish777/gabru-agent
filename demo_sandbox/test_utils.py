"""Tests for demo_sandbox/utils.reverse_str — Tester stage output."""

import pytest

from utils import reverse_str


class TestReverseStrHappyPath:
    def test_reverses_short_ascii_string(self):
        assert reverse_str("abc") == "cba"

    def test_reverses_multiword_sentence(self):
        assert reverse_str("hello world") == "dlrow olleh"


class TestReverseStrEdges:
    def test_empty_string_returns_empty(self):
        assert reverse_str("") == ""

    def test_single_char_is_its_own_reverse(self):
        assert reverse_str("x") == "x"

    def test_palindrome_is_unchanged(self):
        assert reverse_str("racecar") == "racecar"

    def test_unicode_is_reversed_by_code_point(self):
        # Note: this is code-point reversal, not grapheme-cluster aware.
        assert reverse_str("héllo") == "olléh"


class TestReverseStrTypeContract:
    def test_non_string_input_raises(self):
        # reverse_str is type-hinted but not enforced; slicing an int raises.
        with pytest.raises(TypeError):
            reverse_str(123)  # type: ignore[arg-type]
