"""Utility for creating error-focused code windows."""


def _normalize_positive_int(value, default):
    try:
        value_int = int(value)
    except (TypeError, ValueError):
        return default
    return value_int if value_int > 0 else default


def create_error_window(full_code, error_line, chunk_size, window_chunks, include_signatures):
    """Create a compact window of code around an error line.

    Args:
        full_code: Entire code content as a string.
        error_line: 1-indexed line number where the error occurred.
        chunk_size: Number of lines per chunk.
        window_chunks: Number of chunks to include before/after the error chunk.
        include_signatures: Include function/class signatures outside the window.

    Returns:
        dict: Windowed representation with line numbers and optional signatures.
    """
    lines = full_code.splitlines()
    total_lines = len(lines)
    chunk_size = _normalize_positive_int(chunk_size, 1)
    window_chunks = max(0, _normalize_positive_int(window_chunks, 0))

    if total_lines == 0:
        return {
            "error_line": error_line,
            "total_lines": 0,
            "window_start_line": 0,
            "window_end_line": 0,
            "window": [],
            "signatures": [],
        }

    error_line = max(1, min(int(error_line), total_lines))
    error_index = error_line - 1
    max_chunk_index = (total_lines - 1) // chunk_size
    error_chunk = error_index // chunk_size

    start_chunk = max(0, error_chunk - window_chunks)
    end_chunk = min(max_chunk_index, error_chunk + window_chunks)

    window_start_line = start_chunk * chunk_size + 1
    window_end_line = min(total_lines, (end_chunk + 1) * chunk_size)

    window = [
        {"line_no": line_no, "text": lines[line_no - 1]}
        for line_no in range(window_start_line, window_end_line + 1)
    ]

    signatures = []
    if include_signatures:
        for line_no, line in enumerate(lines, start=1):
            if window_start_line <= line_no <= window_end_line:
                continue
            stripped = line.lstrip()
            if stripped.startswith("def ") or stripped.startswith("class "):
                signatures.append({"line_no": line_no, "text": line})

    return {
        "error_line": error_line,
        "total_lines": total_lines,
        "window_start_line": window_start_line,
        "window_end_line": window_end_line,
        "window": window,
        "signatures": signatures,
    }
