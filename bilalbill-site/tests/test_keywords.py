from keywords import dedupe_keywords, normalize_keyword, score_keyword


def test_keyword_deduplication_is_case_and_whitespace_insensitive():
    assert dedupe_keywords(["  BilalBill ", "bilalbill", "Bilal   Bill", ""]) == [
        "BilalBill",
        "Bilal Bill",
    ]
    assert normalize_keyword("  Bilal   BILL ") == "bilal bill"


def test_question_and_pakistan_terms_get_a_higher_score():
    plain = score_keyword("useful technology guide")
    specific = score_keyword("how to choose technology price Pakistan")
    assert specific > plain
