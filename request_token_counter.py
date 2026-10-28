import json

from langchain_core.messages import convert_to_openai_messages
from langchain_core.utils.function_calling import convert_to_openai_tool


class RequestTokenEstimator:
    def __init__(self, text_counter):
        self._text_counter = text_counter

    def estimate(self, messages, *, tools):
        # 当前版本只支持文本消息及工具调用。
        for message in messages:
            if not isinstance(message.content, str):
                raise ValueError("当前估算器只支持文本消息")

        request_data = {
            "messages": convert_to_openai_messages(messages),
        }

        if tools:
            request_data["tools"] = [
                convert_to_openai_tool(tool)
                for tool in tools
            ]

        request_text = json.dumps(
            request_data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )

        return self._text_counter.count_text(request_text)