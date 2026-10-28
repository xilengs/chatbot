import logging
from contextlib import closing

import gradio as gr

from history_display import to_chatbot_messages


def build_chat_ui(service, user_id):
    def get_choices():
        sessions = service.list_sessions(
            user_id=user_id,
            limit=100,
        )

        return [
            (
                f"{row['title'] or '未命名会话'}"
                f" · {row['session_id'][:8]}",
                row["session_id"],
            )
            for row in sessions
        ]

    def switch_session(session_id):
        choices = get_choices()
        allowed_ids = {
            value for label, value in choices
        }

        if session_id not in allowed_ids:
            raise gr.Error("会话不在当前列表中，请刷新页面。")

        history = service.get_session_history(
            session_id,
            reload=True,
        )
        messages = to_chatbot_messages(history.messages)

        return (
            gr.Radio(choices=choices, value=session_id),
            session_id,
            messages,
            f"当前会话：`{session_id}`",
            "",
        )

    def new_session():
        session_id = service.create_session(
            user_id=user_id,
            title="新会话",
            metadata={"source": "chat_v2_stream"},
        )
        return switch_session(session_id)

    def initialize_page():
        choices = get_choices()

        if choices:
            return switch_session(choices[0][1])

        return new_session()

    def respond(message, session_id):
        if not session_id:
            raise gr.Error("请先选择或新建会话。")

        if not isinstance(message, str) or not message.strip():
            raise gr.Error("请输入消息。")

        try:
            history = service.get_session_history(
                session_id,
                reload=True,
            )
            base_messages = to_chatbot_messages(history.messages)
            base_messages.append({
                "role": "user",
                "content": message,
            })

            with closing(
                service.stream_response(session_id, message)
            ) as response:
                # 先显示用户输入，并清空输入框。
                yield base_messages, ""

                for answer in response:
                    yield (
                        base_messages + [{
                            "role": "assistant",
                            "content": answer,
                        }],
                        gr.skip(),
                    )

        except Exception as error:
            logging.exception(
                "聊天请求失败，session_id=%s",
                session_id,
            )
            raise gr.Error(
                "本轮对话未能正常完成，请稍后重试。"
            ) from error

    with gr.Blocks(title="AI Agent 学习助手") as page:
        session_state = gr.State(value=None)

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
                )

            # 右侧：聊天区域
            with gr.Column(scale=4):
                gr.Markdown("### AI Agent 学习助手")

                current_session_info = gr.Markdown(
                    "正在加载会话……"
                )

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
            current_session_info,
            message_input,
        ]

        event_options = {
            "concurrency_id": "chat_operations",
            "concurrency_limit": 1,
        }

        page.load(
            fn=initialize_page,
            inputs=[],
            outputs=session_outputs,
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
            inputs=session_list,
            outputs=session_outputs,
            trigger_mode="always_last",
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
            ],
            outputs=[
                chatbot,
                message_input,
            ],
            trigger_mode="once",
            **event_options,
        )

        stop_button.click(
            fn=None,
            inputs=None,
            outputs=None,
            cancels=[send_event],
            queue=False,
        )

    return page