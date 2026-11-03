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

def to_storage_message(message, status="completed", *, estimated_input_tokens=None):
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
    
    if estimated_input_tokens is not None:
        if (
            type(estimated_input_tokens) is not int
            or estimated_input_tokens < 0
        ):
            raise ValueError("estimated_input_tokens 必须是非负整数")
        
        usage = getattr(message, "usage_metadata", None) or {}
        actual_input = usage.get("input_tokens")

        payload["token_usage"] = {
            "estimated_version": "request_json_v1",
            "estimated_input_tokens": estimated_input_tokens,
            "actual_input_tokens": actual_input,
            "actual_output_tokens": usage.get("output_tokens"),
            "actual_total_tokens": usage.get("total_tokens"),
            "input_difference":(
                actual_input - estimated_input_tokens
                if actual_input is not None else None
            ),
        }
        
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
