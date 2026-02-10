from __future__ import annotations


def build_phi3_validator_prompt(query: str, candidates: str) -> str:
    return (
        "Du bist Tier-2 Validator. Wähle maximal 5 Dateien aus den Kandidaten, "
        "die zur Query passen. Antworte NUR als JSON im Format "
        '{"selected_paths":["a.py"],"why":"..."}.\n\n'
        f"Query:\n{query}\n\n"
        f"Kandidaten:\n{candidates}\n"
    )


def build_qwen_preprocessor_prompt(query: str, bundle_text: str) -> str:
    return (
        "Du bist Tier-2 Preprocessor. Komprimiere Kontext: wichtigste Funktionen, "
        "Signaturen, Imports, Klassen, TODOs. Entferne Implementierungsdetails. "
        "Antworte NUR als JSON: "
        '{"overall_summary":"...","files":[{"path":"...","purpose":"...",'
        '"key_symbols":[],"imports":[],"classes":[],"functions":[],"notes":[]}]}\n\n'
        f"Query:\n{query}\n\n"
        f"Dateikontext:\n{bundle_text}\n"
    )
