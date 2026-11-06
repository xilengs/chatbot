import logging
from copy import deepcopy
from collections import OrderedDict
from time import sleep
from uuid import uuid4

from mysql.connector import Error as MySQLError, errorcode

from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
    message_chunk_to_message,
    message_to_dict,
)

from history_loader import load_session_history, restore_session_turns
from history_display import to_chatbot_messages
from message_converter import to_storage_message
from context_adapter import context_to_prompt_values
from token_budget_checker import ContextBudgetExceeded
from session_title_generator import fallback_title, normalize_title


class ChatService:
    def __init__(
        self,
        storage,
        chain,
        tools_by_name,
        *,
        context_manager,
        context_prompt,
        context_checker,
        execution_config=None,
        keep_recent_turns=2,
        title_generator=None,
    ):
        if execution_config is not None and not isinstance(
            execution_config, dict
        ):
            raise TypeError("execution_config 必须是字典或 None")

        if type(keep_recent_turns) is not int or keep_recent_turns < 1:
            raise ValueError("keep_recent_turns 必须是正整数")

        self._execution_config = (
            deepcopy(execution_config)
            if execution_config is not None
            else {}
        )
        self._keep_recent_turns = keep_recent_turns
        self._storage = storage
        self._chain = chain
        self._tools_by_name = tools_by_name
        self._history_cache = {}
        self._title_generator = title_generator
        self._title_updates = OrderedDict()

        self._context_manager = context_manager
        self._context_prompt = context_prompt
        self._context_checker = context_checker


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


    def get_history_page(self, session_id, *, before_seq=None):
        records, cursor = self._storage.load_message_page(
            session_id, before_seq=before_seq,
        )
        turns = restore_session_turns(records)
        messages = [message for turn in turns for message in turn["messages"]]
        return to_chatbot_messages(messages), cursor


    def get_title_update(self, session_id):
        return self._title_updates.get(session_id)


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
        history = self._history_cache.get(session_id)
        full_answer = ""
        turn_messages = []
        context_cache = {}

        execution_config = deepcopy(self._execution_config)
        execution_config["keep_recent_turns"] = self._keep_recent_turns

        # 创建轮次，并在调用模型前保存用户输入
        turn_id = self._start_turn_with_retry(
            session_id,
            execution_config=execution_config,
        )

        try:
            user_message_obj = HumanMessage(content=user_message)
            self._save_message_with_retry(
                turn_id, 
                to_storage_message(user_message_obj),
            )

            self._generate_session_title(session_id, turn_id, user_message)

            while True:
                response = None
                estimated_input_tokens = None
                try:
                    model_input = self._prepare_model_inputs(
                        session_id,
                        user_message=user_message,
                        turn_messages=turn_messages,
                        context_cache=context_cache,
                    )

                    request_messages = self._context_prompt.invoke(model_input).to_messages()
                    estimated_input_tokens = (
                        self._context_checker.estimate(
                            request_messages, 
                            tools=list(self._tools_by_name.values()),
                            )
                    )

                    for chunk in self._chain.stream(model_input):
                        # 工具名和参数也会分段返回，需合并整轮消息后再执行。
                        response = chunk if response is None else response + chunk
                        if chunk.content:
                            full_answer += chunk.content
                            yield full_answer
                    
                    self._validate_model_response(response)

                except (Exception, GeneratorExit):
                    # 流未正常结束, 但已经收到了一部分消息
                    if response is not None:
                        try:
                            partial_message = message_chunk_to_message(response)
                            partial_data = to_storage_message(
                                partial_message,
                                status="partial",
                                estimated_input_tokens=estimated_input_tokens,
                            )

                            # 额外保留累计的原始 chunk 数据
                            partial_data["payload"]["raw_langchain_chunks"] = (message_to_dict(response))
                            self._save_message_with_retry(turn_id, partial_data)
                        
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

                self._save_message_with_retry(
                    turn_id,
                    to_storage_message(
                        ai_message,
                        estimated_input_tokens=estimated_input_tokens,
                    ),
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
                    self._save_message_with_retry(
                        turn_id,
                        to_storage_message(tool_message),
                    )

                    turn_messages.append(tool_message)

        except GeneratorExit:
            # 尝试将原始错误记录到所属轮次
            try: 
                self._finish_turn_with_retry(
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
                self._finish_turn_with_retry(
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
            self._finish_turn_with_retry(
                turn_id,
                status="completed"
            )

            # 流式输出结束后写回历史
            if history is not None:
                history.add_message(user_message_obj)
                history.add_messages(turn_messages)
    

    def _generate_session_title(self, session_id, turn_id, user_message):
        if self._title_generator is None:
            return
        # 以数据库轮次为准，避免加载历史时过滤失败轮次造成重复命名。
        try:
            if not self._storage.needs_session_title(session_id, turn_id):
                return
            try:
                title = normalize_title(self._title_generator(user_message))
            except Exception:
                logging.exception("生成会话标题失败，使用输入摘录，session_id=%s", session_id)
                title = fallback_title(user_message)
            changed = self._retry_storage_call(
                lambda: self._storage.update_initial_session_title(
                    session_id, turn_id, title,
                )
            )
            if changed:
                self._title_updates[session_id] = title
                self._title_updates.move_to_end(session_id)
                if len(self._title_updates) > 100:
                    self._title_updates.popitem(last=False)
        except Exception:
            # 辅助功能失败不能中断回复或改变轮次状态。
            logging.exception("保存会话标题失败，session_id=%s", session_id)


    def _prepare_model_inputs(
        self,
        session_id,
        user_message,
        turn_messages,
        context_cache=None,
    ):
        def to_inputs(prepared):
            return {
                **context_to_prompt_values(prepared),
                "user_message": user_message,
                "turn_messages": turn_messages,
            }

        def context_fits(prepared):
            messages = self._context_prompt.invoke(
                to_inputs(prepared)
            ).to_messages()

            return not self._context_checker.is_over_limit(
                messages,
                tools=list(self._tools_by_name.values()),
            )

        # 暂时不放入旧摘要和历史原文，只检查本轮及固定开销。
        current_only = to_inputs({
            "summary": None,
            "history_turns": [],
        })

        current_messages = self._context_prompt.invoke(
            current_only
        ).to_messages()

        try:
            self._context_checker.require_fits(
                current_messages,
                tools=list(self._tools_by_name.values()),
            )
        except ContextBudgetExceeded as error:
            if turn_messages:
                hint = (
                    "本轮消息（包含工具调用和工具结果）与固定提示词"
                    "已超出输入预算；需要缩小工具返回内容或调整预算。"
                )
            else:
                hint = (
                    "当前输入与固定提示词、工具定义已超出输入预算；"
                    "请缩短输入，或检查提示词、工具定义及预算配置。"
                )

            raise ContextBudgetExceeded(
                f"{hint} {error}"
            ) from error

        prepared = context_cache.get("prepared") if context_cache is not None else None
        # 工具调用后的下一次请求复用本轮上下文；超预算时仍重新摘要。
        if prepared is None or not context_fits(prepared):
            prepared = self._context_manager.prepare_context(
                session_id,
                keep_recent_turns=self._keep_recent_turns,
                context_fits=context_fits,
            )
            if context_cache is not None:
                context_cache["prepared"] = prepared

        logging.info(
            "上下文准备完成，session_id=%s，summary_status=%s",
            session_id,
            prepared["summary_status"],
        )

        model_inputs = to_inputs(prepared)

        final_messages = self._context_prompt.invoke(
            model_inputs
        ).to_messages()

        try:
            self._context_checker.require_fits(
                final_messages,
                tools=list(self._tools_by_name.values()),
            )
        except ContextBudgetExceeded as error:
            if prepared["summary_status"] == "fallback":
                hint = (
                    "摘要更新失败，保留的原文仍超出输入预算，"
                    "本轮无法继续。"
                )
            else:
                hint = (
                    "上下文处理后仍超出输入预算，"
                    "请缩短输入或调整历史保留策略、预算配置。"
                )

            raise ContextBudgetExceeded(
                f"{hint} {error}"
            ) from error

        return model_inputs
    
    @staticmethod
    def _validate_model_response(response):
        if response is None:
            raise RuntimeError("模型没有返回任何消息")
        
        reason = response.response_metadata.get("finish_reason")

        if reason not in ("stop", "tool_calls"):
            raise RuntimeError(f"模型响应未正常完成，finish_reason={reason!r}")
        
        if response.invalid_tool_calls:
            raise RuntimeError("模型返回了无法解析的工具调用")
        
        if reason == "tool_calls":
            if not response.tool_calls:
                raise RuntimeError("结束原因是工具调用，但没有有效的工具请求")
        else:
            if response.tool_calls:
                raise RuntimeError("结束原因是 stop，但响应仍包含工具调用")
            
            if not isinstance(response.content, str) or not response.content.strip():
                raise RuntimeError("模型正常结束，但没有返回有效的文本回答")
            

    def _retry_storage_call(self, operation):
        retryable_errors = {
            errorcode.ER_LOCK_WAIT_TIMEOUT,
            errorcode.ER_LOCK_DEADLOCK,
            errorcode.CR_SERVER_GONE_ERROR,
            errorcode.CR_SERVER_LOST,
            errorcode.CR_SERVER_LOST_EXTENDED,
        }

        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                return operation()
            except MySQLError as error:
                if (
                    error.errno not in retryable_errors
                    or attempt == max_attempts
                ):
                    raise

                delay = 0.2 * (2 ** (attempt - 1))

                logging.warning(
                    "数据库操作失败，errno=%s，"
                    "%.1f 秒后进行第 %s/%s 次尝试",
                    error.errno,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                sleep(delay)


    def _save_message_with_retry(self, turn_id, message_data):
        # 同一次保存操作，只生成一次 ID，并固定要保存的数据。
        message_id = str(uuid4())
        data_snapshot = deepcopy(message_data)

        return self._retry_storage_call(
            lambda: self._storage.save_message(
                turn_id,
                data_snapshot,
                message_id=message_id,
            )
        )


    def _finish_turn_with_retry(
        self,
        turn_id,
        status,
        error_message=None,
    ):
        return self._retry_storage_call(
            lambda: self._storage.finish_turn(
                turn_id,
                status=status,
                error_message=error_message,
            )
        )
    

    def _start_turn_with_retry(self, session_id, execution_config=None):
        # 一次创建操作，只生成一次 ID。
        turn_id = str(uuid4())
        config_snapshot = deepcopy(execution_config)

        try:
            return self._retry_storage_call(
                lambda: self._storage.start_turn(
                    session_id,
                    execution_config=config_snapshot,
                    turn_id=turn_id,
                )
            )
        except Exception:
            logging.exception(
                "无法确认轮次创建结果，session_id=%s，turn_id=%s",
                session_id,
                turn_id,
            )
            raise


