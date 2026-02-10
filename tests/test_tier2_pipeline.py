import json

from app.tier2.config import Tier2Config
from app.tier2.pipeline import run_tier2
from app.tier2.types import Tier1Candidate


def _cfg() -> Tier2Config:
    return Tier2Config(max_selected_files=5, max_bytes_per_file=120000, max_total_bytes=300000)


def test_phi3_drops_paths_outside_candidates(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_chat_completions(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"selected_paths": ["evil.py", "a.py"], "why": "pick"})
        return json.dumps(
            {
                "overall_summary": "ok",
                "files": [
                    {
                        "path": "a.py",
                        "purpose": "one",
                        "key_symbols": ["a"],
                        "imports": [],
                        "classes": [],
                        "functions": ["a()"],
                        "notes": [],
                    }
                ],
            }
        )

    monkeypatch.setattr("app.tier2.validator_phi3.chat_completions", fake_chat_completions)
    monkeypatch.setattr("app.tier2.preprocessor_qwen.chat_completions", fake_chat_completions)

    selection, _, _ = run_tier2(
        repo_root=tmp_path,
        query="pick a",
        tier1_items=[Tier1Candidate(rel_path="a.py", score=0.9, rank=1), Tier1Candidate(rel_path="b.py", score=0.8, rank=2)],
        cfg=_cfg(),
        cache_dir=tmp_path / ".cache",
    )

    assert selection.selected_paths == ["a.py"]


def test_phi3_empty_uses_top5_fallback(tmp_path, monkeypatch):
    for idx in range(6):
        (tmp_path / f"f{idx}.py").write_text(f"def f{idx}():\n    return {idx}\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_chat_completions(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"selected_paths": [], "why": "none"})
        return "{bad json"

    monkeypatch.setattr("app.tier2.validator_phi3.chat_completions", fake_chat_completions)
    monkeypatch.setattr("app.tier2.preprocessor_qwen.chat_completions", fake_chat_completions)

    items = [Tier1Candidate(rel_path=f"f{idx}.py", score=1 - idx / 10, rank=idx + 1) for idx in range(6)]
    selection, context, _ = run_tier2(
        repo_root=tmp_path,
        query="fallback",
        tier1_items=items,
        cfg=_cfg(),
        cache_dir=tmp_path / ".cache",
    )

    assert selection.selected_paths == [f"f{idx}.py" for idx in range(5)]
    assert "Deterministic Tier-2 bundle" in context.overall_summary


def test_cache_hit_skips_llm_calls(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_chat_completions(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"selected_paths": ["a.py"], "why": "pick"})
        return json.dumps(
            {
                "overall_summary": "ok",
                "files": [
                    {
                        "path": "a.py",
                        "purpose": "one",
                        "key_symbols": ["a"],
                        "imports": [],
                        "classes": [],
                        "functions": ["a()"],
                        "notes": [],
                    }
                ],
            }
        )

    monkeypatch.setattr("app.tier2.validator_phi3.chat_completions", fake_chat_completions)
    monkeypatch.setattr("app.tier2.preprocessor_qwen.chat_completions", fake_chat_completions)

    items = [Tier1Candidate(rel_path="a.py", score=0.9, rank=1)]
    run_tier2(tmp_path, "cache", items, _cfg(), cache_dir=tmp_path / ".cache")
    _, _, cache_hit = run_tier2(tmp_path, "cache", items, _cfg(), cache_dir=tmp_path / ".cache")

    assert calls["n"] == 2
    assert cache_hit is True
