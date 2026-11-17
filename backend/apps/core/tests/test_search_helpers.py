from apps.core.search import MAX_TERMS, compact, split_terms


def test_compact_removes_spaces_and_dashes_and_uppercases():
    assert compact("887 hhh-15") == "887HHH15"
    assert compact("887") == "887"


def test_split_terms_by_words_with_limit():
    assert split_terms("  887   hhh ") == ["887", "hhh"]
    assert len(split_terms(" ".join(str(i) for i in range(20)))) == MAX_TERMS
    assert split_terms("   ") == []
