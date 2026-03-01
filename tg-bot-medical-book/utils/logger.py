"""
Система логирования действий администраторов
Логи сохраняются по дням в папку log/
"""
import logging
from datetime import datetime
from pathlib import Path
import pytz
from config import TIMEZONE

# Создаем директорию для логов
LOG_DIR = Path(__file__).parent.parent / "log"
LOG_DIR.mkdir(exist_ok=True)


def get_admin_logger(name: str = "admin_actions") -> logging.Logger:
    """
    Создает или возвращает логгер для действий администраторов
    Каждый день создается новый файл лога
    """
    logger = logging.getLogger(name)
    
    # Если логгер уже настроен, возвращаем его
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    
    # Получаем текущую дату для имени файла
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    
    # Имя файла: admin_actions_2026-01-07.log
    log_file = LOG_DIR / f"admin_actions_{date_str}.log"
    
    # Создаем handler для файла
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # Формат логов: [2026-01-07 14:30:45] ACTION: message
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    
    return logger


def log_admin_action(admin_id: int, action: str, details: str = ""):
    """
    Логирует действие администратора
    
    Args:
        admin_id: Telegram ID администратора
        action: Тип действия (например: "Добавил напоминание", "Удалил пациента")
        details: Дополнительные детали
    """
    logger = get_admin_logger()
    
    message = f"Админ {admin_id} - {action}"
    if details:
        message += f" | {details}"
    
    logger.info(message)


def log_patient_action(user_id: int, action: str, details: str = ""):
    """
    Логирует действие пациента (если нужно)
    
    Args:
        user_id: Telegram ID пользователя
        action: Тип действия
        details: Дополнительные детали
    """
    logger = get_admin_logger("patient_actions")
    
    message = f"Пациент {user_id} - {action}"
    if details:
        message += f" | {details}"
    
    logger.info(message)
