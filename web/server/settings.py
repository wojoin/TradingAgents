"""What a web-started run uses: the options a person picks, defaulting to their last choices.

The page offers the questions the CLI asks before a run: analysis date, analysts,
research depth, LLM provider (with its region, or its endpoint for a local or
custom server), the quick and deep models, the provider's reasoning setting, and
the output language. Defaults are the last run's answers, kept in
``~/.tradingagents/cli_prefs.json`` and shared with the CLI; a web run that starts
saves its answers there too.

Providers that need more than a key (a ChatGPT plan's sign-in, Azure deployments,
AWS credentials for Bedrock) are left to the CLI.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.date_window import get_current_date
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import get_api_key_env

PREFS_PATH = Path(os.path.expanduser("~")) / ".tradingagents" / "cli_prefs.json"
ANALYST_ORDER = ("market", "social", "news", "fundamentals")
ANALYSTS = (("market", "市场/技术分析师"), ("social", "情绪分析师"), ("news", "新闻分析师"),
            ("fundamentals", "基本面分析师"))
DEPTHS = ((1, "浅", "1 轮多空辩论、1 轮风控讨论，最快最省"), (3, "中", "3 轮辩论与讨论"),
          (5, "深", "5 轮辩论与讨论，最全面，耗时和费用最高"))
LANGUAGES = (("English", "English"), ("Chinese", "中文"), ("Japanese", "日本語"), ("Korean", "한국어"),
             ("Hindi", "हिन्दी"), ("Spanish", "Español"), ("Portuguese", "Português"), ("French", "Français"),
             ("German", "Deutsch"), ("Arabic", "العربية"), ("Russian", "Русский"))
# Reasoning settings, by provider: (config key, [(value, label)]), as the CLI asks them.
EFFORTS = {
    "openai": ("openai_reasoning_effort", (("medium", "中（默认）"), ("high", "高（更周全）"), ("low", "低（更快）"))),
    "anthropic": ("anthropic_effort", (("high", "高（推荐）"), ("medium", "中"), ("low", "低（更快更省）"))),
    "google": ("google_thinking_level", (("high", "开启思考（推荐）"), ("minimal", "最少思考"))),
}
# Region variants the CLI asks for in a second step, offered here as providers of their own.
REGIONS = {
    "qwen": ("qwen-cn", "Qwen（中国区）", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "glm": ("glm-cn", "GLM（BigModel 中国区）", "https://open.bigmodel.cn/api/paas/v4/"),
    "minimax": ("minimax-cn", "MiniMax（中国区）", "https://api.minimaxi.com/v1"),
}
WEB_EXCLUDED = {"chatgpt", "azure", "bedrock"}
URL_EDITABLE = {"ollama", "openai_compatible"}
_ROUNDS = (("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "max_debate_rounds"),
           ("TRADINGAGENTS_MAX_RISK_ROUNDS", "max_risk_discuss_rounds"))
_REMEMBERED = ("output_language", "analysts", "research_depth", "llm_provider",
               "quick_think_llm", "deep_think_llm", "backend_url")


def load_prefs(path: Path | None = None) -> dict:
    """The remembered answers, or {} when there are none or the file is unreadable."""
    try:
        data = json.loads((path or PREFS_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(options: RunOptions, path: Path | None = None) -> None:
    """Remember a run's answers for the next run, web or CLI; failure is never fatal."""
    path = path or PREFS_PATH
    kept = {k: v for k, v in asdict(options).items() if k in _REMEMBERED and v not in (None, "", [])}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


# ---------------------------------------------------------------------------
# Providers and models
# ---------------------------------------------------------------------------
def providers() -> list[dict]:
    """The providers a web run can use, in the CLI's order, region variants beside their base."""
    from cli.prompts import _llm_provider_table
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

    def models(key: str, tier: str) -> list[dict]:
        listed = MODEL_OPTIONS.get(key) or MODEL_OPTIONS.get(key.split("-cn")[0]) or {}
        return [{"value": v, "label": label} for label, v in listed.get(tier, []) if v != "custom"]

    def entry(key: str, label: str, url: str | None) -> dict:
        env = get_api_key_env(key)
        effort = EFFORTS.get(key)
        return {
            "key": key, "label": label, "url": url, "url_editable": key in URL_EDITABLE,
            "key_env": env, "key_set": True if env is None or key == "openai_compatible" else bool(os.environ.get(env)),
            "models": {"quick": models(key, "quick"), "deep": models(key, "deep")},
            "effort": {"config_key": effort[0], "choices": [{"value": v, "label": lab} for v, lab in effort[1]]}
            if effort else None,
        }

    out = []
    for label, key, url in _llm_provider_table():
        if key in WEB_EXCLUDED:
            continue
        out.append(entry(key, label, url))
        if key in REGIONS:
            region_key, region_label, region_url = REGIONS[key]
            out.append(entry(region_key, region_label, region_url))
    return out


