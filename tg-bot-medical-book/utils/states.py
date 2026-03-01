"""
FSM States для Telegram бота
"""
from aiogram.fsm.state import State, StatesGroup


class PatientRegistration(StatesGroup):
    """Состояния регистрации пациента"""
    waiting_for_full_name = State()
    waiting_for_department = State()


class SetSurgeryDate(StatesGroup):
    """Состояние установки даты операции"""
    waiting_for_surgery_date = State()
    waiting_for_surgery_name = State()
    waiting_for_reminder_time = State()


class SetDischargeDate(StatesGroup):
    """Состояние установки даты выписки (если нужно раньше 30 дней)"""
    waiting_for_discharge_date = State()


class ManageRoles(StatesGroup):
    """Состояния управления ролями"""
    waiting_for_user_id = State()
    waiting_for_role_selection = State()


class EditReminderTemplate(StatesGroup):
    """Состояния редактирования шаблонов напоминаний"""
    selecting_interval = State()
    waiting_for_template_text = State()


class SubmitHealthReport(StatesGroup):
    """Состояние отправки отчета о состоянии"""
    waiting_for_report_text = State()


class UrgentHealthReport(StatesGroup):
    """Состояние срочной жалобы на состояние здоровья"""
    waiting_for_urgent_report = State()
