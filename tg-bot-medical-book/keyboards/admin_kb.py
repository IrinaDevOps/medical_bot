"""
Клавиатуры для администраторов - НОВАЯ ВЕРСИЯ
Навигация по отделениям
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.database import patients_db, staff_db
from services.reminder_system import create_surgery_reminders, cancel_surgery_reminders, get_reminder_templates, update_reminder_template, scheduler
from services.health_reports import get_patient_reports
from config import DEPARTMENTS, ROLES


def get_admin_menu(is_superadmin: bool = False, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню администратора"""
    keyboard = [
        [InlineKeyboardButton(text="👥 Список пациентов", callback_data="admin_departments")],
    ]
    
    if is_superadmin or is_admin:
        keyboard.append([InlineKeyboardButton(text="📊 Скачать отчет (.xlsx)", callback_data="admin_export_excel")])
    
    if is_superadmin:
        keyboard.append([InlineKeyboardButton(text="👨‍⚕️ Управление ролями", callback_data="admin_manage_roles")])
        keyboard.append([InlineKeyboardButton(text="⚙️ Настройка текстов напоминаний", callback_data="admin_reminder_templates")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_departments_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора отделения"""
    keyboard = []
    for idx, dept in enumerate(DEPARTMENTS):
        keyboard.append([InlineKeyboardButton(text=dept, callback_data=f"admin_dept:{idx}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_patients_in_department_keyboard(patients_list, dept_idx: int, page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура списка пациентов в отделении с пагинацией"""
    keyboard = []
    
    limit = 6
    start = page * limit
    end = start + limit
    
    current_page_items = patients_list[start:end]
    total_pages = (len(patients_list) + limit - 1) // limit
    
    for patient_id, patient_data in current_page_items:
        full_name = patient_data.get("full_name", "Неизвестно")
        
        # Обрезаем длинное имя (макс 30 символов)
        if len(full_name) > 30:
            full_name = full_name[:27] + "..."
            
        # Добавляем эмодзи если есть операция
        icon = "✅" if patient_data.get("surgery_date") else "👤"
        label = f"{icon} {full_name}"
             
        keyboard.append([InlineKeyboardButton(
            text=label,
            callback_data=f"admin_patient:{patient_id}"
        )])
    
    # Навигация
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_dept:{dept_idx}:p:{page-1}"))
        
        nav_buttons.append(InlineKeyboardButton(text=f"Стр {page+1}/{total_pages}", callback_data="ignore"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_dept:{dept_idx}:p:{page+1}"))
            
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="◀️ К отделениям", callback_data="admin_departments")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_patient_actions_keyboard(patient_id: str, has_surgery_date: bool) -> InlineKeyboardMarkup:
    """Клавиатура действий с пациентом"""
    keyboard = []
    
    if has_surgery_date:
        keyboard.append([InlineKeyboardButton(text="📅 Изменить дату операции", callback_data=f"admin_set_surgery:{patient_id}")])
        keyboard.append([InlineKeyboardButton(text="📝 Просмотреть отчеты пациента", callback_data=f"admin_view_reports:{patient_id}")])
        keyboard.append([InlineKeyboardButton(text="⏳ Продлить срок удаления", callback_data=f"admin_extend:{patient_id}")])
    else:
        keyboard.append([InlineKeyboardButton(text="📅 Установить дату операции", callback_data=f"admin_set_surgery:{patient_id}")])
    
    keyboard.append([InlineKeyboardButton(text="🗑️ Удалить пациента", callback_data=f"admin_delete_patient:{patient_id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_departments")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_staff_list_keyboard(staff_list, page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура списка персонала с пагинацией"""
    keyboard = []
    
    limit = 6
    start = page * limit
    end = start + limit
    
    current_page_items = staff_list[start:end]
    total_pages = (len(staff_list) + limit - 1) // limit
    
    for user_id, staff_data in current_page_items:
        role = staff_data.get("role", "unknown")
        role_name = ROLES.get(role, role)
        keyboard.append([InlineKeyboardButton(
            text=f"{role_name} (ID: {user_id})",
            callback_data=f"admin_staff:{user_id}"
        )])
    
    # Навигация
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_manage_roles:p:{page-1}"))
        
        nav_buttons.append(InlineKeyboardButton(text=f"Стр {page+1}/{total_pages}", callback_data="ignore"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_manage_roles:p:{page+1}"))
            
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add_staff")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_staff_actions_keyboard(user_id: str) -> InlineKeyboardMarkup:
    """Клавиатура действий с персоналом"""
    keyboard = [
        [InlineKeyboardButton(text="✏️ Изменить роль", callback_data=f"admin_change_role:{user_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить роль", callback_data=f"admin_remove_role:{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_roles")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_role_selection_keyboard(for_user_id: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора роли"""
    keyboard = []
    
    for role_key, role_name in ROLES.items():
        if role_key == "superadmin":
            continue  # Суперадмин не назначается вручную
        
        callback_data = f"admin_assign_role:{for_user_id}:{role_key}" if for_user_id else f"role:{role_key}"
        keyboard.append([InlineKeyboardButton(text=role_name, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_reminder_intervals_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора интервала для редактирования шаблона"""
    keyboard = [
        [InlineKeyboardButton(text="5 дней", callback_data="admin_template:5")],
        [InlineKeyboardButton(text="10 дней", callback_data="admin_template:10")],
        [InlineKeyboardButton(text="30 дней", callback_data="admin_template:30")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


def get_back_to_admin_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата в админ меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
    ])
