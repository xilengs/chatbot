-- 通用建库建表脚本
-- 数据库名不写死，使用占位符 ${MYSQL_DATABASE}，由 mysql/apply_sql.py
-- 从 .env（或同名环境变量）读取后渲染执行：
--     python mysql/apply_sql.py init
--
-- 占位符：${MYSQL_DATABASE}

CREATE DATABASE IF NOT EXISTS `${MYSQL_DATABASE}`
    CHARACTER SET utf8mb4;

USE `${MYSQL_DATABASE}`;
SET SESSION time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS sessions (
    session_id CHAR(36) NOT NULL,
    user_id VARCHAR(128) NULL,
    title VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    metadata JSON NULL,

    PRIMARY KEY (session_id)
) ENGINE = InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS turns (
    turn_id CHAR(36) NOT NULL,
    session_id CHAR(36) NOT NULL,
    turn_seq INT UNSIGNED NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    started_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),
    ended_at DATETIME(6) NULL,
    error_message TEXT NULL,
    execution_config JSON NULL,

    PRIMARY KEY (turn_id),

    UNIQUE KEY uq_turns_session_seq (session_id, turn_seq),

    CONSTRAINT fk_turns_session
        FOREIGN KEY (session_id)
        REFERENCES sessions (session_id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT chk_turns_seq
        CHECK (turn_seq > 0),

    CONSTRAINT chk_turns_status
        CHECK (
            status IN (
                'running',
                'completed',
                'failed',
                'interrupted'
            )
        )
) ENGINE = InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS messages (
    message_id CHAR(36) NOT NULL,
    turn_id CHAR(36) NOT NULL,
    message_seq INT UNSIGNED NOT NULL,
    role VARCHAR(16) NOT NULL,
    payload JSON NOT NULL,
    payload_format VARCHAR(64) NOT NULL
        DEFAULT 'chat_message',
    schema_version SMALLINT UNSIGNED NOT NULL
        DEFAULT 1,
    status VARCHAR(16) NOT NULL DEFAULT 'completed',
    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (message_id),

    UNIQUE KEY uq_messages_turn_seq (turn_id, message_seq),

    CONSTRAINT fk_messages_turn
        FOREIGN KEY (turn_id)
        REFERENCES turns (turn_id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT chk_messages_seq
        CHECK (message_seq > 0),

    CONSTRAINT chk_messages_role
        CHECK (role IN ('system', 'user', 'assistant', 'tool')),

    CONSTRAINT chk_messages_status
        CHECK (status IN ('completed', 'partial')),

    CONSTRAINT chk_messages_version
        CHECK (schema_version > 0)
) ENGINE = InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS summaries (
    summary_id CHAR(36) NOT NULL,
    session_id CHAR(36) NOT NULL,
    covered_through_turn_seq INT UNSIGNED NOT NULL,
    summary_text TEXT NOT NULL,
    strategy_version VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (summary_id),

    KEY idx_summaries_session_boundary (
        session_id,
        covered_through_turn_seq,
        created_at,
        summary_id
    ),

    CONSTRAINT fk_summaries_boundary
        FOREIGN KEY (
            session_id,
            covered_through_turn_seq
        )
        REFERENCES turns (
            session_id,
            turn_seq
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT chk_summaries_boundary
        CHECK (covered_through_turn_seq > 0)

) ENGINE = InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_bin;
