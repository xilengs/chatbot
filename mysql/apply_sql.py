"""按 .env 配置渲染并执行 mysql/ 目录下的通用 SQL 模板。

mysql/init.sql 与 mysql/create_app_user.sql 不写死数据库名、地址和账户，
统一使用 ${MYSQL_*} 占位符；本脚本从 .env（或同名进程环境变量）取值，
按所在 SQL 上下文做转义后连接数据库执行。

用法（在项目根目录执行）::

    python mysql/apply_sql.py              # 依次执行 init.sql、create_app_user.sql
    python mysql/apply_sql.py init         # 只建库建表
    python mysql/apply_sql.py app_user     # 只创建应用账户并授权
    python mysql/apply_sql.py --dry-run    # 只打印渲染后的 SQL，不连接数据库

可用占位符：

    ${MYSQL_DATABASE}   数据库名
    ${MYSQL_HOST}       数据库地址
    ${MYSQL_PORT}       数据库端口
    ${MYSQL_USER}       应用账户名
    ${MYSQL_PASSWORD}   应用账户密码
    ${MYSQL_APP_HOST}   应用账户允许连接的来源地址（默认取 MYSQL_HOST）

执行账户取 MYSQL_ADMIN_USER（默认 root），密码取 MYSQL_ADMIN_PASSWORD；
未配置时交互输入，因此管理员密码不必写进 .env。
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

MYSQL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MYSQL_DIR.parent
ENV_FILE = PROJECT_DIR / ".env"

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

SCRIPTS = {
    "init": "init.sql",
    "app_user": "create_app_user.sql",
}
TARGETS = (*SCRIPTS, "all")


def read_setting(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(
            f"缺少配置项 {name}，请在 {ENV_FILE} 或环境变量中设置"
        )
    return value or ""


def load_settings() -> dict[str, str]:
    load_dotenv(ENV_FILE)

    settings = {
        "MYSQL_HOST": read_setting("MYSQL_HOST", "127.0.0.1"),
        "MYSQL_PORT": read_setting("MYSQL_PORT", "3306"),
        "MYSQL_DATABASE": read_setting("MYSQL_DATABASE", required=True),
        "MYSQL_USER": read_setting("MYSQL_USER", required=True),
        "MYSQL_PASSWORD": read_setting("MYSQL_PASSWORD", required=True),
        "MYSQL_ADMIN_USER": read_setting("MYSQL_ADMIN_USER", "root"),
    }
    settings["MYSQL_APP_HOST"] = (
        read_setting("MYSQL_APP_HOST") or settings["MYSQL_HOST"]
    )
    return settings


def escape_value(value: str, quote: str | None) -> str:
    """按占位符所在的 SQL 上下文转义取值，避免密码等字符破坏语句。"""
    if quote is None:
        return value
    if quote == "`":
        return value.replace("`", "``")
    if quote == "'":
        return value.replace("\\", "\\\\").replace("'", "''")
    if quote == '"':
        return value.replace("\\", "\\\\").replace('"', '""')
    return value


def _lookup(name: str, values: dict[str, str], quote: str | None) -> str:
    if name not in values:
        raise SystemExit(f"模板中使用了未定义的占位符 ${{{name}}}")
    return escape_value(values[name], quote)


def render(template: str, values: dict[str, str]) -> str:
    """把模板渲染成可执行 SQL，并按引号上下文转义取值。"""
    out: list[str] = []
    i, n = 0, len(template)
    quote: str | None = None

    while i < n:
        char = template[i]

        if quote is not None:
            if char == "$":
                match = PLACEHOLDER.match(template, i)
                if match:
                    out.append(_lookup(match.group(1), values, quote))
                    i = match.end()
                    continue
            out.append(char)
            if char == "\\" and quote != "`" and i + 1 < n:
                out.append(template[i + 1])
                i += 2
                continue
            if char == quote:
                if i + 1 < n and template[i + 1] == quote:
                    out.append(template[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if char in "'\"`":
            quote = char
            out.append(char)
            i += 1
            continue

        if (
            char == "-"
            and template.startswith("--", i)
            and (i + 2 >= n or template[i + 2] in " \t\r\n")
        ):
            end = template.find("\n", i)
            end = n if end == -1 else end
            out.append(template[i:end])
            i = end
            continue

        if char == "#":
            end = template.find("\n", i)
            end = n if end == -1 else end
            out.append(template[i:end])
            i = end
            continue

        if char == "/" and template.startswith("/*", i):
            end = template.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(template[i:end])
            i = end
            continue

        if char == "$":
            match = PLACEHOLDER.match(template, i)
            if match:
                out.append(_lookup(match.group(1), values, quote))
                i = match.end()
                continue

        out.append(char)
        i += 1

    if quote is not None:
        raise SystemExit("SQL 模板中的引号没有闭合")

    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """按分号切分语句，跳过注释，并保证引号内的分号不被误切。"""
    statements: list[str] = []
    buffer: list[str] = []
    i, n = 0, len(sql)
    quote: str | None = None

    while i < n:
        char = sql[i]

        if quote is not None:
            buffer.append(char)
            if char == "\\" and quote != "`" and i + 1 < n:
                buffer.append(sql[i + 1])
                i += 2
                continue
            if char == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    buffer.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if char in "'\"`":
            quote = char
            buffer.append(char)
            i += 1
            continue

        if (
            char == "-"
            and sql.startswith("--", i)
            and (i + 2 >= n or sql[i + 2] in " \t\r\n")
        ) or char == "#":
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            buffer.append("\n")
            continue

        if char == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            buffer.append(" ")
            continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            i += 1
            continue

        buffer.append(char)
        i += 1

    if quote is not None:
        raise SystemExit("SQL 模板中的引号没有闭合")

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)

    return statements


def _connect(settings: dict[str, str], user: str, password: str, connector):
    try:
        return connector.connect(
            host=settings["MYSQL_HOST"],
            port=int(settings["MYSQL_PORT"]),
            user=user,
            password=password,
            charset="utf8mb4",
            autocommit=True,
        )
    except connector.Error as error:
        raise SystemExit(
            f"连接 MySQL 失败（{settings['MYSQL_HOST']}:{settings['MYSQL_PORT']}，"
            f"用户 {user}）：{error}"
        ) from error


def execute(statements: list[tuple[str, str]], settings: dict[str, str]) -> None:
    import mysql.connector

    admin_user = settings["MYSQL_ADMIN_USER"]
    admin_password = os.getenv("MYSQL_ADMIN_PASSWORD") or None
    if admin_password is None:
        admin_password = getpass.getpass(f"MySQL 管理员 {admin_user} 的密码: ")

    connection = _connect(settings, admin_user, admin_password, mysql.connector)

    try:
        cursor = connection.cursor(buffered=True)
        for filename, statement in statements:
            try:
                cursor.execute(statement)
                if cursor.with_rows:
                    for row in cursor.fetchall():
                        print(row[0] if len(row) == 1 else row)
                cursor.reset()
            except mysql.connector.Error as error:
                head = " ".join(statement.split())
                if len(head) > 160:
                    head = head[:157] + "..."
                raise SystemExit(
                    f"\n执行失败（{filename}）：{error}\n语句：{head}"
                ) from error
        cursor.close()
    finally:
        connection.close()


def build_plan(targets: list[str], settings: dict[str, str]) -> list[tuple[str, str]]:
    """返回 [(文件名, 语句)]，按脚本顺序展开。"""
    names = list(SCRIPTS) if "all" in targets else targets
    ordered = [name for name in SCRIPTS if name in names]

    plan: list[tuple[str, str]] = []
    for name in ordered:
        path = MYSQL_DIR / SCRIPTS[name]
        rendered = render(path.read_text(encoding="utf-8"), settings)
        plan.extend((path.name, statement) for statement in split_statements(rendered))
    return plan


def print_summary(settings: dict[str, str]) -> None:
    print(
        f"目标数据库：{settings['MYSQL_DATABASE']} "
        f"@ {settings['MYSQL_HOST']}:{settings['MYSQL_PORT']}"
    )
    print(
        f"应用账户：{settings['MYSQL_USER']}@{settings['MYSQL_APP_HOST']}"
        f"（执行账户 {settings['MYSQL_ADMIN_USER']}）"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按 .env 配置渲染并执行 mysql/ 下的通用 SQL 脚本"
    )
    parser.add_argument(
        "targets",
        nargs="*",
        choices=TARGETS,
        metavar="{init,app_user,all}",
        help="要执行的脚本，默认 all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印渲染后的 SQL，不连接数据库",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    print_summary(settings)

    try:
        port = int(settings["MYSQL_PORT"])
    except ValueError as error:
        raise SystemExit(f"MYSQL_PORT 不是合法端口：{settings['MYSQL_PORT']}") from error
    settings["MYSQL_PORT"] = str(port)

    plan = build_plan(args.targets or ["all"], settings)
    if not plan:
        raise SystemExit("没有要执行的语句")

    if args.dry_run:
        for filename, statement in plan:
            print(f"\n-- [dry-run] {filename}\n{statement};")
        return 0

    execute(plan, settings)
    print(f"完成，共执行 {len(plan)} 条语句。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
