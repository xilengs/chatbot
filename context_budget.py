class ContextBudgetExceeded(ValueError):
    """输入超过允许的上下文预算。"""


class ContextBudget:
    def __init__(
        self,
        *,
        context_window,
        output_reserve,
        safety_margin,
        token_counter,
    ):
        values = {
            "context_window": context_window,
            "output_reserve": output_reserve,
            "safety_margin": safety_margin,
        }

        for name, value in values.items():
            if type(value) is not int:
                raise TypeError(f"{name} 必须是整数")

        if context_window <= 0:
            raise ValueError("context_window 必须大于 0")

        if output_reserve <= 0:
            raise ValueError("output_reserve 必须大于 0")

        if safety_margin < 0:
            raise ValueError("safety_margin 不能小于 0")

        if output_reserve + safety_margin >= context_window:
            raise ValueError("预留输出和安全余量占满了上下文容量")

        if not callable(token_counter):
            raise TypeError("token_counter 必须是可调用对象")

        self._context_window = context_window
        self._output_reserve = output_reserve
        self._safety_margin = safety_margin
        self._token_counter = token_counter

    def check(self, messages, *, tools):
        # 计数函数需要同时考虑消息和工具定义。
        input_tokens = self._token_counter(
            messages,
            tools=tools,
        )

        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("token_counter 必须返回非负整数")

        input_limit = (
            self._context_window
            - self._output_reserve
            - self._safety_margin
        )

        if input_tokens > input_limit:
            raise ContextBudgetExceeded(
                f"输入需要 {input_tokens} tokens，"
                f"当前最多允许 {input_limit} tokens"
            )

        return {
            "input_tokens": input_tokens,
            "input_limit": input_limit,
            "remaining_input_tokens": input_limit - input_tokens,
        }