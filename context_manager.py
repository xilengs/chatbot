import logging

class ContextManager:
    # 初始化存储、轮次加载器、摘要策略版本及可选摘要函数，并校验摘要函数是否可调用。
    def __init__(self, storage, *, turn_loader, strategy_version, summarizer=None):
        if summarizer is not None and not callable(summarizer):
            raise TypeError("summarizer 必须是可调用对象或 None")
        
        self._storage = storage
        self._turn_loader = turn_loader
        self._strategy_version = strategy_version
        self._summarizer = summarizer


    # 校验摘要覆盖边界，将已完成且未被摘要覆盖的轮次划分为待摘要和近期保留部分；
    # 待摘要范围不越过首个运行中的轮次，返回规划结果而不生成或保存摘要。
    def plan_context(self, session_id, *, keep_recent_turns=2):
        if type(keep_recent_turns) is not int or keep_recent_turns < 1:
            raise ValueError("keep_recent_turns 必须是正整数")

        summary = self._storage.load_latest_summary(
            session_id,
            strategy_version=self._strategy_version,
        )

        # turn_loader 应返回按 turn_seq 升序排列的有效完整轮次。
        # turns = self._turn_loader(
        #     self._storage,
        #     session_id,
        # )

        covered_seq = (
            summary["covered_through_turn_seq"]
            if summary is not None
            else 0
        )

        # 记录本次查询看到的全部轮次及状态
        turn_rows = self._storage.load_turns(session_id)

        first_running_seq = next(
            (
                row["turn_seq"]
                for row in turn_rows if row["status"] == "running"
            ),
            None
        )

        if (
            first_running_seq is not None
            and first_running_seq <= covered_seq
        ):
            raise ValueError("已有摘要覆盖范围内存在未结束轮次，请检查摘要")
        
        completed_ids = {
            row["turn_id"]
            for row in turn_rows if row["status"] == "completed"
        }

        # 只考虑本次状态查询时已完成的轮次
        turns = [
            turn for turn in self._turn_loader(self._storage, session_id)
            if turn["turn_id"] in completed_ids
        ]

        if (
            summary is not None
            and covered_seq not in {
                turn["turn_seq"] for turn in turns
            }
        ):
            raise ValueError("摘要边界对应的轮次无法恢复，请先检查原始记录")

        uncovered_turns = [
            turn
            for turn in turns
            if turn["turn_seq"] > covered_seq
        ]

        candidates = uncovered_turns[:-keep_recent_turns]
        
        if first_running_seq is not None:
            candidates = [
                turn for turn in candidates
                if turn["turn_seq"] < first_running_seq
            ]

        return {
            "summary": summary,
            "turns_to_summarize": candidates,
            "recent_turns": uncovered_turns[len(candidates):],
            "first_running_turn_seq": first_running_seq,
        }


    # 按上下文规划调用摘要函数合并旧摘要与待摘要轮次，保存成功后返回新摘要及近期轮次；
    # 无待摘要轮次时保留原结果，生成或保存失败时回退到旧摘要并保留未覆盖的原文。
    def prepare_context(self, session_id, *, keep_recent_turns=2):
        if self._summarizer is None:
            raise ValueError("请先配置 summarizer")

        plan = self.plan_context(
            session_id,
            keep_recent_turns=keep_recent_turns,
        )

        old_summary = plan["summary"]
        candidates = plan["turns_to_summarize"]

        # 默认保留旧摘要，以及全部未覆盖的完整轮次。
        result = {
            "summary": old_summary,
            "history_turns": candidates + plan["recent_turns"],
            "summary_status": "unchanged",
        }

        if not candidates:
            return result

        try:
            old_text = (
                old_summary["summary_text"]
                if old_summary is not None
                else ""
            )

            new_text = self._summarizer(old_text, candidates)

            if not isinstance(new_text, str) or not new_text.strip():
                raise ValueError("摘要函数必须返回非空字符串")

            new_text = new_text.strip()
            new_boundary = candidates[-1]["turn_seq"]

            summary_id = self._storage.save_summary(
                session_id,
                covered_through_turn_seq=new_boundary,
                summary_text=new_text,
                strategy_version=self._strategy_version,
            )

        except Exception:
            logging.exception(
                "摘要更新未确认成功，使用旧摘要并保留原文，session_id=%s",
                session_id,
            )

            result["summary_status"] = "fallback"
            return result

        # 只有保存调用成功返回，才采用新摘要和新边界。
        return {
            "summary": {
                "summary_id": summary_id,
                "session_id": session_id,
                "covered_through_turn_seq": new_boundary,
                "summary_text": new_text,
                "strategy_version": self._strategy_version,
            },
            "history_turns": plan["recent_turns"],
            "summary_status": "updated",
        }