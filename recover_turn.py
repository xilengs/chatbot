import argparse

from app_config import load_settings
from chat_storage import ChatStorage


def main():
    parser = argparse.ArgumentParser(
        description=(
            "查看未结束轮次，或在执行程序已停止后，"
            "将指定轮次标记为 interrupted"
        )
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认执行该轮次的所有程序已停止，并执行状态修复",
    )
    args = parser.parse_args()

    if args.apply and not args.turn_id:
        parser.error("--apply 必须同时指定 --turn-id")

    db_config, _ = load_settings()
    storage = ChatStorage(db_config)

    turns = storage.load_turns(args.session_id)

    # 没有指定轮次：只列出该会话的 running 轮次。
    if not args.turn_id:
        running = [
            turn for turn in turns
            if turn["status"] == "running"
        ]

        for turn in running:
            print(
                f"第 {turn['turn_seq']} 轮："
                f"{turn['turn_id']}，状态：running"
            )

        if not running:
            print(
                "未找到 running 轮次；"
                "也可能是会话不存在或尚无轮次。"
            )

        return

    # 确保指定轮次确实属于这个会话。
    target = next(
        (
            turn for turn in turns
            if turn["turn_id"] == args.turn_id
        ),
        None,
    )

    if target is None:
        raise SystemExit(
            "指定轮次不属于该会话，或轮次不存在。"
        )

    print(
        f"目标：第 {target['turn_seq']} 轮，"
        f"当前状态：{target['status']}"
    )

    if target["status"] != "running":
        print("该轮次已经结束，无需修复。")
        return

    if not args.apply:
        print(
            "当前仅预览。确认执行该轮次的程序已停止后，"
            "加 --apply 执行。"
        )
        return

    storage.finish_turn(
        args.turn_id,
        status="interrupted",
        error_message=(
            "人工恢复：已确认原执行程序停止，"
            "结束遗留的 running 轮次"
        ),
    )

    print(
        "状态已更新为 interrupted；"
        "已保存的原始消息仍保留。"
    )


if __name__ == "__main__":
    main()