"""
Общие обработчики для всех пользователей
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import SUPERADMIN_ID
from services.database import staff_db, patients_db
from keyboards.admin_kb import get_admin_menu
from handlers import patient

logger = logging.getLogger(__name__)

router = Router()


async def is_staff(user_id: int) -> bool:
    """Проверяет, является ли пользователь персоналом"""
    if user_id == SUPERADMIN_ID:
        return True
    return await staff_db.exists(str(user_id))


async def is_patient(user_id: int) -> bool:
    """Проверяет, является ли пользователь зарегистрированным пациентом"""
    result = await patients_db.get_by_user_id(user_id)
    return result is not None


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    # Проверяем роль пользователя
    staff_status = await is_staff(user_id)
    logger.info(f"User {user_id} staff status: {staff_status}, SUPERADMIN_ID: {SUPERADMIN_ID}")
    
    if staff_status:
        # Админ
        staff_data = await staff_db.get(str(user_id))
        role = str(staff_data.get("role")).strip().lower() if staff_data else ""
        
        is_super = (user_id == SUPERADMIN_ID) or (role == "admin")
        is_full_admin = is_super
        
        logger.info(f"Showing admin menu to user {user_id}. Role='{role}', is_super={is_super}, is_full_admin={is_full_admin}")
        
        await message.answer(
            "👨‍⚕️ <b>Панель управления</b>\n\n"
            "Добро пожаловать! Выберите действие:",
            reply_markup=get_admin_menu(is_super, is_full_admin),
            parse_mode="HTML"
        )
    else:
        # Пациент или новый пользователь - передаем в patient handler
        logger.info(f"User {user_id} is not staff, showing patient interface")
        await patient.cmd_start_patient(message)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    user_id = message.from_user.id
    
    if await is_staff(user_id):
        help_text = (
            "ℹ️ <b>Справка для персонала</b>\n\n"
            "<b>Основные функции:</b>\n"
            "• Просмотр пациентов по отделениям\n"
            "• Установка даты операции\n"
            "• Управление автоматическими напоминаниями\n\n"
            "<b>Для суперадмина:</b>\n"
            "• Управление ролями персонала\n"
            "• Настройка текстов напоминаний\n\n"
            "Используйте /start для доступа к панели управления."
        )
    else:
        help_text = (
            "ℹ️ <b>Справка</b>\n\n"
            "Этот бот помогает следить за вашим послеоперационным состоянием.\n\n"
            "<b>Команды:</b>\n"
            "/start - Главное меню\n"
            "/register - Регистрация\n"
            "/help - Справка\n\n"
            "После операции вы будете получать автоматические напоминания "
            "через 5, 10 и 30 дней."
        )
    
    await message.answer(help_text, parse_mode="HTML")


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Универсальная отмена"""
    await state.clear()
    await callback.answer("Операция отменена")


@router.callback_query(F.data == "ignore")
async def callback_ignore(callback: CallbackQuery):
    """Пустой колбэк"""
    await callback.answer()


# Этот роутер должен быть зарегистрирован ПЕРВЫМ в bot.py
