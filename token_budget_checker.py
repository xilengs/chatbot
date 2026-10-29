"""统一的文本计数、请求估算、预算判断和调用链拦截。

请求 JSON 的分词数只是估算，不保证等于或大于服务端实际用量。
当前仅支持文本消息和工具调用，不支持图片等多模态输入。
"""

import json
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, convert_to_openai_messages
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from tokenizers import Tokenizer


class ContextBudgetExceeded(ValueError):
    """输入估算值超过应用预算。"""


class TokenBudgetChecker:
    def __init__(
        self,
        tokenizer_path,
        *,
        context_window=128000,
        output_reserve=16000,
        safety_margin=4000,
    ):
        # 默认值是本项目的应用预算，不是模型官方容量。
        for name, value in {
            "context_window": context_window,
            "output_reserve": output_reserve,
            "safety_margin": safety_margin,
        }.items():
            if type(value) is not int:
                raise TypeError(f"{name} 必须是整数")
        if context_window <= 0 or output_reserve <= 0:
            raise ValueError("context_window 和 output_reserve 必须大于 0")
        if safety_margin < 0:
            raise ValueError("safety_margin 不能小于 0")
        if output_reserve + safety_margin >= context_window:
            raise ValueError("预留输出和安全余量占满了上下文容量")

        path = Path(tokenizer_path)
        if not path.is_file():
            raise FileNotFoundError(f"找不到 tokenizer 文件：{path}")
        self._tokenizer = Tokenizer.from_file(str(path))
        self._output_reserve = output_reserve
        self._input_limit = context_window - output_reserve - safety_margin

    @property
    def output_reserve(self):
        return self._output_reserve

    @property
    def input_limit(self):
        return self._input_limit

    def count_text(self, text):
        """仅计算文本本身，不含消息和工具的格式开销。"""
        if not isinstance(text, str):
            raise TypeError("text 必须是字符串")
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def estimate(self, input_data, *, tools=None):
        """接受字符串、单条消息或消息列表；字符串按一条用户消息处理。"""
        if isinstance(input_data, str):
            messages = [HumanMessage(content=input_data)]
        elif isinstance(input_data, BaseMessage):
            messages = [input_data]
        elif isinstance(input_data, (list, tuple)):
            messages = list(input_data)
        else:
            raise TypeError("input_data 必须是字符串、消息对象或消息列表")

        for message in messages:
            if not isinstance(message, BaseMessage):
                raise TypeError("消息列表中必须是 LangChain 消息对象")
            if not isinstance(message.content, str):
                raise ValueError("当前估算器只支持文本消息及工具调用")

        request_data = {"messages": convert_to_openai_messages(messages)}
        if tools:
            request_data["tools"] = [convert_to_openai_tool(tool) for tool in tools]
        request_text = json.dumps(
            request_data, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        )
        return self.count_text(request_text)

    def inspect(self, input_data, *, tools=None):
        """返回估算详情；超限本身不抛异常。"""
        estimated = self.estimate(input_data, tools=tools)
        return {
            "estimated_input_tokens": estimated,
            "input_limit": self.input_limit,
            "is_over_limit": estimated > self.input_limit,
            "remaining_input_tokens": max(0, self.input_limit - estimated),
            "overflow_tokens": max(0, estimated - self.input_limit),
        }

    def is_over_limit(self, input_data, *, tools=None):
        """True 表示超限，False 表示未超限；无效输入仍会抛异常。"""
        return self.inspect(input_data, tools=tools)["is_over_limit"]

    def require_fits(self, input_data, *, tools=None):
        """调用模型前使用：超限时抛异常，通过时返回估算详情。"""
        result = self.inspect(input_data, tools=tools)
        if result["is_over_limit"]:
            raise ContextBudgetExceeded(
                f"输入估算为 {result['estimated_input_tokens']} tokens，"
                f"当前最多允许 {self.input_limit} tokens"
            )
        return result

    def as_guard(self, *, tools=None):
        """返回可插入 prompt | guard | model 的节点。"""
        bound_tools = tuple(tools) if tools is not None else ()

        def check_before_model(prompt_value):
            self.require_fits(prompt_value.to_messages(), tools=bound_tools)
            return prompt_value

        return RunnableLambda(check_before_model)
