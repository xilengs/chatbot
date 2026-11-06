import logging
from pathlib import Path

from langchain_openai import ChatOpenAI

from app_config import load_settings, load_context_settings
from agent_factory import build_agent, CHAT_PROMPT_VERSION
from chat_storage import ChatStorage
from chat_service import ChatService
from chat_ui import build_chat_ui, CHAT_CSS
from context_manager import ContextManager
from history_loader import load_session_turns
from summary_generator import build_summarizer
from session_title_generator import build_title_generator
from token_budget_checker import TokenBudgetChecker


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    db_config, model_config = load_settings()
    storage = ChatStorage(db_config)

    # 聊天模型、提示词及预算检查器。
    context_settings = load_context_settings()

    chain, tools_by_name, prompt, checker = build_agent(
        model_config,
        context_settings=context_settings,
    )

    # 摘要使用独立预算。
    tokenizer_path = (
        Path(__file__).resolve().parent
        / "model_assets"
        / "tokenizer.json"
    )

    summary_checker = TokenBudgetChecker(
        tokenizer_path,
        context_window=16000,
        output_reserve=4096,
        safety_margin=1000,
    )

    summary_model = ChatOpenAI(
        **{
            **model_config,
            "temperature": 0,
        }
    )

    summary_strategy_version = "learning_v1"
    max_summary_tokens = 2048
    
    summarize = build_summarizer(
        summary_model,
        focus="用户的学习目标、学习偏好、已掌握知识和下一步学习任务。",
        budget_checker=summary_checker,
        max_summary_tokens=max_summary_tokens,
    )

    context_manager = ContextManager(
        storage,
        turn_loader=load_session_turns,
        strategy_version=summary_strategy_version,
        summarizer=summarize,
    )

    execution_config = {
        "config_version": 1,

        "chat_prompt": {"version": CHAT_PROMPT_VERSION},
        "chat_model": {
            "name": model_config["model"],
            "temperature": model_config.get("temperature"),
            "max_tokens": checker.output_reserve,
        },

        "chat_budget": {
            **context_settings,
            "input_limit": checker.input_limit,
        },

        "tools": sorted(tools_by_name),

        "summary": {
            "enabled": True,
            "strategy_version": summary_strategy_version,
            "model": summary_model.model_name,
            "temperature": summary_model.temperature,
            "input_limit": summary_checker.input_limit,
            "output_reserve": summary_checker.output_reserve,
            "max_summary_tokens": max_summary_tokens,
        },
    }

    title_model = ChatOpenAI(**{
        **model_config,
        "temperature": 0,
        "timeout": 10,
        "max_retries": 0,
        "extra_body": {"max_tokens": 128},
    })

    service = ChatService(
        storage=storage,
        chain=chain,
        tools_by_name=tools_by_name,
        context_manager=context_manager,
        context_prompt=prompt,
        context_checker=checker,
        execution_config=execution_config,
        keep_recent_turns=2,
        title_generator=build_title_generator(title_model),
    )

    page = build_chat_ui(
        service=service,
        user_id="user_001",
    )

    page.queue().launch(share=True, css=CHAT_CSS)


if __name__ == "__main__":
    main()
