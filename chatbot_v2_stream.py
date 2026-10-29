from app_config import load_settings, load_context_settings
from agent_factory import build_agent
from chat_storage import ChatStorage
from chat_service import ChatService
from chat_ui import build_chat_ui


def main():
    db_config, model_config = load_settings()

    storage = ChatStorage(db_config)
    
    context_settings = load_context_settings()

    chain, tools_by_name = build_agent(model_config, context_settings=context_settings)

    service = ChatService(
        storage=storage,
        chain=chain,
        tools_by_name=tools_by_name,
    )

    page = build_chat_ui(
        service=service,
        user_id="user_001",
    )

    page.queue().launch(share=True)


if __name__ == "__main__":
    main()