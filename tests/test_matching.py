"""The matching rules topic packs rely on, pinned down so refactors can't drift them."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aikb.topics import _bucket, _matched_terms, suggest_from_texts


def test_short_terms_match_whole_words_only():
    assert _matched_terms("Price the COP panel", ["COP"]) == ["COP"]
    assert _matched_terms("copy this file", ["COP"]) == []
    assert _matched_terms("we develop software", ["LOP"]) == []


def test_long_terms_match_across_spacing_and_case():
    assert _matched_terms("notes on the apacesystems repo", ["Apace Systems"]) == ["Apace Systems"]


def test_two_distinct_terms_make_a_high_confidence_match():
    assert _bucket(2, False, ["elevator", "GST"], manual=False) == "high"


def test_one_specific_term_is_medium_and_one_short_term_is_buried():
    assert _bucket(1, False, ["elevator"], manual=False) == "medium"
    assert _bucket(1, False, ["GST"], manual=False) == "buried"


def test_an_excluded_term_downgrades_one_level():
    assert _bucket(2, True, ["elevator", "GST"], manual=False) == "medium"
    assert _bucket(1, True, ["GST"], manual=False) == "false"


def test_a_manually_pinned_record_is_always_high():
    assert _bucket(0, False, [], manual=True) == "high"


def test_suggestions_keep_the_mid_frequency_band():
    texts = ["graphql schema rails"] * 3 + ["rails invoice"] * 3 + ["rails"] * 4
    words = dict(suggest_from_texts(texts, existing=[]))
    assert words == {"graphql": 3, "schema": 3, "invoice": 3}  # "rails" is in every text


def test_suggestions_drop_sentence_punctuation_but_keep_dotted_names():
    texts = ["it failed as expected. use node.js"] * 3 + ["alpha", "beta", "gamma"]
    words = dict(suggest_from_texts(texts, existing=[]))
    assert "expected" in words and "expected." not in words
    assert "node.js" in words


def test_suggestions_skip_terms_the_user_already_has():
    texts = ["Rails invoice"] * 3 + ["alpha", "beta", "gamma"]
    assert suggest_from_texts(texts, existing=["invoice"]) == [("rails", 3)]
