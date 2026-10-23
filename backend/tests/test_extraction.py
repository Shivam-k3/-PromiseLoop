"""Deterministic natural-language extraction used by the mock provider."""

from app.llm.extraction import extract_commitment


def test_relationship_without_amount_or_deadline():
    extracted = extract_commitment("I promise to send money to my sister.")
    assert extracted is not None
    assert extracted.title == "Send money to my sister"
    assert extracted.recipient == "sister"
    assert extracted.due_text is None


def test_amount_and_bare_tomorrow_are_kept():
    extracted = extract_commitment("I'll send ₹2,000 to my sister tomorrow.", "Asia/Kolkata")
    assert extracted is not None
    assert "2,000" in extracted.title
    assert extracted.recipient == "sister"
    assert extracted.due_text == "tomorrow"


def test_told_recipient_and_evening_deadline():
    extracted = extract_commitment(
        "I told Abhishek I'll send the project demo tomorrow evening.", "Asia/Kolkata"
    )
    assert extracted is not None
    assert extracted.title == "Send the project demo"
    assert extracted.recipient == "Abhishek"
    assert extracted.due_text == "tomorrow evening"


def test_personal_task_with_ambiguous_friday_asks_for_clarification():
    extracted = extract_commitment("I need to finish my report by Friday.", "Asia/Kolkata")
    assert extracted is not None
    assert extracted.title == "Finish my report"
    assert extracted.recipient is None
    assert extracted.due_text.lower() == "friday"
    assert extracted.ambiguous is True
    assert extracted.question is not None


def test_unrelated_question_is_not_a_commitment():
    assert extract_commitment("What's the weather like today?") is None


def test_hypothetical_and_quoted_examples_are_not_commitments():
    assert extract_commitment("If I promised Abhishek, I'll send the demo tomorrow.") is None
    assert extract_commitment('"I promised Abhishek I will send the demo tomorrow."') is None
