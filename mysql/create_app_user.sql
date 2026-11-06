-- 通用应用账户脚本：创建供本机 Python 程序使用的账户并授权
-- 数据库名、地址、账户和密码都不写死，由 mysql/apply_sql.py 从
-- .env（或同名环境变量）读取后渲染执行：
--     python mysql/apply_sql.py app_user
--
-- 占位符：
--   ${MYSQL_DATABASE}  数据库名
--   ${MYSQL_USER}      应用账户名
--   ${MYSQL_PASSWORD}  应用账户密码
--   ${MYSQL_APP_HOST}  应用账户允许连接的来源地址
--
-- 执行账户需要 CREATE USER 和 GRANT 权限（例如 root）。
-- CREATE USER IF NOT EXISTS 不会修改已存在账户的密码；
-- 需要重置时先执行 ALTER USER。

CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'${MYSQL_APP_HOST}'
IDENTIFIED BY '${MYSQL_PASSWORD}';

-- 授予三张表的读取、插入和修改权限
GRANT SELECT, INSERT, UPDATE
ON `${MYSQL_DATABASE}`.sessions
TO '${MYSQL_USER}'@'${MYSQL_APP_HOST}';

GRANT SELECT, INSERT, UPDATE
ON `${MYSQL_DATABASE}`.turns
TO '${MYSQL_USER}'@'${MYSQL_APP_HOST}';

GRANT SELECT, INSERT, UPDATE
ON `${MYSQL_DATABASE}`.messages
TO '${MYSQL_USER}'@'${MYSQL_APP_HOST}';

GRANT SELECT, INSERT
ON `${MYSQL_DATABASE}`.summaries
TO '${MYSQL_USER}'@'${MYSQL_APP_HOST}';

-- 查看授权结果
SHOW GRANTS FOR '${MYSQL_USER}'@'${MYSQL_APP_HOST}';
