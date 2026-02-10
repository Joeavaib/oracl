from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Tier2Config:
    phi3_model_path: str = ""
    qwen_model_path: str = ""
    phi3_model_id: str = "phi-3-mini-4k-instruct"
    qwen_model_id: str = "qwen2-1.5b-instruct"
    phi3_base_url: str = "http://127.0.0.1:8081/v1"
    qwen_base_url: str = "http://127.0.0.1:8082/v1"
    threads: int = 4
    ctx_phi3: int = 4096
    ctx_qwen: int = 8192
    max_selected_files: int = 5
    max_bytes_per_file: int = 120_000
    max_total_bytes: int = 300_000


def load_tier2_config() -> Tier2Config:
    return Tier2Config(
        phi3_model_path=os.getenv("TIER2_PHI3_MODEL_PATH", ""),
        qwen_model_path=os.getenv("TIER2_QWEN_MODEL_PATH", ""),
        phi3_model_id=os.getenv("TIER2_PHI3_MODEL_ID", "phi-3-mini-4k-instruct"),
        qwen_model_id=os.getenv("TIER2_QWEN_MODEL_ID", "qwen2-1.5b-instruct"),
        phi3_base_url=os.getenv("TIER2_PHI3_BASE_URL", "http://127.0.0.1:8081/v1"),
        qwen_base_url=os.getenv("TIER2_QWEN_BASE_URL", "http://127.0.0.1:8082/v1"),
        threads=int(os.getenv("TIER2_THREADS", "4")),
        ctx_phi3=int(os.getenv("TIER2_CTX_PHI3", "4096")),
        ctx_qwen=int(os.getenv("TIER2_CTX_QWEN", "8192")),
        max_selected_files=int(os.getenv("TIER2_MAX_SELECTED_FILES", "5")),
        max_bytes_per_file=int(os.getenv("TIER2_MAX_BYTES_PER_FILE", "120000")),
        max_total_bytes=int(os.getenv("TIER2_MAX_TOTAL_BYTES", "300000")),
    )
