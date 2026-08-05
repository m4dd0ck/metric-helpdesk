from datetime import date
from pathlib import Path

from metric_helpdesk.evals import EvalQuestion, ValueSpec, grade, load_questions, number_variants
from metric_helpdesk.tools import HelpDesk

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JANUARY = ValueSpec(metric="revenue", start=date(2024, 1, 1), end=date(2024, 1, 31))


def test_bundled_questions_parse() -> None:
    questions = load_questions(PROJECT_ROOT / "evals" / "questions.yaml")
    assert len({q.id for q in questions}) == len(questions) >= 6


def test_number_variants_cover_common_formats() -> None:
    assert {"92,378", "92378", "92.4k"} <= set(number_variants(92377.9, is_rate=False))
    assert "15.7%" in number_variants(0.1566, is_rate=True)


def test_grade_passes_a_correct_answer(helpdesk: HelpDesk) -> None:
    question = EvalQuestion(
        id="q", question="?", must_call=["query_metrics"], must_mention=["january"],
        values=[JANUARY],
    )  # fmt: skip
    checks = grade(helpdesk, question, "January revenue was $930.", ["query_metrics"])
    assert all(check.passed for check in checks)


def test_grade_flags_wrong_number_missing_call_and_leaked_sql(helpdesk: HelpDesk) -> None:
    question = EvalQuestion(
        id="q", question="?", must_call=["query_metrics"], values=[JANUARY],
        must_not=["\\bSELECT\\b"],
    )  # fmt: skip
    checks = grade(helpdesk, question, "SELECT sum(amount) gives 931.", [])
    assert [check.passed for check in checks] == [False, False, False]
