import os
from pathlib import Path
from dotenv import load_dotenv


def load_settings():
    project_dir = Path(__file__).resolve().parent
    load_dotenv(project_dir / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError(
            "请在 .env 或环境变量中配置 DEEPSEEK_API_KEY"
        )

    db_config = {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ["MYSQL_PORT"]),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
    }

    model_config = {
        "model": "deepseek-flash",
        "api_key": api_key,
        "base_url": os.getenv("base_url"),
        "temperature": 0.7,
    }

    return db_config, model_config