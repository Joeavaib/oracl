from app.window_manager import create_error_window


def test_create_error_window_basic():
    full_code = "\n".join(
        [
            "line1",
            "line2",
            "line3",
            "line4",
            "line5",
            "line6",
            "line7",
            "line8",
            "line9",
            "line10",
        ]
    )

    window = create_error_window(
        full_code=full_code,
        error_line=6,
        chunk_size=3,
        window_chunks=1,
        include_signatures=False,
    )

    assert window["window_start_line"] == 1
    assert window["window_end_line"] == 9
    assert window["error_line"] == 6
    assert window["window"][0]["text"] == "line1"
    assert window["window"][-1]["text"] == "line9"


def test_create_error_window_includes_signatures():
    full_code = "\n".join(
        [
            "def top():",
            "    pass",
            "",
            "def middle():",
            "    pass",
            "",
            "def bottom():",
            "    pass",
            "boom",
        ]
    )

    window = create_error_window(
        full_code=full_code,
        error_line=9,
        chunk_size=2,
        window_chunks=0,
        include_signatures=True,
    )

    assert window["window_start_line"] == 9
    assert window["window_end_line"] == 9

    signatures = window["signatures"]
    signature_lines = {item["line_no"] for item in signatures}
    assert signature_lines == {1, 4, 7}
