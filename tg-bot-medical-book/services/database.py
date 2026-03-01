"""
Database Manager для медицинского бота
Экспортирует глобальные экземпляры баз данных
"""

# Используем SQLite базу данных
from services.sqlite_db import (
    sqlite_db,
    patients_db,
    staff_db,
    reminders_db,
    reminder_templates_db,
    health_reports_db
)

# Экспортируем для обратной совместимости
__all__ = [
    'sqlite_db',
    'patients_db',
    'staff_db', 
    'reminders_db',
    'reminder_templates_db',
    'health_reports_db'
]
