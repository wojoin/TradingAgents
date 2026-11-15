"""What a web-started run uses: the CLI's last choices, so a run needs only a ticker.

The CLI remembers its answers in ``~/.tradingagents/cli_prefs.json`` (provider,
models, research depth, output language, analysts). A web run takes the same,
over ``DEFAULT_CONFIG`` with its ``TRADINGAGENTS_*`` environment overrides; a round
count set in the environment wins over the remembered research depth, as in the CLI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG

PREFS_PATH = Path(os.path.expanduser("~")) / ".tradingagents" / "cli_prefs.json"
ANALYST_ORDER = ("market", "social", "news", "fundamentals")
_LLM_KEYS = ("llm_provider", "quick_think_llm", "deep_think_llm", "backend_url", "output_language")
_ROUNDS = (("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "max_debate_rounds"),
           ("TRADINGAGENTS_MAX_RISK_ROUNDS", "max_risk_discuss_rounds"))


def load_prefs(path: Path | None = None) -> dict:
    """The CLI's remembered answers, or {} when there are none or the file is unreadable."""
    try:
        data = json.loads((path or PREFS_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_config(prefs: dict | None = None) -> tuple[dict, list[str]]:
    """The config and analyst keys for a web run."""
    prefs = load_prefs() if prefs is None else prefs
    config = DEFAULT_CONFIG.copy()
    for key in _LLM_KEYS:
        if prefs.get(key):
            config[key] = prefs[key]
    if config.get("llm_provider"):
        config["llm_provider"] = str(config["llm_provider"]).lower()
    depth = prefs.get("research_depth")
    if isinstance(depth, int) and depth > 0:
        for env_var, key in _ROUNDS:
            if not os.environ.get(env_var):
                config[key] = depth
    chosen = set(prefs.get("analysts") or ANALYST_ORDER)
    analysts = [a for a in ANALYST_ORDER if a in chosen] or list(ANALYST_ORDER)
    return config, analysts


def describe(config: dict, analysts: list[str]) -> dict:
    """The settings a run will use, for the page to show (no keys, no endpoints)."""
    return {
        "llm_provider": config.get("llm_provider"),
        "deep_think_llm": config.get("deep_think_llm"),
        "quick_think_llm": config.get("quick_think_llm"),
        "output_language": config.get("output_language"),
        "research_rounds": config.get("max_debate_rounds"),
        "risk_rounds": config.get("max_risk_discuss_rounds"),
        "analysts": analysts,
        "prefs_found": PREFS_PATH.exists(),
    }
