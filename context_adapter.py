# 将准备好的上下文转换为提示词所需的参数：提取摘要文本（无摘要时为空字符串），
# 按原有顺序合并各历史轮次的消息，返回 summary_text 和 chat_history。
def context_to_prompt_values(prepared_context):
    summary = prepared_context["summary"]

    summary_text = (
        summary["summary_text"]
        if summary is not None
        else ""
    )

    chat_history = []

    for turn in prepared_context["history_turns"]:
        chat_history.extend(turn["messages"])

    return {
        "summary_text": summary_text,
        "chat_history": chat_history,
    }