"""
Клавиатуры для пациентов
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_patient_menu() -> InlineKeyboardMarkup:
    """Главное меню пациента"""
    keyboard = [
        [InlineKeyboardButton(text="👤 Моя информация", callback_data="patient_my_info")],
        [InlineKeyboardButton(text="🚨 Сообщить об ухудшении", callback_data="patient_urgent_report")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="patient_help")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_patient_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата в меню пациента"""
    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="patient_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
