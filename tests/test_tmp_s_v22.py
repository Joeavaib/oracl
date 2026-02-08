import pytest

from protocols.tmp_s_v22 import (
    MAX_RATIONALE_WORDS,
    normalize_tmp_s,
    parse_tmp_s,
    validate_tmp_s,
)


def test_parse_and_validate_good_case():
    text = "\n".join(
        [
            "V|2.2|run-1|pre_planner|1",
            "A|hard1,hard2,hard3,hard4|soft1,soft2,soft3,soft4|accept|All good.",
            "E|app/main.py|low|Fix it.",
            "B|p1:planner|Check scope.",
            "B|p2:planner|Confirm files.",
            "B|p3:planner|Ready.",
            "C|accept|none|0|focus",
        ]
    )
    msg = parse_tmp_s(text)
    errors = validate_tmp_s(msg)
    assert errors == []
    assert msg.header.ver == "2.2"
    assert msg.audit.verdict == "accept"
    assert len(msg.briefs) == 3


def test_validate_rejects_bad_order():
    text = "\n".join(
        [
            "V?",
            "A|h|s|accept|ok",
            "C|accept|none|0|*",
            "B|p1:planner|late",
            "B|p2:planner|late",
            "B|p3:planner|late",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("order" in err.fix_hint for err in errors)


def test_validate_rejects_pipe_spaces():
    text = "\n".join(
        [
            "V?",
            "A|hard4 |soft4|accept|ok",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|accept|none|0|*",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("Pipes" in err.fix_hint for err in errors)


def test_validate_rejects_too_many_briefs():
    text = "\n".join(
        [
            "V?",
            "A|h|s|accept|ok",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "B|p4:planner|four",
            "B|p5:planner|five",
            "B|p6:planner|six",
            "B|p7:planner|seven",
            "B|p8:planner|eight",
            "C|accept|none|0|*",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("between" in err.fix_hint for err in errors)


def test_validate_rejects_long_rationale():
    rationale = " ".join(["word"] * (MAX_RATIONALE_WORDS + 1))
    text = "\n".join(
        [
            "V?",
            f"A|h|s|accept|{rationale}",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|accept|none|0|*",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("Rationale" in err.fix_hint for err in errors)


def test_normalize_defaults_p_decision():
    text = "\n".join(
        [
            "V?",
            "A|h|s|P|ok",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|P|||",
        ]
    )
    msg = normalize_tmp_s(parse_tmp_s(text))
    assert msg.header.ver == "2.2"
    assert msg.control.decision == "accept"
    assert msg.control.strategy == "0"
    assert msg.control.max_retries == 0
    assert msg.control.focus == "*"


def test_validate_rejects_missing_lines():
    text = "\n".join(
        [
            "V?",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|accept|none|0|*",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("Missing A line" in err.fix_hint for err in errors)


def test_validate_rejects_extra_lines():
    text = "\n".join(
        [
            "V?",
            "A|h|s|accept|ok",
            "E|path|low|fix",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|accept|none|0|*",
            "Z|unexpected|line",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert any("order" in err.fix_hint for err in errors)


def test_validate_rejects_pipe_in_rationale():
    text = "\n".join(
        [
            "V?",
            "A|h|s|accept|bad|rationale",
            "B|p1:planner|one",
            "B|p2:planner|two",
            "B|p3:planner|three",
            "C|accept|none|0|*",
        ]
    )
    errors = validate_tmp_s(parse_tmp_s(text))
    assert errors
