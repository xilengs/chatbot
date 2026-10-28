-- 创建供本机 Python 程序使用的账户
CREATE USER IF NOT EXISTS 'chat_app'@'127.0.0.1'
IDENTIFIED BY '123456';

-- 授予三张表的读取、插入和修改权限
GRANT SELECT, INSERT, UPDATE
ON chat_memory.sessions
TO 'chat_app'@'127.0.0.1';

GRANT SELECT, INSERT, UPDATE
ON chat_memory.turns
TO 'chat_app'@'127.0.0.1';

GRANT SELECT, INSERT, UPDATE
ON chat_memory.messages
TO 'chat_app'@'127.0.0.1';

GRANT SELECT, INSERT
ON chat_memory.summaries
TO 'chat_app'@'127.0.0.1';

-- 查看授权结果
SHOW GRANTS FOR 'chat_app'@'127.0.0.1';