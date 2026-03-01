"""
Обработчики для пациентов - НОВАЯ ВЕРСИЯ
Регистрация с выбором отделения
"""
import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from utils.states import PatientRegistration, SubmitHealthReport, UrgentHealthReport
from services.database import patients_db
from services.health_reports import save_health_report, notify_admins_about_report
from keyboards.patient_kb import get_patient_menu, get_back_to_patient_menu
from config import TIMEZONE, DEPARTMENTS
import pytz
from utils.logger import log_patient_action

logger = logging.getLogger(__name__)

router = Router()


def get_department_keyboard():
    """Клавиатура выбора отделения"""
    keyboard = []
    for idx, dept in enumerate(DEPARTMENTS):
        keyboard.append([InlineKeyboardButton(text=dept, callback_data=f"dept:{idx}")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_registration")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)



async def cmd_start_patient(message: Message):
    """Обработчик /start для пациентов (вызывается из common.py)"""
    # Проверка регистрации
    user_id = message.from_user.id
    patient_record = await patients_db.get_by_user_id(user_id)
    is_registered = patient_record is not None
    
    if is_registered:
        await message.answer(
            "🏥 <b>Медицинский бот</b>\n\n"
            "Добро пожаловать! Используйте меню ниже для навигации.",
            reply_markup=get_patient_menu(),
            parse_mode="HTML"
        )
    else:
        # Новый пользователь - показываем приветствие с кнопкой регистрации
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data="start_registration")],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="patient_help")]
        ])
        
        await message.answer(
            "🏥 <b>Добро пожаловать в медицинский бот!</b>\n\n"
            "Этот бот помогает следить за вашим послеоперационным состоянием "
            "и напоминает о важных процедурах.\n\n"
            f"🆔 <b>Ваш ID:</b> <code>{user_id}</code>\n\n"
            "<i>💡 Если вы медицинский работник, перешлите это сообщение "
            "администратору для добавления в список персонала.</i>\n\n"
            "Для начала работы необходимо пройти регистрацию.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )



@router.callback_query(F.data == "start_registration")
@router.message(Command("register"))
async def cmd_register(update: Message | CallbackQuery, state: FSMContext):
    """Начало регистрации пациента"""
    if isinstance(update, CallbackQuery):
        message = update.message
        user_id = update.from_user.id
        await update.answer()
    else:
        message = update
        user_id = update.from_user.id
    
    # Проверяем, не зарегистрирован ли уже
    patient_record = await patients_db.get_by_user_id(user_id)
    if patient_record:
        await message.answer(
            "ℹ️ Вы уже зарегистрированы в системе.",
            reply_markup=get_patient_menu()
        )
        return
    
    await state.set_state(PatientRegistration.waiting_for_full_name)
    
    if isinstance(update, CallbackQuery):
        await message.edit_text(
            "📝 <b>Регистрация пациента</b>\n\n"
            "Шаг 1 из 2\n\n"
            "Введите ваше ФИО (например: Иванов Иван Иванович):",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "📝 <b>Регистрация пациента</b>\n\n"
            "Шаг 1 из 2\n\n"
            "Введите ваше ФИО (например: Иванов Иван Иванович):",
            parse_mode="HTML"
        )


@router.message(PatientRegistration.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext):
    """Обработка ФИО пациента"""
    raw_text = message.text.strip()
    
    # Разбиваем на слова, очищаем от лишних пробелов
    words = [w.strip() for w in raw_text.split() if w.strip()]
    
    # Проверка: должно быть минимум 3 слова (Фамилия Имя Отчество)
    if len(words) < 3:
        await message.answer(
            "❌ <b>Некорректный формат ФИО</b>\n\n"
            "Пожалуйста, введите <b>Фамилию, Имя и Отчество</b> полностью (минимум 3 слова).\n"
            "Например: <i>Иванов Иван Иванович</i>",
            parse_mode="HTML"
        )
        return
    
    # Форматируем: Каждое Слово С Большой Буквы
    # capitalize() переводит первую букву в верхний регистр, остальные в нижний
    formatted_words = [w.capitalize() for w in words]
    full_name = " ".join(formatted_words)
    
    await state.update_data(full_name=full_name)
    await state.set_state(PatientRegistration.waiting_for_department)
    
    await message.answer(
        "📝 <b>Регистрация пациента</b>\n\n"
        "Шаг 2 из 2\n\n"
        "Выберите ваше отделение:",
        reply_markup=get_department_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("dept:"))
async def process_department(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора отделения"""
    dept_idx = int(callback.data.split(":", 1)[1])
    department = DEPARTMENTS[dept_idx]
    
    # Сохраняем пациента
    user_data = await state.get_data()
    full_name = user_data["full_name"]
    user_id = callback.from_user.id
    
    patient_id = f"patient_{user_id}_{int(datetime.now().timestamp())}"
    
    patient_data = {
        "user_id": user_id,
        "full_name": full_name,
        "department": department,
        "registration_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
        "surgery_date": None,
        "auto_delete_date": None
    }
    
    await patients_db.update(patient_id, patient_data)
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Регистрация завершена!</b>\n\n"
        f"👤 ФИО: {full_name}\n"
        f"🏥 Отделение: {department}\n\n"
        f"Теперь вы можете использовать функции бота.\n"
        f"Дата операции будет установлена медицинским персоналом.",
        reply_markup=get_patient_menu(),
        parse_mode="HTML"
    )
    
    logger.info(f"Patient registered: {patient_id} - {full_name} ({department})")
    
    # Логируем регистрацию пациента
    log_patient_action(
        user_id,
        "Зарегистрировался",
        f"ФИО: {full_name}, Отделение: {department}"
    )
    
    await callback.answer()


@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    """Отмена регистрации"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Регистрация отменена.\n\n"
        "Для начала регистрации используйте команду /register"
    )
    await callback.answer()


@router.callback_query(F.data == "patient_menu")
async def callback_patient_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню пациента"""
    await state.clear()
    user_id = callback.from_user.id
    patient_record = await patients_db.get_by_user_id(user_id)
    
    if not patient_record:
        # Если не зарегистрирован - показываем стартовое меню
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data="start_registration")],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="patient_help")]
        ])
        
        await callback.message.edit_text(
            "🏥 <b>Медицинский бот</b>\n\n"
            "Для доступа к функциям необходимо зарегистрироваться.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            "🏥 <b>Медицинский бот</b>\n\n"
            "Выберите действие:",
            reply_markup=get_patient_menu(),
            parse_mode="HTML"
        )
    await callback.answer()

@router.message(Command("info"))
async def cmd_my_info(message: Message):
    """Показать информацию о пациенте по команде /info"""
    user_id = message.from_user.id
    
    # Находим patient_id пользователя
    patient_record = await patients_db.get_by_user_id(user_id)
    patient_data = patient_record[1] if patient_record else None
    
    if not patient_data:
        await message.answer(
            "❌ Вы не зарегистрированы как пациент.\n\n"
            "Используйте /register для регистрации."
        )
        return
    
    full_name = patient_data.get("full_name", "Неизвестно")
    department = patient_data.get("department", "Не указано")
    surgery_date_str = patient_data.get("surgery_date")
    
    surgery_name = patient_data.get("surgery_name")
    
    surgery_info = ""
    if surgery_date_str:
        try:
            surgery_date = datetime.fromisoformat(surgery_date_str)
            surgery_info = f"\n⚕️ Дата операции: {surgery_date.strftime('%d.%m.%Y')}"
            if surgery_name:
                surgery_info += f"\n📝 Операция: {surgery_name}"
        except ValueError:
            surgery_info = f"\n⚕️ Дата операции: {surgery_date_str}"
            if surgery_name:
                surgery_info += f"\n📝 Операция: {surgery_name}"
    else:
        surgery_info = "\n⚕️ Дата операции: не установлена"
    
    await message.answer(
        f"👤 <b>Ваша информация</b>\n\n"
        f"ФИО: {full_name}\n"
        f"🏥 Отделение: {department}{surgery_info}",
        reply_markup=get_back_to_patient_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "patient_my_info")
async def callback_my_info(callback: CallbackQuery):
    """Показать информацию о пациенте"""
    user_id = callback.from_user.id
    
    # Находим patient_id пользователя
    patient_record = await patients_db.get_by_user_id(user_id)
    
    if patient_record:
        patient_id = patient_record[0]
        patient_data = patient_record[1]
    else:
        patient_id = None
        patient_data = None
    
    if not patient_data:
        await callback.answer("❌ Вы не зарегистрированы как пациент", show_alert=True)
        return
    
    full_name = patient_data.get("full_name", "Неизвестно")
    department = patient_data.get("department", "Не указано")
    surgery_date_str = patient_data.get("surgery_date")
    
    surgery_name = patient_data.get("surgery_name")
    
    surgery_info = ""
    if surgery_date_str:
        try:
            surgery_date = datetime.fromisoformat(surgery_date_str)
            surgery_info = f"\n⚕️ Дата операции: {surgery_date.strftime('%d.%m.%Y')}"
            if surgery_name:
                surgery_info += f"\n📝 Операция: {surgery_name}"
        except ValueError:
            surgery_info = f"\n⚕️ Дата операции: {surgery_date_str}"
            if surgery_name:
                surgery_info += f"\n📝 Операция: {surgery_name}"
    else:
        surgery_info = "\n⚕️ Дата операции: не установлена"
    
    text = (
        f"👤 <b>Ваша информация</b>\n\n"
        f"ФИО: {full_name}\n"
        f"🏥 Отделение: {department}{surgery_info}"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_patient_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "patient_help")
async def callback_patient_help(callback: CallbackQuery):
    """Справка для пациента"""
    help_text = (
        "ℹ️ <b>Справка</b>\n\n"
        "Этот бот помогает вам следить за вашим послеоперационным состоянием.\n\n"
        "<b>Автоматические напоминания:</b>\n"
        "После установки даты операции вам будут приходить напоминания:\n"
        "• Через 5 дней после операции\n"
        "• Через 10 дней после операции\n"
        "• Через 30 дней после операции\n\n"
        "Через 31 день ваши данные будут автоматически удалены из системы.\n\n"
        "Если у вас есть вопросы, обратитесь к медицинскому персоналу."
    )
    
    await callback.message.edit_text(
        help_text,
        reply_markup=get_back_to_patient_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


# ========== ОТЧЕТЫ О СОСТОЯНИИ ==========

@router.callback_query(F.data.startswith("report:"))
async def callback_submit_report(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Начало отправки отчета о состоянии"""
    parts = callback.data.split(":")
    patient_id = parts[1]
    days_after = int(parts[2])
    
    await state.update_data(patient_id=patient_id, days_after=days_after)
    await state.set_state(SubmitHealthReport.waiting_for_report_text)
    
    await callback.message.answer(
        f"📝 <b>Отчет о состоянии (день {days_after} после операции)</b>\n\n"
        "Пожалуйста, опишите следующую информацию:\n\n"
        "🌡️ <b>Температура тела:</b> (например: 36.6°C)\n"
        "💪 <b>Общее самочувствие:</b> (хорошее/удовлетворительное/плохое)\n"
        "😌 <b>Уровень боли:</b> (нет/слабая/умеренная/сильная)\n"
        "💊 <b>Прием лекарств:</b> (по назначению/нерегулярно)\n"
        "❓ <b>Вопросы к врачу:</b> (если есть)\n\n"
        "<i>Напишите всё одним сообщением.</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SubmitHealthReport.waiting_for_report_text)
async def process_health_report(message: Message, state: FSMContext, bot: Bot):
    """Обработка отчета о состоянии"""
    report_text = message.text.strip()
    
    if len(report_text) < 10:
        await message.answer("❌ Отчет слишком короткий. Пожалуйста, опишите подробнее (минимум 10 символов).")
        return
    
    user_data = await state.get_data()
    patient_id = user_data["patient_id"]
    days_after = user_data["days_after"]
    
    # Сохраняем отчет
    await save_health_report(patient_id, days_after, report_text)
    
    # Уведомляем всех админов
    await notify_admins_about_report(bot, patient_id, days_after, report_text)
    
    await state.clear()
    
    await message.answer(
        "✅ <b>Спасибо!</b>\n\n"
        "Ваш отчет отправлен медицинскому персоналу.",
        parse_mode="HTML"
    )
    
    logger.info(f"Health report submitted by user {message.from_user.id}, day {days_after}")
    
    # Логируем
    log_patient_action(
        message.from_user.id,
        "Отправил отчет о состоянии",
        f"День {days_after}"
    )


# ========== СРОЧНАЯ ЖАЛОБА НА СОСТОЯНИЕ ==========

@router.message(Command("report"))
async def cmd_urgent_report(message: Message, state: FSMContext):
    """Начало отправки срочной жалобы по команде /report"""
    user_id = message.from_user.id
    
    # Находим patient_id
    patient_record = await patients_db.get_by_user_id(user_id)
    patient_id = patient_record[0] if patient_record else None
    
    if not patient_id:
        await message.answer(
            "❌ Вы не зарегистрированы как пациент.\n\n"
            "Используйте /register для регистрации."
        )
        return
    
    await state.update_data(patient_id=patient_id)
    await state.set_state(UrgentHealthReport.waiting_for_urgent_report)
    
    await message.answer(
        "🚨 <b>Срочная жалоба на состояние здоровья</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ!</b> Если ваше состояние сильно ухудшилось, "
        "немедленно позвоните врачу или вызовите скорую помощь!\n\n"
        "Опишите ваше текущее состояние:\n"
        "🌡️ Температура\n"
        "😣 Симптомы и жалобы\n"
        "💊 Какие лекарства принимали\n\n"
        "<i>Медицинский персонал получит уведомление.</i>",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "patient_urgent_report")
async def callback_urgent_report(callback: CallbackQuery, state: FSMContext):
    """Начало отправки срочной жалобы на состояние"""
    user_id = callback.from_user.id
    
    # Находим patient_id
    patient_record = await patients_db.get_by_user_id(user_id)
    patient_id = patient_record[0] if patient_record else None
    
    if not patient_id:
        await callback.answer("❌ Вы не зарегистрированы", show_alert=True)
        return
    
    await state.update_data(patient_id=patient_id)
    await state.set_state(UrgentHealthReport.waiting_for_urgent_report)
    
    await callback.message.answer(
        "🚨 <b>Срочная жалоба на состояние здоровья</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ!</b> Если ваше состояние сильно ухудшилось, "
        "немедленно позвоните врачу или вызовите скорую помощь!\n\n"
        "Опишите ваше текущее состояние:\n"
        "🌡️ Температура\n"
        "😣 Симптомы и жалобы\n"
        "💊 Какие лекарства принимали\n\n"
        "<i>Медицинский персонал получит уведомление.</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(UrgentHealthReport.waiting_for_urgent_report)
async def process_urgent_report(message: Message, state: FSMContext, bot: Bot):
    """Обработка срочной жалобы"""
    report_text = message.text.strip()
    
    if len(report_text) < 10:
        await message.answer("❌ Описание слишком короткое. Опишите подробнее (минимум 10 символов).")
        return
    
    user_data = await state.get_data()
    patient_id = user_data["patient_id"]
    
    # Сохраняем как специальный отчет с меткой "urgent"
    await save_health_report(patient_id, "urgent", report_text)
    
    # Уведомляем всех админов
    patient_data = await patients_db.get(patient_id)
    if patient_data:
        full_name = patient_data.get("full_name", "Неизвестно")
        department = patient_data.get("department", "Не указано")
        
        # Получаем всех администраторов
        from services.database import staff_db
        staff = await staff_db.read()
        
        urgent_message = (
            "🚨 <b>СРОЧНАЯ ЖАЛОБА НА СОСТОЯНИЕ!</b>\n\n"
            f"👤 Пациент: {full_name}\n"
            f"🏥 Отделение: {department}\n\n"
            f"<b>Жалоба:</b>\n{report_text}\n\n"
            "⚠️ <i>Требует внимания медицинского персонала!</i>"
        )
        
        for user_id_str, _ in staff.items():
            try:
                admin_id = int(user_id_str)
                await bot.send_message(admin_id, urgent_message, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to notify admin {user_id_str}: {e}")
    
    await state.clear()
    
    await message.answer(
        "✅ <b>Ваша жалоба отправлена!</b>\n\n"
        "Медицинский персонал получил уведомление.\n\n"
        "⚠️ При серьезном ухудшении состояния не ждите ответа - звоните врачу или вызывайте скорую помощь!",
        parse_mode="HTML"
    )
    
    logger.info(f"Urgent health report submitted by user {message.from_user.id}")
    
    # Логируем
    log_patient_action(
        message.from_user.id,
        "Отправил срочную жалобу",
        f"Пациент ID: {patient_id}"
    )
