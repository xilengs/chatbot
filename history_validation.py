from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
)

def validate_turn_messages(messages):
    if len(messages) < 2:
        raise ValueError("一个完整轮次至少需要用户消息和最终回答")
    
    if not isinstance(messages[0], HumanMessage):
        raise TypeError("第一个消息必须是用户消息")

    if not isinstance(messages[-1], AIMessage):
        raise TypeError("最后一个消息必须是AI回答")
    
    pending_calls = {}
    seen_call_ids = set()

    for index, message in enumerate(messages[1:], start=1):
        if isinstance(message, AIMessage):
            if pending_calls:
                raise ValueError("工具结果尚未齐全，就出现下一条助手消息")
            
            if message.invalid_tool_calls:
                raise ValueError("消息中存在无法正确解析的工具调用")
            
            if not message.tool_calls and index != len(messages) - 1:
                raise ValueError("最终回答之后仍然存在其他消息")
            
            for call in message.tool_calls:
                call_id = call.get("id")

                if not isinstance(call_id, str) or not call_id:
                    raise ValueError("工具调用缺少有效的调用 ID")
                
                if call_id in seen_call_ids:
                    raise ValueError("同一轮次中存在重复的工具调用 ID")

                name = call.get("name")

                if not isinstance(name, str) or not name:
                    raise ValueError("工具调用缺少有效的工具名称")

                seen_call_ids.add(call_id)
                pending_calls[call_id] = name

        elif isinstance(message, ToolMessage):
            call_id = message.tool_call_id

            if call_id not in pending_calls:
                raise ValueError("工具结果没有对应的待完成请求")

            if (
                message.name is not None
                and message.name != pending_calls[call_id]
            ):
                raise ValueError("工具结果的名称与请求不一致")

            del pending_calls[call_id]

        else:
            raise ValueError("用户输入之后只能出现助手消息或工具结果")

    if pending_calls:
        raise ValueError("轮次结束时仍有工具请求缺少结果")