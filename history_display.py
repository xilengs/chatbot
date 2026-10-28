from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
)

def to_chatbot_messages(messages):
    """将已经验证的历史消息转换为页面显示内容"""
    display_messages = []

    for message in messages:
        # 工具结果保留在模型历史中，不作为聊天气泡展示
        if isinstance(message, ToolMessage):
            continue

        if not isinstance(message, (HumanMessage, AIMessage)):
            raise ValueError(f"Unknown message type: {type(message).__name__}")

        if not isinstance(message.content, str):
            raise ValueError(f"Message content must be a string, got {type(message.content).__name__}")
        
        if isinstance(message, HumanMessage):
            display_messages.append({"role": "user", "content": message.content})

        elif (display_messages and display_messages[-1]["role"] == "assistant"):
            display_messages[-1]["content"] += message.content

        else:
            display_messages.append({"role": "assistant", "content": message.content})

    return display_messages