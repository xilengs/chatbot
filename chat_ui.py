import logging
from contextlib import closing

import gradio as gr

from token_budget_checker import ContextBudgetExceeded

SESSION_LIST_LIMIT = 20
CHAT_CSS = """
#session-list .wrap {
    flex-direction: column;
    align-items: stretch;
}
#session-list label:has(input[type="radio"]) {
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    min-width: 0;
}
#session-list label:has(input[type="radio"]) span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}
"""


def build_chat_ui(service, user_id):
    def get_choices():
        sessions = service.list_sessions(
            user_id=user_id,
            limit=SESSION_LIST_LIMIT,
        )

        return [
            (
                row['title'] or '未命名会话',
                row["session_id"],
            )
            for row in sessions
        ]

    def switch_session(session_id, choices=None):
        if choices is None:
            choices = get_choices()
        allowed_ids = {
            value for label, value in choices
        }

        if session_id not in allowed_ids:
            raise gr.Error("会话不在当前列表中，请刷新页面。")

        # 先把标题和选中状态送到浏览器，再进行较慢的消息查询。
        yield (
            gr.Radio(choices=choices, value=session_id),
            session_id,
            [],
            "正在加载此会话的最近消息……",
            gr.Textbox(value="", interactive=False),
            choices,
            None,
            gr.Button(visible=False),
            False,
        )
        try:
            messages, cursor = service.get_history_page(session_id)
        except Exception as error:
            logging.exception("加载会话消息失败，session_id=%s", session_id)
            yield (
                gr.skip(), gr.skip(), gr.skip(), "消息加载失败，请重新选择会话重试。",
                gr.Textbox(interactive=True), gr.skip(), None, gr.Button(visible=False),
                False,
            )
            raise gr.Error("读取历史消息失败，请稍后重试。") from error
        yield (
            gr.skip(), gr.skip(), messages, "",
            gr.Textbox(interactive=True), gr.skip(), cursor,
            gr.Button(visible=cursor is not None),
            False,
        )

    def new_session():
        session_id = service.create_session(
            user_id=user_id,
            title="新会话",
            metadata={"source": "chat_v2_stream"},
        )
        # 刚创建的会话已知为空，无需查询历史。
        choices = get_choices()
        return (
            gr.Radio(choices=choices, value=session_id), session_id, [],
            "", gr.Textbox(value="", interactive=True),
            choices, None, gr.Button(visible=False), False,
        )

    def initialize_page():
        choices = get_choices()

        if choices:
            yield from switch_session(choices[0][1], choices)
        else:
            yield new_session()

    def refresh_session_list(session_id, choices):
        title = service.get_title_update(session_id)
        if not title or not any(
            value == session_id and label != title for label, value in choices
        ):
            return gr.skip(), gr.skip()
        updated = [
            (title if value == session_id else label, value)
            for label, value in choices
        ]
        return gr.Radio(choices=updated, value=session_id), updated

    def load_older(session_id, cursor, visible_messages):
        if cursor is None:
            return gr.skip(), gr.skip(), gr.Button(visible=False)
        messages, next_cursor = service.get_history_page(session_id, before_seq=cursor)
        return (
            messages + (visible_messages or []), next_cursor,
            gr.Button(visible=next_cursor is not None),
        )

    def respond(message, session_id, visible_messages):
        if not session_id:
            raise gr.Error("请先选择或新建会话。")

        if not isinstance(message, str) or not message.strip():
            raise gr.Error("请输入消息。")

        # 临时提示不加入 base_messages，也不传入 service 或数据库。
        base_messages = list(visible_messages or [])
        base_messages.append({"role": "user", "content": message})
        displayed_messages = base_messages
        waiting = True
        yield base_messages + [{"role": "assistant", "content": "思考中…"}], "", True

        try:
            with closing(
                service.stream_response(session_id, message)
            ) as response:
                for answer in response:
                    if not answer:
                        continue
                    waiting = False
                    displayed_messages = base_messages + [{
                        "role": "assistant", "content": answer,
                    }]
                    yield displayed_messages, gr.skip(), False
            if waiting:
                yield base_messages, gr.skip(), False

        except ContextBudgetExceeded as error:
            logging.warning(
                "上下文预算不足，session_id=%s：%s",
                session_id,
                error,
            )

            yield displayed_messages, gr.skip(), False
            raise gr.Error(str(error)) from error
        
        except Exception as error:
            logging.exception(
                "聊天请求失败，session_id=%s",
                session_id,
            )
            yield displayed_messages, gr.skip(), False
            raise gr.Error(
                "本轮对话未能正常完成，请稍后重试。"
            ) from error

    def clear_thinking(visible_messages, thinking):
        # 依靠本次请求状态识别提示，避免误删内容恰好为“思考中…”的真实回复。
        if thinking:
            return list(visible_messages or [])[:-1], False
        return gr.skip(), False

    with gr.Blocks(title="AI Agent 学习助手") as page:
        session_state = gr.State(value=None)
        choices_state = gr.State(value=[])
        history_cursor = gr.State(value=None)
        thinking_state = gr.State(value=False)

        with gr.Row():
            # 左侧：会话列表
            with gr.Column(scale=1, min_width=240):
                gr.Markdown("### 会话")

                new_button = gr.Button(
                    "＋ 新建会话",
                    variant="primary",
                )

                session_list = gr.Radio(
                    choices=[],
                    label="历史会话",
                    interactive=True,
                    elem_id="session-list",
                )

            # 右侧：聊天区域
            with gr.Column(scale=4):
                gr.Markdown("### AI Agent 学习助手")

                session_status = gr.Markdown(
                    "正在加载会话……"
                )

                older_button = gr.Button("加载更早消息", visible=False)

                chatbot = gr.Chatbot(
                    height=600,
                    buttons=["copy"],
                )

                message_input = gr.Textbox(
                    label="消息",
                    placeholder="输入消息，按回车发送",
                    lines=1,
                )

                with gr.Row():
                    send_button = gr.Button(
                        "发送",
                        variant="primary",
                    )
                    stop_button = gr.Button("停止生成")

        session_outputs = [
            session_list,
            session_state,
            chatbot,
            session_status,
            message_input,
            choices_state,
            history_cursor,
            older_button,
            thinking_state,
        ]

        event_options = {
            "concurrency_id": "chat_operations",
            "concurrency_limit": 1,
        }

        page.load(
            fn=initialize_page,
            inputs=[],
            outputs=session_outputs,
            show_progress="hidden",
            **event_options,
        )

        new_button.click(
            fn=new_session,
            inputs=[],
            outputs=session_outputs,
            **event_options,
        )

        session_list.input(
            fn=switch_session,
            inputs=[session_list, choices_state],
            outputs=session_outputs,
            trigger_mode="always_last",
            show_progress="hidden",
            **event_options,
        )

        send_event = gr.on(
            triggers=[
                message_input.submit,
                send_button.click,
            ],
            fn=respond,
            inputs=[
                message_input,
                session_state,
                chatbot,
            ],
            outputs=[
                chatbot,
                message_input,
                thinking_state,
            ],
            trigger_mode="once",
            show_progress="hidden",
            **event_options,
        )

        send_event.then(
            fn=refresh_session_list,
            inputs=[session_state, choices_state],
            outputs=[session_list, choices_state],
            show_progress="hidden",
            **event_options,
        )

        stop_button.click(
            fn=clear_thinking,
            inputs=[chatbot, thinking_state],
            outputs=[chatbot, thinking_state],
            cancels=[send_event],
            queue=False,
            show_progress="hidden",
        ).then(
            fn=refresh_session_list,
            inputs=[session_state, choices_state],
            outputs=[session_list, choices_state],
            show_progress="hidden",
            **event_options,
        )

        older_button.click(
            fn=load_older,
            inputs=[session_state, history_cursor, chatbot],
            outputs=[chatbot, history_cursor, older_button],
            **event_options,
        )

    return page
