import json
from uuid import uuid4

import mysql.connector

class ChatStorage:
    def __init__(self, db_config):
        self._db_config = {
            **db_config,
            "charset": "utf8mb4",
            "time_zone": "+00:00",
            "connection_timeout": 5,
            "autocommit": False,
        }
    

    def _connect(self):
        return mysql.connector.connect(**self._db_config)
    

    def create_session(self, user_id=None, title=None, metadata=None):
        session_id = str(uuid4())
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")
        
        metadata_json = (
            json.dumps(metadata, ensure_ascii=False, allow_nan=False)
            if metadata is not None
            else None
        )

        with self._connect() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO sessions
                            (session_id, user_id, title, metadata)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (session_id, user_id, title, metadata_json),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        
        return session_id
    

    def start_turn(self, session_id, execution_config=None):
        if execution_config is not None and not isinstance(execution_config, dict):
            raise TypeError("execution_config must be a dictionary or None")
        
        execution_config_json = json.dumps(
            execution_config,
            ensure_ascii=False,
            allow_nan=False,
        ) if execution_config is not None else None

        turn_id = str(uuid4())

        with self._connect() as connection:
            try:
                with connection.cursor(dictionary=True) as cursor:
                    # 锁定所属 session,同时确认 session 存在
                    cursor.execute(
                        """
                        SELECT session_id 
                        FROM sessions
                        WHERE session_id = %s
                        FOR UPDATE
                        """,
                        (session_id,),
                    )

                    if cursor.fetchone() is None:
                        raise ValueError(f"会话不存在：{session_id}")
                    
                    # 计算这个会话的下一个轮次序号
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(turn_seq), 0) + 1
                            AS next_turn_seq
                        FROM turns
                        WHERE session_id = %s
                        """,
                        (session_id,),
                    )
                    turn_seq = cursor.fetchone()["next_turn_seq"]

                    # status 和 started_at 使用表中设置的默认值
                    cursor.execute(
                        """
                        INSERT INTO turns
                        (turn_id, session_id, turn_seq, execution_config)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (turn_id, session_id, turn_seq, execution_config_json),
                    )

                    # 创建轮次也算是一次会话活动。
                    cursor.execute(
                        """
                        UPDATE sessions
                        SET updated_at = CURRENT_TIMESTAMP(6)
                        WHERE session_id = %s
                        """,
                        (session_id,),
                    )

                connection.commit()
            
            except Exception:
                connection.rollback()
                raise

        return turn_id
    

    def save_message(self, turn_id, message_data):
        if not isinstance(message_data, dict):
            raise TypeError("message_data must be a dictionary or None")
        
        role = message_data.get("role")
        payload = message_data.get("payload")
        status = message_data.get("status", "completed")

        if role not in ("system", "user", "assistant", "tool"):
            raise ValueError("role must be either 'system' or 'user' or 'assistant' or 'tool'")
        
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        
        if status not in ("completed", "partial"):
            raise ValueError("status must be either 'completed' or 'partial'")
        
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        )
        message_id = str(uuid4())

        with self._connect() as connection:
            try:
                with connection.cursor(dictionary=True) as cursor:
                    # 锁定轮次， 检查其是否存在以及是否仍在运行
                    cursor.execute(
                        """
                        SELECT session_id, status
                        FROM turns
                        WHERE turn_id = %s
                        FOR UPDATE
                        """,
                        (turn_id,),
                    )
                    turn = cursor.fetchone()

                    if turn is None:
                        raise ValueError(f"轮次不存在：{turn_id}")
                    
                    if turn["status"] != "running":
                        raise ValueError(f"只能向 running 状态的轮次添加消息")
                    
                    # 为当前轮次分配下一个消息序列
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(message_seq), 0) + 1
                            AS next_message_seq
                        FROM messages
                        WHERE turn_id = %s
                        """,
                        (turn_id,),
                    )
                    message_seq = cursor.fetchone()["next_message_seq"]   

                    cursor.execute(
                        """
                        INSERT INTO messages
                        (message_id, turn_id, message_seq, role, payload, status)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (message_id, turn_id, message_seq, role, payload_json, status),
                    )

                    cursor.execute(
                        """
                        UPDATE sessions
                        SET updated_at = CURRENT_TIMESTAMP(6)
                        WHERE session_id = %s
                        """,
                        (turn["session_id"],),
                    )

                connection.commit()
            
            except Exception:
                connection.rollback()
                raise

        return message_id
    

    def finish_turn(self, turn_id, status, error_message=None):
        if status not in ("completed", "failed", "interrupted"):
            raise ValueError("status must be either 'completed' or 'failed' or 'interrupted'")
        
        if error_message is not None and not isinstance(error_message, str):
            raise TypeError("error_message must be a string or None")
        
        if status == "completed" and error_message is not None:
            raise ValueError("正常的轮次不应设置 error_message")
        
        with self._connect() as connection:
            try:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT session_id, status
                        FROM turns
                        WHERE turn_id = %s
                        FOR UPDATE
                        """,
                        (turn_id,),
                    )
                    turn = cursor.fetchone()

                    if turn is None:
                        raise ValueError(f"轮次不存在：{turn_id}")
                    if turn["status"] != "running":
                        raise ValueError(f"轮次已经结束，当前状态：{turn['status']}")
                    
                    cursor.execute(
                        """
                        UPDATE turns
                        SET status = %s,
                        ended_at = CURRENT_TIMESTAMP(6),
                        error_message = %s
                        WHERE turn_id = %s
                        """,
                        (status, error_message, turn_id,),
                    )

                    cursor.execute(
                        """
                        UPDATE sessions
                        SET updated_at = CURRENT_TIMESTAMP(6)
                        WHERE session_id = %s
                        """,
                        (turn["session_id"],),
                    )

                connection.commit()
            
            except Exception:
                connection.rollback()
                raise
    

    def load_messages(self, session_id):
        with self._connect() as connection:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    """
                    SELECT
                        m.message_id,
                        m.turn_id,
                        t.turn_seq,
                        t.status AS turn_status,
                        m.message_seq,
                        m.role,
                        m.payload,
                        m.payload_format,
                        m.schema_version,
                        m.status,
                        m.created_at
                    FROM messages AS m
                    INNER JOIN turns AS t
                        ON m.turn_id = t.turn_id
                    WHERE t.session_id = %s
                    ORDER BY t.turn_seq ASC, m.message_seq ASC      
                    """,
                    (session_id,),
                )
                messages =cursor.fetchall()

        for message in messages:
            message["payload"] = json.loads(message["payload"])

        return messages
    
    
    def list_sessions(self, user_id, limit=100):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id 必须是非空字符串")
        
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit 必须是1到100之间的整数")
        
        with self._connect() as connection:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    """
                    SELECT session_id, user_id, title, created_at, updated_at
                    FROM sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC, session_id DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                sessions = cursor.fetchall()

        return sessions


    def save_summary(
        self,
        session_id,
        *,
        covered_through_turn_seq,
        summary_text,
        strategy_version,
    ):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id 必须是非空字符串")

        if (
            type(covered_through_turn_seq) is not int
            or not 1 <= covered_through_turn_seq <= 4294967295
        ):
            raise ValueError("覆盖轮次必须是 INT UNSIGNED 范围内的正整数")

        if not isinstance(summary_text, str) or not summary_text.strip():
            raise ValueError("摘要必须是非空字符串")

        if len(summary_text.encode("utf-8")) > 65535:
            raise ValueError("摘要超过 TEXT 字段的字节容量")

        if (
            not isinstance(strategy_version, str)
            or not strategy_version.strip()
            or len(strategy_version) > 64
        ):
            raise ValueError("策略版本必须是长度不超过 64 的非空字符串")

        summary_id = str(uuid4())

        with self._connect() as connection:
            try:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT turn_seq, status
                        FROM turns
                        WHERE session_id = %s
                          AND turn_seq <= %s
                        ORDER BY turn_seq ASC
                        FOR UPDATE
                        """,
                        (session_id, covered_through_turn_seq),
                    )
                    covered_turns = cursor.fetchall()
                    

                    if (
                        not covered_turns 
                        or covered_turns[-1]["turn_seq"] != covered_through_turn_seq
                    ):
                        raise ValueError("指定会话中的摘要边界轮次不存在")
                    
                    if covered_turns[-1]["status"] != "completed":
                        raise ValueError("摘要边界必须是已完成的轮次")

                    running_turn = next(
                        (
                            turn
                            for turn in covered_turns
                            if turn["status"] == "running"
                        ),
                        None,
                    )

                    if running_turn is not None:
                        raise ValueError(
                            f"第 {running_turn['turn_seq']} 轮尚未结束，"
                            "不能将摘要边界推进到它之后"
                        )

                    cursor.execute(
                        """
                        INSERT INTO summaries (
                            summary_id,
                            session_id,
                            covered_through_turn_seq,
                            summary_text,
                            strategy_version
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            summary_id,
                            session_id,
                            covered_through_turn_seq,
                            summary_text,
                            strategy_version,
                        ),
                    )

                connection.commit()

            except Exception:
                connection.rollback()
                raise

        return summary_id


    def load_latest_summary(self, session_id, *, strategy_version):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id 必须是非空字符串")

        if (
            not isinstance(strategy_version, str)
            or not strategy_version.strip()
            or len(strategy_version) > 64
        ):
            raise ValueError("策略版本必须是长度不超过 64 的非空字符串")

        with self._connect() as connection:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    """
                    SELECT
                        summary_id,
                        session_id,
                        covered_through_turn_seq,
                        summary_text,
                        strategy_version,
                        created_at
                    FROM summaries
                    WHERE session_id = %s
                      AND strategy_version = %s
                    ORDER BY
                        covered_through_turn_seq DESC,
                        created_at DESC,
                        summary_id DESC
                    LIMIT 1
                    """,
                    (session_id, strategy_version),
                )

                summary = cursor.fetchone()

        return summary
    

    def load_turns(self, session_id):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id 必须是非空字符串")

        with self._connect() as connection:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(
                    """
                    SELECT
                        turn_id,
                        turn_seq,
                        status
                    FROM turns
                    WHERE session_id = %s
                    ORDER BY turn_seq ASC
                    """,
                    (session_id,),
                )

                turns = cursor.fetchall()

        return turns
    
