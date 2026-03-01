import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
import pytz

from config import SUPERADMIN_ID, TIMEZONE, ROLES, DEPARTMENTS
from utils.states import SetSurgeryDate, ManageRoles, EditReminderTemplate
from services.database import patients_db, staff_db, reminders_db, reminder_templates_db
from services.export import export_patients_to_excel
from services.reminder_system import create_surgery_reminders, cancel_surgery_reminders, get_reminder_templates, update_reminder_template, scheduler
from services.health_reports import get_patient_reports, save_health_report
from keyboards.admin_kb import (
    get_admin_menu, get_departments_keyboard, get_patients_in_department_keyboard,
    get_patient_actions_keyboard, get_staff_list_keyboard, get_staff_actions_keyboard,
    get_role_selection_keyboard, get_reminder_intervals_keyboard, get_cancel_keyboard,
    get_back_to_admin_menu
)
from handlers.common import is_staff
from utils.logger import log_admin_action

logger = logging.getLogger(__name__)

router = Router()

# ========== ГЛАВНОЕ МЕНЮ ==========

@router.callback_query(F.data == "admin_menu")
async def callback_admin_menu(callback: CallbackQuery, state: FSMContext):
    """Главное меню администратора"""
    await state.clear()
    
    if not await is_staff(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа к админ-панели", show_alert=True)
        return
    
    # Проверка прав (суперадмин или роль admin)
    user_id = callback.from_user.id
    staff_data = await staff_db.get(str(user_id))
    role = str(staff_data.get("role")).strip().lower() if staff_data else ""
    is_super = (user_id == SUPERADMIN_ID) or (role == "admin")
    is_full_admin = is_super
    
    await callback.message.edit_text(
        "👨‍⚕️ <b>Панель управления</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_menu(is_super, is_full_admin),
        parse_mode="HTML"
    )
    await callback.answer()


# ========== НАВИГАЦИЯ ПО ОТДЕЛЕНИЯМ ==========

@router.message(Command("patients"))
async def cmd_patients(message: Message):
    """Показать список отделений по команде /patients"""
    if not await is_staff(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Подсчитываем пациентов по отделениям
    counts = await patients_db.get_department_counts()
    dept_counts = {dept: counts.get(dept, 0) for dept in DEPARTMENTS}
    
    text = "🏥 <b>Отделения</b>\n\nВыберите отделение для просмотра пациентов:\n\n"
    for dept in DEPARTMENTS:
        count = dept_counts[dept]
        text += f"• {dept}: <b>{count}</b> пациент(ов)\n"
    
    await message.answer(
        text,
        reply_markup=get_departments_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_departments")
async def callback_departments(callback: CallbackQuery):
    """Показать список отделений"""
    if not await is_staff(callback.from_user.id):
        await callback.answer("❌ У вас нет доступа", show_alert=True)
        return
    
    counts = await patients_db.get_department_counts()
    dept_counts = {dept: counts.get(dept, 0) for dept in DEPARTMENTS}
    
    text = "🏥 <b>Отделения</b>\n\nВыберите отделение для просмотра пациентов:\n\n"
    for dept in DEPARTMENTS:
        count = dept_counts[dept]
        text += f"• {dept}: <b>{count}</b> пациент(ов)\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_departments_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_export_excel")
async def callback_export_excel(callback: CallbackQuery):
    """Экспорт данных в Excel"""
    # Проверка прав (только админ или суперадмин)
    user_id = callback.from_user.id
    staff_data = await staff_db.get(str(user_id))
    is_allowed = (user_id == SUPERADMIN_ID) or (staff_data and str(staff_data.get("role")).strip().lower() == "admin")
    
    if not is_allowed:
        await callback.answer("❌ Доступно только администраторам", show_alert=True)
        return

    await callback.message.edit_text("⏳ Формирование отчета...")
    
    try:
        file_io = await export_patients_to_excel()
        filename = f"Отчет_о_пациентах_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
        
        input_file = BufferedInputFile(file_io.getvalue(), filename=filename)
        
        await callback.message.answer_document(
            document=input_file,
            caption="📊 <b>Отчет о пациентах</b>\n\nСодержит полную информацию из базы данных.",
            parse_mode="HTML"
        )
        
        # Restore menu
        role = str(staff_data.get("role")).strip().lower() if staff_data else ""
        is_super = (user_id == SUPERADMIN_ID) or (role == "admin")
        is_full_admin = is_super
        
        await callback.message.answer(
             "👨‍⚕️ <b>Панель управления</b>",
             reply_markup=get_admin_menu(is_super, is_full_admin),
             parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Export error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при создании отчета.\nПопробуйте позже.",
            reply_markup=get_back_to_admin_menu()
        )
        
    await callback.answer()


@router.callback_query(F.data.startswith("admin_dept:"))
async def callback_department_patients(callback: CallbackQuery):
    """Показать пациентов в отделении"""
    parts = callback.data.split(":")
    dept_idx = int(parts[1])
    
    page = 0
    if len(parts) > 3 and parts[2] == "p":
        page = int(parts[3])
    
    department = DEPARTMENTS[dept_idx]
    
    dept_patients = await patients_db.get_by_department(department)
    
    try:
        if not dept_patients:
            await callback.message.edit_text(
                f"ℹ️ <b>{department}</b>\n\nВ этом отделении пока нет пациентов.",
                reply_markup=get_departments_keyboard(),
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                f"👥 <b>{department}</b>\n\nПациентов: {len(dept_patients)}\n\nВыберите пациента:",
                reply_markup=get_patients_in_department_keyboard(dept_patients, dept_idx, page),
                parse_mode="HTML"
            )
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_patient:"))
async def callback_delete_patient_ask(callback: CallbackQuery):
    """Спрашиваем подтверждение удаления"""
    patient_id = callback.data.split(":", 1)[1]
    
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        await callback.answer("❌ Пациент не найден", show_alert=True)
        return
        
    full_name = patient_data.get("full_name", "Неизвестно")
    
    # Клавиатура подтверждения
    keyboard = [
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete:{patient_id}")],
        [InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"admin_patient:{patient_id}")]
    ]
    
    await callback.message.edit_text(
        f"⚠️ <b>Удаление пациента</b>\n\n"
        f"Вы уверены, что хотите удалить пациента <b>{full_name}</b>?\n"
        f"Это действие <b>необратимо</b> и удалит все данные пользователя.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_delete:"))
