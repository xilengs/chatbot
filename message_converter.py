from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
)

TYPE_TO_ROLE = {
    "system": "system",
    "human": "user",
    "ai": "assistant",
    "tool": "tool",
}

def to_storage_message(message, status="completed"):
    if not isinstance(message, BaseMessage):
        raise TypeError("message 必须是 LangChain 消息对象")
    
    if message.type not in TYPE_TO_ROLE:
        raise ValueError(f"暂不支持的消息类型：{message.type}")
    
    if status not in ("completed", "partial"):
        raise ValueError("status 必须是 'completed' 或 'partial'")
    
    raw = message_to_dict(message)
    data = raw["data"]

    payload = {
        "content": data["content"],
        "raw_langchain": raw,
    }

    # 按消息实际具有的字段提供工具信息
    for key in ("tool_calls", "tool_call_id", "name"):
        if key in data and data[key] is not None:
            payload[key] = data[key]
    
    return {
        "role": TYPE_TO_ROLE[message.type],
        "payload": payload,
        "status": status,
        "payload_format": "chat_message",
        "schema_version": 1,
    }


def from_storage_message(message_data):
    if message_data.get("payload_format") != "chat_message":
        raise ValueError("不支持的 payload_format")

    if message_data.get("schema_version") != 1:
        raise ValueError("不支持的 schema_version")

    payload = message_data["payload"]
    raw = payload.get("raw_langchain")

    if not isinstance(raw, dict):
        raise ValueError("缺少 Langchain 原始载荷，无法完整还原")
    
    role = TYPE_TO_ROLE.get(raw.get("type"))

    if role is None or role != message_data["role"]:
        raise ValueError("消息角色与原始载荷不一致")

    return messages_from_dict([raw])[0]
