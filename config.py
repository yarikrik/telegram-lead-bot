"""Настройки бота. Всё читается из файла .env (см. .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv необязателен, если переменные заданы в окружении
    pass

BASE_DIR = Path(__file__).resolve().parent


def _parse_ids(raw: str) -> set[int]:
    """'123, 456' -> {123, 456}"""
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: set[int] = field(default_factory=set)
    # Канал, подписку на который проверяем: @username или -100... (бот должен быть в нём админом)
    channel_id: str = ""
    # Ссылка на канал для кнопки «Подписаться» (для приватного канала — инвайт-ссылка)
    channel_url: str = ""
    db_path: Path = BASE_DIR / "data" / "bot.db"
    content_path: Path = BASE_DIR / "content.json"


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")
    channel_id = os.getenv("CHANNEL_ID", "").strip()
    channel_url = os.getenv("CHANNEL_URL", "").strip()
    if not channel_url and channel_id.startswith("@"):
        channel_url = f"https://t.me/{channel_id[1:]}"
    if channel_id and not channel_url:
        raise RuntimeError("Для приватного канала укажите CHANNEL_URL (инвайт-ссылку).")
    return Config(
        bot_token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        channel_id=channel_id,
        channel_url=channel_url,
        db_path=Path(os.getenv("DB_PATH", BASE_DIR / "data" / "bot.db")),
        content_path=Path(os.getenv("CONTENT_PATH", BASE_DIR / "content.json")),
    )
