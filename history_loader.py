import logging

from langchain_community.chat_message_histories import ChatMessageHistory

from message_converter import from_storage_message
from history_validation import validate_turn_messages

def load_session_turns(storage, session_id):
    """恢复已经完成且消息结构有效的轮次，保留原始轮次序号。"""
    records = storage.load_messages(session_id)

    records_by_turn = {}

    for record in records:
        turn_id = record["turn_id"]
        if turn_id not in records_by_turn:
            records_by_turn[turn_id] = []
        records_by_turn[turn_id].append(record)

    valid_turns = []

    for turn_id, turn_records in records_by_turn.items():
        # 未完成或失败的轮次不进入模型历史
        if any(
            row["turn_status"] != "completed"
            for row in turn_records
        ):
            continue

        try:
            if any(
                row["status"] != "completed"
                for row in turn_records
            ):
                raise ValueError("轮次中存在未完成的消息")

            actual_seq = [
                row["message_seq"] for row in turn_records
            ]
            expected_seq = list(range(1, len(turn_records) + 1))

            if actual_seq != expected_seq:
                raise ValueError("轮次消息序列不连续")

            messages = [
                from_storage_message(row) for row in turn_records
            ]

            validate_turn_messages(messages)

        except (KeyError, TypeError, ValueError) as error:
            logging.warning(
                "跳过无法恢复的轮次，turn_id=%s，原因：%s",
                turn_id, error
            )
            continue

        valid_turns.append({
            "turn_id": turn_id,
            "turn_seq": turn_records[0]["turn_seq"],
            "messages": messages,
        })

    return valid_turns


def load_session_history(storage, session_id):
    """兼容现有聊天程序：将有效轮次展开为消息历史。"""
    turns = load_session_turns(storage, session_id)
    history = ChatMessageHistory()

    for turn in turns:
        history.add_messages(turn["messages"])

    return history
