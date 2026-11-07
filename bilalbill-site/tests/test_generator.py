import pytest

from generator import QualityError, validate_article


def valid_article():
    paragraphs = [
        f"Guide section {number} explains practical steps for comparing tools, checking current details, and choosing a safe option."
        for number in range(1, 70)
    ]
    body = (
        "## Planning your next step\n\n"
        "### Start with your needs\n\n"
        + "\n\n".join(paragraphs)
        + "\n\n## Frequently Asked Questions\n\n"
        + "\n\n".join(
            f"### What should readers check in case {number}?\n\n"
            f"Review the current details for case {number} before deciding."
            for number in range(1, 5)
        )
    )
    return {
        "title": "bilalbill practical technology guide",
        "slug": "bilalbill-practical-technology-guide",
        "meta_description": "A concise guide to practical technology decisions and checks.",
        "markdown": body,
        "tags": ["technology", "guides"],
        "category": "Technology",
        "verify_before_publish": ["Check current requirements.", "Verify any prices.", "Review cited facts."],
    }


def test_quality_gates_accept_article_with_required_sections():
    article = valid_article()
    validate_article(article, "bilalbill")


def test_quality_gates_reject_short_article_and_duplicate_paragraph():
    article = valid_article()
    with pytest.raises(QualityError, match="900-1300"):
        validate_article({**article, "markdown": "## Short\n\nA few words."}, "bilalbill")

    article = valid_article()
    first_paragraph = article["markdown"].split("\n\n")[2]
    with pytest.raises(QualityError, match="duplicate paragraphs"):
        validate_article(
            {**article, "markdown": article["markdown"] + "\n\n" + first_paragraph},
            "bilalbill",
        )


def test_quality_gate_rejects_repeated_content():
    article = valid_article()
    with pytest.raises(QualityError, match="similar"):
        validate_article(article, "bilalbill", [article["markdown"]])
