from __future__ import annotations

import re
from typing import Any


def extract_meta(file: dict[str, str]) -> dict[str, Any]:
    code = file["content"]
    lines = code.splitlines()
    return {
        "lines_of_code": len(lines),
        "num_functions": len(re.findall(r"def\s+\w+", code)),
        "num_classes": len(re.findall(r"class\s+\w+", code)),
        "num_imports": len(re.findall(r"(?:import|from)\s+\w+", code)),
    }
