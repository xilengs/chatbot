import logging

from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
    message_chunk_to_message,
    message_to_dict,
)

from history_loader import load_session_history
from message_converter import to_storage_message


class ChatService:
    def __init__(self, storage, chain, tools_by_name):
        self._storage = storage
        self._chain = chain
        self._tools_by_name = tools_by_name
        self._history_cache = {}

    def get_session_history(self, session_id, *, reload=False):
        if reload or session_id not in self._history_cache:
            history = load_session_history(
                self._storage,
                session_id,
            )
            self._history_cache[session_id] = history

        return self._history_cache[session_id]

    def create_session(self, *, user_id, title="新会话", metadata=None):
        return self._storage.create_session(
            user_id=user_id,
            title=title,
            metadata=metadata,
        )

    def list_sessions(self, user_id, limit=100):
        return self._storage.list_sessions(
            user_id=user_id,
            limit=limit,
        )

    def stream_response(self, session_id: str, user_message: str):
        """
        完整消息逐条保存
        正常完成时标记为 completed, 普通异常时尝试标记为 failed
        流式生成回复：逐段 yield 给前端。
        全部生成完毕后再把本轮对话写入历史（避免存入残缺文本）。
        """
        history = self.get_session_history(session_id)
        full_answer = ""
        turn_messages = []

        # 创建轮次，并在调用模型前保存用户输入
        turn_id = self._storage.start_turn(session_id)

        try:
            user_message_obj = HumanMessage(content=user_message)
            self._storage.save_message(
                turn_id, 
                to_storage_message(user_message_obj),
            )

            while True:
                response = None
                try:
                    for chunk in self._chain.stream({
                        "chat_history": history.messages,
                        "user_message": user_message,
                        "turn_messages": turn_messages,
                    }):
                        # 工具名和参数也会分段返回，需合并整轮消息后再执行。
                        response = chunk if response is None else response + chunk
                        if chunk.content:
                            full_answer += chunk.content
                            yield full_answer

                    if (
                        response is not None
                        and response.response_metadata.get(
                            "finish_reason",
                        ) == "length"
                    ):
                        raise RuntimeError("模型输出达到长度限制，本次回复未完整生成")
                
                except (Exception, GeneratorExit):
                    # 流未正常结束, 但已经收到了一部分消息
                    if response is not None:
                        try:
                            partial_message = message_chunk_to_message(response)
                            partial_data = to_storage_message(
                                partial_message,
                                status="partial",
                            )

                            # 额外保留累计的原始 chunk 数据
                            partial_data["payload"]["raw_langchain_chunks"] = (message_to_dict(response))
                            self._storage.save_message(turn_id, partial_data)
                        
                        except Exception:
                            logging.exception(
                                "保存部分消息失败，turn_id=%s",
                                turn_id,
                            )
                    
                    # 继续交给外层异常处理， 尝试将轮次标记为 failed
                    raise

                if response is None:
                    raise RuntimeError("模型没有返回任何消息")

                # 本次模型输出结束：合并结果转换为消息，再保存
                ai_message = message_chunk_to_message(response)

                self._storage.save_message(
                    turn_id,
                    to_storage_message(ai_message),
                )

                turn_messages.append(ai_message)

                if not ai_message.tool_calls:
                    break

                for tool_call in ai_message.tool_calls:
                    result = self._tools_by_name[tool_call["name"]].invoke(tool_call["args"])

                    tool_message = ToolMessage(
                        content=result,
                        tool_call_id=tool_call["id"],
                        name=tool_call["name"],
                    )

                    # 每个工具执行结束，就保存对应结果
                    self._storage.save_message(
                        turn_id,
                        to_storage_message(tool_message),
                    )

                    turn_messages.append(tool_message)

        except GeneratorExit:
            # 尝试将原始错误记录到所属轮次
            try: 
                self._storage.finish_turn(
                    turn_id,
                    status="interrupted",
                    error_message="GeneratorExit: 生成器被关闭",
                )

            except Exception:
                # 记录失败状态失败
                logging.exception(
                    "记录轮次中断状态失败, turn_id: %s",
                    turn_id,
                )
            # 保留并继续抛出原始执行异常
            raise

        except Exception as error:
            # 尝试将原始错误记录到所属轮次
            try: 
                self._storage.finish_turn(
                    turn_id,
                    status="failed",
                    error_message=f"{type(error).__name__}:{error}",
                )
            except Exception:
                # 记录失败状态失败
                logging.exception(
                    "记录轮次失败状态发生异常, turn_id: %s",
                    turn_id,
                )
            # 保留并继续抛出原始执行异常
            raise
        
        else:
            # 最终回答已保存，标记本轮正常结束
            self._storage.finish_turn(
                turn_id,
                status="completed"
            )

            # 流式输出结束后写回历史
            history.add_message(user_message_obj)
            history.add_messages(turn_messages)