def options() -> dict:
    """Everything the analysis form offers, with the remembered answers as defaults."""
    prefs = load_prefs()
    listed = providers()
    keys = {p["key"] for p in listed}
    provider = str(prefs.get("llm_provider") or DEFAULT_CONFIG.get("llm_provider") or "openai").lower()
    if provider not in keys:
        provider = next((p["key"] for p in listed if p["key_set"]), listed[0]["key"])
    defaults = {
        "date": get_current_date(),
        "analysts": [a for a in ANALYST_ORDER if a in set(prefs.get("analysts") or ANALYST_ORDER)],
        "research_depth": prefs.get("research_depth") if prefs.get("research_depth") in (1, 3, 5) else 1,
        "llm_provider": provider,
        "quick_think_llm": prefs.get("quick_think_llm") if provider == prefs.get("llm_provider") else None,
        "deep_think_llm": prefs.get("deep_think_llm") if provider == prefs.get("llm_provider") else None,
        "backend_url": prefs.get("backend_url") if provider in URL_EDITABLE else None,
        "output_language": prefs.get("output_language") or "English",
        "effort": None,
    }
    return {
        "analysts": [{"value": v, "label": label} for v, label in ANALYSTS],
        "depths": [{"value": v, "label": label, "help": help_} for v, label, help_ in DEPTHS],
        "languages": [{"value": v, "label": label} for v, label in LANGUAGES],
        "providers": listed,
        "defaults": defaults,
        "today": get_current_date(),
        "prefs_found": PREFS_PATH.exists(),
    }


# ---------------------------------------------------------------------------
# A run's options
# ---------------------------------------------------------------------------
@dataclass
class RunOptions:
    date: str | None = None
    analysts: list[str] = field(default_factory=lambda: list(ANALYST_ORDER))
    research_depth: int = 1
    llm_provider: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    backend_url: str | None = None
    output_language: str = "English"
    effort: str | None = None


_MODEL_ID = re.compile(r"^[A-Za-z0-9._:/@+\-]{1,120}$")


def validate(raw: dict | None) -> RunOptions:
    """A run's options from the form, each checked; a ValueError names what is wrong.

    Missing fields take the remembered answers, as the form's defaults do.
    """
    raw = {k: v for k, v in (raw or {}).items() if v not in (None, "")}
    base = options()
    d = base["defaults"]
    pick = {**d, **raw}

    date = str(pick.get("date") or base["today"])
    try:
        if datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date:
            raise ValueError
    except ValueError:
        raise ValueError(f"分析日格式应为 YYYY-MM-DD：{date}") from None
    if date > base["today"]:
        raise ValueError(f"分析日不能晚于今天（{base['today']}）")

    analysts = pick.get("analysts") or []
    if not isinstance(analysts, list) or not analysts or any(a not in ANALYST_ORDER for a in analysts):
        raise ValueError("请至少选择一位分析师")
    analysts = [a for a in ANALYST_ORDER if a in analysts]

    depth = pick.get("research_depth")
    if depth not in (1, 3, 5):
        raise ValueError("研究深度只能是 1、3 或 5")

    providers_by_key = {p["key"]: p for p in base["providers"]}
    provider = str(pick.get("llm_provider") or "").lower()
    if provider not in providers_by_key:
        raise ValueError(f"不支持的模型提供商：{provider}")
    spec = providers_by_key[provider]
    if not spec["key_set"]:
        raise ValueError(f"{spec['label']} 的 API key 未设置：请在 .env 中设置 {spec['key_env']} 后重启后端")

    models = {}
    for tier in ("quick_think_llm", "deep_think_llm"):
        value = str(raw.get(tier) or (d.get(tier) if provider == d["llm_provider"] else "") or "").strip()
        if not value:
            listed = spec["models"]["quick" if tier.startswith("quick") else "deep"]
            if not listed:
                raise ValueError(f"请填写{'快速' if tier.startswith('quick') else '深度'}模型名")
            value = listed[0]["value"]
        if not _MODEL_ID.match(value):
            raise ValueError(f"模型名不合法：{value}")
        models[tier] = value

    url = spec["url"]
    if spec["url_editable"]:
        url = str(pick.get("backend_url") or url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("请填写以 http:// 或 https:// 开头的接口地址")

    effort = pick.get("effort")
    if spec["effort"]:
        allowed = [c["value"] for c in spec["effort"]["choices"]]
        effort = effort if effort in allowed else allowed[0]
    else:
        effort = None

    language = str(pick.get("output_language") or "English").strip()
    if not 1 <= len(language) <= 40:
        raise ValueError("输出语言不合法")

    return RunOptions(date=date, analysts=analysts, research_depth=depth, llm_provider=provider,
                      quick_think_llm=models["quick_think_llm"], deep_think_llm=models["deep_think_llm"],
                      backend_url=url, output_language=language, effort=effort)


def run_config(opts: RunOptions) -> tuple[dict, list[str]]:
    """The config and analyst keys for a run with these options, over DEFAULT_CONFIG.

    As in the CLI, a round count set in the environment wins over the depth, and
    TRADINGAGENTS_LLM_BACKEND_URL over the provider's endpoint.
    """
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = opts.llm_provider
    config["quick_think_llm"] = opts.quick_think_llm
    config["deep_think_llm"] = opts.deep_think_llm
    config["backend_url"] = os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL") or opts.backend_url
    config["output_language"] = opts.output_language
    for env_var, key in _ROUNDS:
        if not os.environ.get(env_var):
            config[key] = opts.research_depth
    effort = EFFORTS.get(opts.llm_provider or "")
    if effort and opts.effort:
        config[effort[0]] = opts.effort
    return config, list(opts.analysts)
