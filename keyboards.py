"""Клавиатуры бота."""
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from content import Content

# Кнопки постоянного меню (внизу экрана)
MENU_MATERIALS = "🎁 Материалы"
MENU_LINKS = "🔗 Наши ресурсы"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_MATERIALS), KeyboardButton(text=MENU_LINKS)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def materials_kb(content: Content) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in content.materials:
        kb.button(text=m.button, callback_data=f"mat:{m.id}")
    kb.adjust(1)
    return kb.as_markup()


def subscribe_kb(channel_url: str, material_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Подписаться", url=channel_url)
    kb.button(text="✅ Я подписался", callback_data=f"chk:{material_id}")
    kb.adjust(1)
    return kb.as_markup()


def links_kb(content: Content) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for link in content.links:
        kb.button(text=link.button, url=link.url)
    kb.adjust(1)
    return kb.as_markup()


def after_material_kb(content: Content, taken_id: str) -> InlineKeyboardMarkup:
    """Предлагает остальные материалы + ссылки на ресурсы."""
    kb = InlineKeyboardBuilder()
    for m in content.materials:
        if m.id != taken_id:
            kb.button(text=m.button, callback_data=f"mat:{m.id}")
    kb.button(text=MENU_LINKS, callback_data="links")
    kb.adjust(1)
    return kb.as_markup()


# ---------- админка ----------

def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="📨 Рассылка", callback_data="adm:broadcast")
    kb.button(text="📥 Выгрузить пользователей (CSV)", callback_data="adm:export")
    kb.button(text="🔄 Обновить контент", callback_data="adm:reload")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data="bc:send")
    kb.button(text="❌ Отмена", callback_data="bc:cancel")
    kb.adjust(2)
    return kb.as_markup()
