"""Resolve environment overrides and the user's persistent model configuration."""

import json
import os
from pathlib import Path

from matsimpy.ai.provider import DeepSeekProvider


def configured_provider(config_path: Path | None = None) -> DeepSeekProvider:
    if os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekProvider()
    if os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"):
        return DeepSeekProvider(
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ["OPENAI_MODEL"],
            base_url=os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        )

    path = config_path or Path.home() / ".config" / "2d-matagent" / "model.json"
    if not path.is_file():
        raise ValueError("请配置模型环境变量或 ~/.config/2d-matagent/model.json。离线验收请加 --demo。")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"无法读取有效的模型配置文件 {path}。") from None
    if not isinstance(config, dict) or config.get("provider") != "deepseek":
        raise ValueError("本地模型配置的 provider 应为 deepseek。")
    required = ("api_key", "base_url", "model")
    if any(not isinstance(config.get(key), str) or not config[key].strip() for key in required):
        raise ValueError("本地模型配置需要非空的 api_key、base_url 和 model 字段。")
    return DeepSeekProvider(
        api_key=config["api_key"],
        model=config["model"],
        base_url=config["base_url"],
        reasoning_effort=config.get("reasoning_effort"),
    )
