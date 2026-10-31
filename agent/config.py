"""Central configuration. Everything can be overridden with environment variables."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    db_path: str = os.getenv("AGENT_DB", "data/olist.db")
    model: str = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")   # any current Claude model id
    max_steps: int = 8          # max LLM turns per question
    max_rows: int = 500         # hard cap on rows fetched from the database
    model_rows: int = 30        # rows echoed back to the model (keeps tokens low)
    timeout_s: float = 10.0     # per-query wall-clock limit
    max_tokens: int = 1500      # max output tokens per LLM turn
    charts_dir: str = "outputs/charts"
    log_path: str = "logs/runs.jsonl"
