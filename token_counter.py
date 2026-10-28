from pathlib import Path
from tokenizers import Tokenizer


class DeepSeekTextCounter:
    def __init__(self, tokenizer_path):
        path = Path(tokenizer_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"找不到 tokenizer 文件：{path}"
            )

        self._tokenizer = Tokenizer.from_file(str(path))

    def count_text(self, text):
        if not isinstance(text, str):
            raise TypeError("text 必须是字符串")

        encoded = self._tokenizer.encode(
            text,
            add_special_tokens=False,
        )

        return len(encoded.ids)