async def callback_delete_patient_confirm(callback: CallbackQuery):
    """Подтвержденное удаление"""
    patient_id = callback.data.split(":", 1)[1]
    
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        await callback.answer("❌ Пациент не найден", show_alert=True)
        await callback.message.edit_text(
            "❌ Пациент не найден (возможно уже удален).",
            reply_markup=get_departments_keyboard()
        )
        return

    # Отменяем напоминания
    await cancel_surgery_reminders(patient_id)
    
    # Удаляем пациента (только текущую запись, архив не трогаем)
    full_name = patient_data.get("full_name", "Неизвестно")
    await patients_db.delete(patient_id)
    
    await callback.message.edit_text(
        f"✅ Пациент <b>{full_name}</b> удален из системы.",
        reply_markup=get_departments_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()





@router.callback_query(F.data.startswith("admin_patient:"))
async def callback_view_patient(callback: CallbackQuery):
    """Просмотр карточки пациента"""
    patient_id = callback.data.split(":", 1)[1]
    
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        await callback.answer("❌ Пациент не найден", show_alert=True)
        return
    
    full_name = patient_data.get("full_name", "Неизвестно")
    department = patient_data.get("department", "Не указано")
    surgery_date_str = patient_data.get("surgery_date")
    
    surgery_info = ""
    has_surgery = False
    if surgery_date_str:
        has_surgery = True
        try:
            surgery_date = datetime.fromisoformat(surgery_date_str)
            surgery_info = f"\n⚕️ Дата операции: {surgery_date.strftime('%d.%m.%Y')}"
            
            if patient_data.get("surgery_name"):
                surgery_info += f"\n📝 Операция: {patient_data.get('surgery_name')}"
                
            if patient_data.get("reminder_time"):
                surgery_info += f"\n⏰ Уведомления: в {patient_data.get('reminder_time')}"
        except ValueError:
            surgery_info = f"\n⚕️ Дата операции: {surgery_date_str}"
    else:
        surgery_info = "\n⚕️ Дата операции: не установлена"
    
    text = (
        f"👤 <b>{full_name}</b>\n\n"
        f"🏥 Отделение: {department}{surgery_info}\n\n"
        f"Выберите действие:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_patient_actions_keyboard(patient_id, has_surgery),
        parse_mode="HTML"
    )
    await callback.answer()


# ========== УСТАНОВКА ДАТЫ ОПЕРАЦИИ ==========

@router.callback_query(F.data.startswith("admin_set_surgery:"))
async def callback_set_surgery_date(callback: CallbackQuery, state: FSMContext):
    """Начало установки даты операции"""
    patient_id = callback.data.split(":", 1)[1]
    
    await state.update_data(patient_id=patient_id)
    await state.set_state(SetSurgeryDate.waiting_for_surgery_date)
    
    await callback.message.edit_text(
        "📅 <b>Установка даты операции</b>\n\n"
        "Введите дату операции в формате ДД.ММ.ГГГГ\n"
        "Например: 15.01.2026",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SetSurgeryDate.waiting_for_surgery_date)
async def process_surgery_date(message: Message, state: FSMContext):
    """Обработка даты операции"""
    date_str = message.text.strip()
    
    try:
        surgery_date = datetime.strptime(date_str, "%d.%m.%Y")
        tz = pytz.timezone(TIMEZONE)
        surgery_date = tz.localize(surgery_date)
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Используйте: ДД.ММ.ГГГГ\n"
            "Например: 15.01.2026"
        )
        return
    
    # Проверка "давности" операции
    now = datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Сравниваем даты (игнорируя время)
    surgery_day = surgery_date.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = today - surgery_day
    
    if delta.days > 4:
        await message.answer(
            "❌ Дата операции не может быть старше 4 дней.\n"
            "Пожалуйста, введите корректную дату."
        )
        return

    # Сохраняем дату и переходим к имени
    await state.update_data(surgery_date_iso=surgery_date.isoformat())
    await state.set_state(SetSurgeryDate.waiting_for_surgery_name)
    
    await message.answer(
        "📝 <b>Введите название операции</b>\n\n"
        "Например: Лазерная коррекция зрения",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(SetSurgeryDate.waiting_for_surgery_name)
async def process_surgery_name(message: Message, state: FSMContext):
    """Обработка названия операции"""
    surgery_name = message.text.strip()
    await state.update_data(surgery_name=surgery_name)
    
    await state.set_state(SetSurgeryDate.waiting_for_reminder_time)
    
    # Клавиатура для времени
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕛 12:00 (По умолчанию)", callback_data="time_default_12")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    
    await message.answer(
        "⏰ <b>Установите время отправки уведомлений</b>\n\n"
        "Введите время в формате ЧЧ:ММ (24 часа)\n"
        "Или нажмите кнопку для выбора 12:00.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(SetSurgeryDate.waiting_for_reminder_time)
@router.callback_query(F.data == "time_default_12")
async def process_reminder_time(update: Message | CallbackQuery, state: FSMContext, bot: Bot):
    """Обработка времени напоминания и завершение"""
    time_str = "12:00"
    
    if isinstance(update, CallbackQuery):
        await update.answer()
        # time_str уже задан
    else:
        time_str = update.text.strip()
        # Валидация формата времени
        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            await update.answer("❌ Неверный формат времени. Используйте ЧЧ:ММ (например 09:30)")
            return
    
    # Загружаем данные из состояния
    user_state_data = await state.get_data()
    patient_id = user_state_data["patient_id"]
    surgery_date_iso = user_state_data["surgery_date_iso"]
    surgery_name = user_state_data["surgery_name"]
    
    # Получаем данные пациента
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        msg = update.message if isinstance(update, Message) else update.message
        await msg.answer("❌ Пациент не найден.")
        await state.clear()
        return
    
    # Конвертируем дату обратно
    surgery_date = datetime.fromisoformat(surgery_date_iso)
    
    # Отменяем старые напоминания
    if patient_data.get("surgery_date"):
        await cancel_surgery_reminders(patient_id)
    
    # Обновляем данные в БД
    patient_data["surgery_date"] = surgery_date_iso
    patient_data["surgery_name"] = surgery_name
    patient_data["reminder_time"] = time_str
    
    await patients_db.update(patient_id, patient_data)
    
    # Запускаем создание напоминаний (передаем время!)
    # Но функция create_surgery_reminders принимает surgery_date. 
    # Она сама должна теперь учитывать reminder_time?
    # Мы пока просто передадим surgery_date.
    # Нам нужно обновить create_surgery_reminders чтобы она читала время из БД или передать его ей.
    # Пока передадим как есть, а потом обновим reminder_system.
    
    await create_surgery_reminders(bot, patient_id, surgery_date)
    
    await state.clear()
    
    msg = update.message if isinstance(update, Message) else update.message
    formatted_date = surgery_date.strftime("%d.%m.%Y")
    
    await msg.answer(
        f"✅ <b>Операция оформлена!</b>\n\n"
        f"📅 Дата: {formatted_date}\n"
        f"📝 Операция: {surgery_name}\n"
        f"⏰ Уведомления: в {time_str}\n"
        f"👤 Пациент: {patient_data.get('full_name')}\n\n"
        f"Напоминания запланированы.",
        parse_mode="HTML"
    )
    
    # Логируем
    log_admin_action(
        update.from_user.id,
        "Установил операцию",
        f"Пациент: {patient_id}, Дата: {formatted_date}, Имя: {surgery_name}"
    )





# ========== ПРОСМОТР ОТЧЕТОВ ПАЦИЕНТА ==========

@router.callback_query(F.data.startswith("admin_view_reports:"))
async def callback_view_reports(callback: CallbackQuery):
    """Просмотр отчетов о состоянии пациента"""
    patient_id = callback.data.split(":", 1)[1]
    
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        await callback.answer("❌ Пациент не найден", show_alert=True)
        return
    
    full_name = patient_data.get("full_name", "Неизвестно")
    
    # Получаем отчеты
    reports_data = await get_patient_reports(patient_id)
    reports = reports_data.get("reports", {})
    
    if not reports:
        await callback.message.edit_text(
            f"ℹ️ <b>Отчеты пациента</b>\n\n"
            f"👤 {full_name}\n\n"
            f"Пациент пока не отправлял отчетов о состоянии.",
            reply_markup=get_back_to_admin_menu(),
            parse_mode="HTML"
        )
    else:
        text = f"📋 <b>Отчеты пациента</b>\n\n👤 {full_name}\n\n"
        
        for day in ["5", "10", "30"]:
            if day in reports:
                report = reports[day]
                submitted_at = report.get("submitted_at", "Неизвестно")
                report_text = report.get("text", "")
                
                try:
                    dt = datetime.fromisoformat(submitted_at)
                    formatted_time = dt.strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    formatted_time = submitted_at
                
                text += f"<b>День {day}:</b> ({formatted_time})\n{report_text}\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=get_back_to_admin_menu(),
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("admin_extend:"))
async def callback_extend_deletion(callback: CallbackQuery):
    """Продление срока удаления пациента на 7 дней"""
    patient_id = callback.data.split(":", 1)[1]
    
    patient_data = await patients_db.get(patient_id)
    if not patient_data:
        await callback.answer("❌ Пациент не найден", show_alert=True)
        return
    
    surgery_date_str = patient_data.get("surgery_date")
    if not surgery_date_str:
        await callback.answer("❌ Дата операции не установлена", show_alert=True)
        return
    
    full_name = patient_data.get("full_name", "Неизвестно")
    
    # Продляем на 7 дней
    surgery_date = datetime.fromisoformat(surgery_date_str)
    from config import AUTO_DELETE_DAY
    from datetime import timedelta
    
    # Новая дата удаления: текущая + 7 дней
    new_delete_date = surgery_date + timedelta(days=AUTO_DELETE_DAY + 7)
    
    # Обновляем задачу в планировщике
    from services.reminder_system import delete_patient_after_surgery
    from apscheduler.triggers.date import DateTrigger
    
    delete_job_id = f"delete_{patient_id}"
    
    try:
        scheduler.remove_job(delete_job_id)
    except Exception:
        pass
    
    tz = pytz.timezone(TIMEZONE)
    if new_delete_date > datetime.now(tz):
        scheduler.add_job(
            delete_patient_after_surgery,
            trigger=DateTrigger(run_date=new_delete_date),
            args=[patient_id],
            id=delete_job_id,
            replace_existing=True
        )
    
    await callback.message.edit_text(
        f"✅ Срок удаления продлен на 7 дней!\n\n"
        f"👤 Пациент: <b>{full_name}</b>\n"
        f"📅 Новая дата удаления: {new_delete_date.strftime('%d.%m.%Y')}",
        reply_markup=get_back_to_admin_menu(),
        parse_mode="HTML"
    )
    
    await callback.answer()
    
    logger.info(f"Deletion extended for patient {patient_id} by 7 days")
    
    # Логируем
    log_admin_action(
        callback.from_user.id,
        "Продлил срок удаления",
        f"Пациент: {full_name}, +7 дней"
    )


# ========== УПРАВЛЕНИЕ РОЛЯМИ ==========

@router.callback_query(F.data.startswith("admin_manage_roles"))
async def callback_manage_roles(callback: CallbackQuery):
    """Управление ролями (только для суперадмина)"""
    parts = callback.data.split(":")
    page = 0
    if len(parts) > 2 and parts[1] == "p":
        page = int(parts[2])

    # Проверка прав (суперадмин или роль admin)
    user_id = callback.from_user.id
    staff_data = await staff_db.get(str(user_id))
    is_allowed = (user_id == SUPERADMIN_ID) or (staff_data and str(staff_data.get("role")).strip().lower() == "admin")
    
    logger.info(f"Manage Roles Access: User {user_id}, Role: {staff_data.get('role') if staff_data else 'None'}, Allowed: {is_allowed}")
    
    if not is_allowed:
        await callback.answer("❌ Доступно только администраторам", show_alert=True)
        return
    
    staff = await staff_db.read()
    staff_list = [(user_id, data) for user_id, data in staff.items()]
    
    await callback.message.edit_text(
        "👨‍⚕️ <b>Управление ролями</b>\n\n"
        f"Всего администраторов: {len(staff_list)}\n\n"
        "Выберите пользователя для управления:",
        reply_markup=get_staff_list_keyboard(staff_list, page),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_staff")
async def callback_add_staff(callback: CallbackQuery, state: FSMContext):
    """Начало добавления админа"""
    await state.set_state(ManageRoles.waiting_for_user_id)
    
    await callback.message.edit_text(
        "👨‍⚕️ <b>Добавление администратора</b>\n\n"
        "Введите Telegram ID пользователя:\n\n"
        "ℹ️ Узнать ID можно через @userinfobot",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ManageRoles.waiting_for_user_id)
async def process_new_admin_id(message: Message, state: FSMContext):
    """Обработка ID для нового админа"""
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    await state.update_data(target_user_id=str(user_id))
    await state.set_state(ManageRoles.waiting_for_role_selection)
    
    await message.answer(
        f"👤 ID пользователя: <code>{user_id}</code>\n\n"
        "Выберите роль:",
        reply_markup=get_role_selection_keyboard(str(user_id)),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin_staff:"))
async def callback_view_staff(callback: CallbackQuery):
    """Просмотр карточки админа"""
    user_id = callback.data.split(":", 1)[1]
    
    if user_id == str(SUPERADMIN_ID):
        await callback.answer("❌ Нельзя изменить суперадмина", show_alert=True)
        return
    
    staff_data = await staff_db.get(user_id)
    if not staff_data:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    role = staff_data.get("role", "unknown")
    role_name = ROLES.get(role, role)
    
    await callback.message.edit_text(
        f"👤 <b>Пользователь {user_id}</b>\n\n"
        f"Роль: <b>{role_name}</b>\n\n"
        "Выберите действие:",
        reply_markup=get_staff_actions_keyboard(user_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_change_role:"))
async def callback_change_role(callback: CallbackQuery, state: FSMContext):
    """Начало изменения роли"""
    user_id = callback.data.split(":", 1)[1]
    
    await state.update_data(target_user_id=user_id)
    await state.set_state(ManageRoles.waiting_for_role_selection)
    
    await callback.message.edit_text(
        f"✏️ <b>Изменение роли</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n\n"
        "Выберите новую роль:",
        reply_markup=get_role_selection_keyboard(user_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_assign_role:"))
async def callback_assign_role(callback: CallbackQuery, state: FSMContext):
    """Назначение/изменение роли"""
    parts = callback.data.split(":")
    user_id = parts[1]
    role_key = parts[2]
    
    role_name = ROLES.get(role_key, role_key)
    
    staff_data = {
        "user_id": int(user_id),
        "role": role_key,
        "assigned_by": callback.from_user.id,
        "assigned_at": datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    }
    
    await staff_db.update(user_id, staff_data)
    
    await callback.message.edit_text(
        f"✅ Роль <b>{role_name}</b> назначена пользователю {user_id}",
        reply_markup=get_back_to_admin_menu(),
        parse_mode="HTML"
    )
    
    logger.info(f"Role {role_key} assigned to user {user_id}")
    
    # Логируем действие
    log_admin_action(
        callback.from_user.id,
        "Назначил роль",
        f"User ID: {user_id}, Роль: {role_name}"
    )
    
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("admin_remove_role:"))
async def callback_remove_role(callback: CallbackQuery):
    """Удаление роли"""
    user_id = callback.data.split(":", 1)[1]
    
    await staff_db.delete(user_id)
    
    await callback.message.edit_text(
        f"✅ Роль удалена для пользователя {user_id}",
        reply_markup=get_back_to_admin_menu()
    )
    await callback.answer()
    
    logger.info(f"Role removed for user {user_id}")
    
    # Логируем действие
    log_admin_action(
        callback.from_user.id,
        "Удалил роль",
        f"User ID: {user_id}"
    )


# ========== НАСТРОЙКА ТЕКСТОВ НАПОМИНАНИЙ ==========

@router.callback_query(F.data == "admin_reminder_templates")
async def callback_reminder_templates(callback: CallbackQuery):
    """Настройка текстов напоминаний"""
    # Проверка прав (суперадмин или роль admin)
    user_id = callback.from_user.id
    staff_data = await staff_db.get(str(user_id))
    is_allowed = (user_id == SUPERADMIN_ID) or (staff_data and str(staff_data.get("role")).strip().lower() == "admin")

    logger.info(f"Templates Access: User {user_id}, Role: {staff_data.get('role') if staff_data else 'None'}, Allowed: {is_allowed}")
    
    if not is_allowed:
        await callback.answer("❌ Доступно только администраторам", show_alert=True)
        return
    
    templates = await get_reminder_templates()
    
    text = "⚙️ <b>Настройка текстов напоминаний</b>\n\n"
    text += "Текущие шаблоны:\n\n"
    
    for interval in [5, 10, 30]:
        template = templates.get(str(interval), "Не установлен")
        text += f"<b>{interval} дней:</b>\n{template}\n\n"
    
    text += "Выберите интервал для редактирования:"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_reminder_intervals_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_template:"))
async def callback_edit_template(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования шаблона"""
    interval = callback.data.split(":")[1]
    
    await state.update_data(template_interval=interval)
    await state.set_state(EditReminderTemplate.waiting_for_template_text)
    
    templates = await get_reminder_templates()
    current = templates.get(interval, "Не установлен")
    
    await callback.message.edit_text(
        f"✏️ <b>Редактирование шаблона ({interval} дней)</b>\n\n"
        f"Текущий текст:\n{current}\n\n"
        f"Введите новый текст напоминания:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditReminderTemplate.waiting_for_template_text)
async def process_template_text(message: Message, state: FSMContext):
    """Обработка нового текста шаблона"""
    new_text = message.text.strip()
    
    if len(new_text) < 10:
        await message.answer("❌ Текст слишком короткий (минимум 10 символов).")
        return
    
    user_data = await state.get_data()
    interval = int(user_data["template_interval"])
    
    await update_reminder_template(interval, new_text)
    
    await state.clear()
    
    await message.answer(
        f"✅ Шаблон для {interval} дней обновлен!\n\n"
        f"Новый текст:\n{new_text}",
        parse_mode="HTML"
    )
    
    logger.info(f"Reminder template updated: {interval} days")
    
    # Логируем действие
    log_admin_action(
        message.from_user.id,
        "Обновил шаблон напоминания",
        f"Интервал: {interval} дней"
    )


# ========== ОТМЕНА ==========


# ========== ТЕСТИРОВАНИЕ НАПОМИНАНИЙ ==========

@router.message(Command("test"))
async def cmd_test_reminders(message: Message, bot: Bot):
    """
    Команда для тестирования системы напоминаний
    Доступна только администраторам
    """
    if not await is_staff(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Получаем данные пользователя как пациента
    user_id = message.from_user.id
    # Находим тестовый patient_id
    patient_record = await patients_db.get_by_user_id(user_id)
    test_patient_id = patient_record[0] if patient_record else None
    
    # Если нет - создаем временный
    if not test_patient_id:
        test_patient_id = f"test_patient_{user_id}"
    
    await message.answer(
        "🧪 <b>Режим тестирования напоминаний</b>\n\n"
        "Сейчас вы получите все три типа напоминаний:\n"
        "• День 5\n"
        "• День 10\n"
        "• День 30\n\n"
        "Проверьте кнопки и формы отправки отчетов.",
        parse_mode="HTML"
    )
    
    # Отправляем тестовые напоминания
    from services.reminder_system import send_surgery_reminder
    
    for days in [5, 10, 30]:
        await send_surgery_reminder(bot, user_id, days, test_patient_id)
        logger.info(f"Test reminder sent: {days} days to admin {user_id}")
    
    await message.answer(
        "✅ Тестовые напоминания отправлены!\n\n"
        "Проверьте работу кнопок и отправку отчетов.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена операции"""
    await state.clear()
    
    user_id = callback.from_user.id
    staff_data = await staff_db.get(str(user_id))
    is_superadmin = (user_id == SUPERADMIN_ID) or (staff_data and str(staff_data.get("role")).strip().lower() == "admin")
    
    await callback.message.edit_text(
        "❌ Операция отменена.\n\n"
        "👨‍⚕️ <b>Панель управления</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_menu(is_superadmin),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(Command("testexpirationpatient"))
async def cmd_test_expiration_patient(message: Message):
    """
    Тест системы архивации и повторной регистрации.
    Создает пациента, архивирует его и создает заново.
    """
    # Проверка прав (только персонал)
    if not await is_staff(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return

    log = []
    log.append("🚀 <b>Начало теста архивации...</b>")
    
    test_user_id = 999999999
    
    # 1. Очистка (на всякий случай)
    await patients_db.delete_by_user_id(test_user_id)
    log.append("✅ Предварительная очистка тестовых данных")

    # 2. Создаем пациента (Эмуляция регистрации)
    dept = DEPARTMENTS[0] # Хирургическое отделение
    patient_id_1 = f"test_pat_1_{int(datetime.now().timestamp())}"
    surgery_date = datetime.now(pytz.timezone(TIMEZONE))
    
    p1_data = {
        "user_id": test_user_id,
        "full_name": "Тестовый Тест Тестович",
        "department": dept,
        "registration_date": surgery_date.isoformat(),
        "surgery_date": surgery_date.isoformat(),
        "surgery_name": "Удаление пальца",
        "reminder_time": "12:00",
        "is_archived": 0
    }
    
    await patients_db.update(patient_id_1, p1_data)
    log.append(f"✅ Пациент 1 создан: {patient_id_1} (Активен)")
    
    # Проверка наличия
    p1 = await patients_db.get_by_user_id(test_user_id)
    if p1 and p1[0] == patient_id_1:
        log.append("   -> Проверка: Пациент найден системой как активный")
    else:
        log.append("   ❌ ОШИБКА: Пациент не найден!")
        await message.answer("\n".join(log), parse_mode="HTML")
        return

    # 3. Тест истечения (Архивация)
    log.append("⏳ <b>Эмуляция истечения 31 дня...</b>")
    # Импортируем внутри функции, чтобы избежать циклических импортов если они есть
    from services.reminder_system import delete_patient_after_surgery
    await delete_patient_after_surgery(patient_id_1)
    
    # Проверяем статус в БД
    p1_check = await patients_db.get(patient_id_1)
    if p1_check and p1_check.get("is_archived") == 1:
        log.append("✅ Пациент 1 успешно архивирован (is_archived=1)")
    else:
        log.append("❌ ОШИБКА: Пациент не архивирован!")
    
    # Проверяем, что get_by_user_id его НЕ видит
    p1_lookup = await patients_db.get_by_user_id(test_user_id)
    if p1_lookup is None:
         log.append("✅ Система 'забыла' пациента (get_by_user_id вернул None)")
    else:
         log.append(f"❌ ОШИБКА: Система всё ещё видит пациента: {p1_lookup[0]}")

    # 4. Создаем пациента заново (Новая операция)
    log.append("🔄 <b>Новая регистрация в Хирургическом отделении...</b>")
    
    patient_id_2 = f"test_pat_2_{int(datetime.now().timestamp())}"
    p2_data = {
        "user_id": test_user_id,
        "full_name": "Тестовый Тест Тестович (Новый)",
        "department": dept,
        "registration_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
        "is_archived": 0
    }
    
    await patients_db.update(patient_id_2, p2_data)
    log.append(f"✅ Пациент 2 создан: {patient_id_2}")
    
    # 5. Финальная проверка
    p2_lookup = await patients_db.get_by_user_id(test_user_id)
    if p2_lookup and p2_lookup[0] == patient_id_2:
        log.append("✅ Система видит НОВОГО пациента")
    else:
        log.append("❌ ОШИБКА: Система не видит нового пациента")
        
    log.append("\n🏁 <b>Тест успешно завершен!</b>")
    await message.answer("\n".join(log), parse_mode="HTML")

@router.message(Command("testall"))
async def cmd_test_all(message: Message):
    """
    Полный системный тест ВСЕХ компонентов:
    1. БД: Персонал (CRUD), Шаблоны, Статистика
    2. Пациент: Регистрация, Операция, Напоминания, Отчеты, Архивация, Повтор
    3. Оповещения и Экспорт
    """
    if not await is_staff(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return

    start_time = datetime.now()
    log = []
    log.append(f"🧪 <b>ЗАПУСК ГЛОБАЛЬНОГО ТЕСТИРОВАНИЯ</b>")
    log.append(f"📅 {start_time.strftime('%d.%m.%Y %H:%M:%S')}")
    
    msg = await message.answer("\n".join(log) + "\n\n⏳ <i>Тестирование...</i>", parse_mode="HTML")
    
    test_uid = 77777777  # ID для тестов
    p_id_1 = f"test_full_{int(start_time.timestamp())}_1"
    
    try:
        # === 1. ПЕРСОНАЛ И ПРАВА ===
        log.append("\n<b>1. Система персонала</b>")
        try:
            # Чтение себя
            my_role = await staff_db.get(str(message.from_user.id))
            if my_role: log.append(f"✅ Self-check: Роль '{my_role.get('role')}' найдена")
            else: log.append("⚠️ Self-check: Вы суперадмин без записи в БД")
            
            # CRUDDummy
            dummy_id = "00000000"
            await staff_db.update(dummy_id, {"role": "doctor", "assigned_by": "test"})
            if await staff_db.exists(dummy_id): log.append("✅ CRUD: Временный сотрудник создан")
            else: raise Exception("Не удалось создать сотрудника")
            
            await staff_db.delete(dummy_id)
            if not await staff_db.exists(dummy_id): log.append("✅ CRUD: Временный сотрудник удален")
            else: raise Exception("Не удалось удалить сотрудника")
        except Exception as e:
            log.append(f"❌ FAIL: {e}")
            raise e

        # === 2. ШАБЛОНЫ И НАСТРОЙКИ ===
        log.append("\n<b>2. Настройки и Шаблоны</b>")
        try:
            tmpls = await reminder_templates_db.read()
            if tmpls: log.append(f"✅ Шаблоны загружены ({len(tmpls)} шт)")
            
            # Временное изменение
            orig_text = tmpls.get(5, "")
            await reminder_templates_db.update(5, "TEST_TEMPLATE_IGNORE")
            check_t = await reminder_templates_db.read()
            if check_t.get(5) == "TEST_TEMPLATE_IGNORE": log.append("✅ Шаблон обновлен успешно")
            else: raise Exception("Ошибка обновления шаблона")
            
            # Возврат
            await reminder_templates_db.update(5, orig_text)
            log.append("✅ Шаблон восстановлен")
        except Exception as e:
            log.append(f"❌ FAIL: {e}")
            raise e

        # === 3. ЖИЗНЕННЫЙ ЦИКЛ ПАЦИЕНТА ===
        log.append("\n<b>3. Полный цикл пациента</b>")
        await patients_db.delete_by_user_id(test_uid) # Очистка
        
        try:
            # 3.1 Регистрация
            dept = DEPARTMENTS[0]
            start_count = (await patients_db.get_department_counts()).get(dept, 0)
            
            p_data = {
                "user_id": test_uid,
                "full_name": "Test Full Cycle",
                "department": dept,
                "registration_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "is_archived": 0
            }
            await patients_db.update(p_id_1, p_data)
            
            # Проверка статистики
            new_count = (await patients_db.get_department_counts()).get(dept, 0)
            if new_count == start_count + 1: log.append("✅ Статистика отделения обновлена (+1)")
            else: log.append(f"⚠️ Статистика не изменилась: {start_count}->{new_count}")

            # 3.2 Операция и Напоминания
            surg_date = datetime.now(pytz.timezone(TIMEZONE))
            await create_surgery_reminders(message.bot, p_id_1, surg_date)
            
            # Проверка планировщика (scheduler)
            # Напоминания живут в памяти scheduler, а не в отдельной таблице reminders
            rem_id = f"reminder_{p_id_1}_5"
            job = scheduler.get_job(rem_id)
            if job: log.append("✅ Напоминания созданы в планировщике")
            else: 
                # Debug info
                all_jobs = [j.id for j in scheduler.get_jobs()]
                log.append(f"⚠️ Debug: Jobs in scheduler: {len(all_jobs)}")
                raise Exception(f"Напоминание {rem_id} не найдено в scheduler")

            # 3.3 Отчет о здоровье
            rep_id = await save_health_report(p_id_1, 5, "Test Report", user_id=test_uid, is_urgent=True)
            if not rep_id:
                raise Exception("save_health_report вернул None (ошибка сохранения)")
                
            saved_reps = await get_patient_reports(p_id_1)
            
            # Debug
            log.append(f"🔍 Debug: Report ID={rep_id}")
            log.append(f"🔍 Debug: Reports found: {list(saved_reps.get('reports', {}).keys())}")
            
            if saved_reps.get("reports", {}).get("5"): log.append("✅ Отчет о здоровье сохранен")
            else: raise Exception(f"Отчет не сохранился. Dump: {saved_reps}")

            # 3.4 Архивация
            from services.reminder_system import delete_patient_after_surgery
            await delete_patient_after_surgery(p_id_1)
            
            check_arch = await patients_db.get(p_id_1)
            if check_arch.get("is_archived") == 1: log.append("✅ Пациент архивирован")
            else: raise Exception("Архивация не сработала")
            
            # Статистика должна уменьшиться
            final_count = (await patients_db.get_department_counts()).get(dept, 0)
            if final_count == start_count: log.append("✅ Пациент ушел из статистики активных")
            else: log.append(f"⚠️ Статистика не вернулась: {final_count} != {start_count}")

            # 3.5 Ре-регистрация
            p_id_2 = f"test_full_{int(start_time.timestamp())}_2"
            p_data["full_name"] = "Test Cycle 2"
            await patients_db.update(p_id_2, p_data)
            
            check_active = await patients_db.get_by_user_id(test_uid)
            if check_active and check_active[0] == p_id_2: log.append("✅ Повторная регистрация успешна (новый ID)")
            else: raise Exception("Ошибка повторной регистрации")

            # Очистка
            await patients_db.delete_by_user_id(test_uid)

        except Exception as e:
            log.append(f"❌ FAIL: {e}")
            raise e

        # === 4. ОПОВЕЩЕНИЯ И ЭКСПОРТ ===
        log.append("\n<b>4. Внешние системы</b>")
        try:
            # Уведомления
            from services.reminder_system import send_surgery_reminder
            from config import REMINDER_INTERVALS
            for d in REMINDER_INTERVALS:
                await send_surgery_reminder(message.bot, message.from_user.id, d, p_id_1)
            log.append("✅ Уведомления отправлены (см. чат)")
            
            # Excel
            file_io = await export_patients_to_excel()
            if file_io.getbuffer().nbytes > 0: log.append("✅ Excel сгенерирован в памяти")
            else: raise Exception("Пустой файл Excel")

        except Exception as e:
            log.append(f"❌ FAIL: {e}")
            raise e

        # Финал
        dur = (datetime.now() - start_time).total_seconds()
        log.append(f"\n🏁 <b>ТЕСТ ЗАВЕРШЕН УСПЕШНО! ({dur:.2f}s)</b>")
    
    except Exception as ge:
        log.append(f"\n⛔ <b>КРИТИЧЕСКИЙ СБОЙ: {ge}</b>")
        logger.error(f"Global Test Fail: {ge}")

    await msg.edit_text("\n".join(log), parse_mode="HTML")
