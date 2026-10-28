from langchain_core.runnables import RunnableLambda


def build_budget_guard(budget, *, tools):
    def check_before_model(prompt_value):
        messages = prompt_value.to_messages()

        budget.check(
            messages,
            tools=tools,
        )

        # 检查通过，原样传给后面的模型。
        return prompt_value

    return RunnableLambda(check_before_model)