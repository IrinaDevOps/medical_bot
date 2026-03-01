"""
Система сохранения отчетов о состоянии пациентов
Отчеты хранятся в SQLite базе данных
"""
import logging
from datetime import datetime
import pytz
from config import TIMEZONE
from services.database import patients_db, staff_db, health_reports_db
from aiogram import Bot

logger = logging.getLogger(__name__)


async def save_health_report(patient_id: str, days_after: int, report_text: str, 
                             user_id: int = None, is_urgent: bool = False):
    """
    Сохраняет отчет о состоянии пациента
    
    Args:
        patient_id: ID пациента
        days_after: День после операции (5, 10, 30)
        report_text: Текст отчета
        user_id: Telegram ID пациента
        is_urgent: Срочный отчет
    """
    try:
        # Если user_id не передан, получаем из данных пациента
        if user_id is None:
            patient_data = await patients_db.get(patient_id)
            user_id = patient_data.get("user_id", 0) if patient_data else 0
        
        # Сохраняем в SQLite
        report_id = await health_reports_db.save_report(
            patient_id=patient_id,
            user_id=user_id,
            day=days_after,
            text=report_text,
            is_urgent=is_urgent
        )
        
        logger.info(f"Health report #{report_id} saved for patient {patient_id}, day {days_after}")
        return report_id
        
    except Exception as e:
        logger.error(f"Error saving health report: {e}")
        return None


async def get_patient_reports(patient_id: str) -> dict:
    """
    Получает все отчеты пациента
    
    Returns:
        dict: Словарь с отчетами в старом формате для совместимости
    """
    try:
        reports = await health_reports_db.get_patient_reports(patient_id)
        
        if not reports:
            return {}
        
        # Преобразуем в старый формат для совместимости
        result = {
            "patient_id": patient_id,
            "reports": {}
        }
        
        for report in reports:
            day = str(report.get("day", 0))
            # Сохраняем только последний отчет за каждый день
            if day not in result["reports"]:
                result["reports"][day] = {
                    "text": report.get("text", ""),
                    "submitted_at": report.get("submitted_at", ""),
                    "is_urgent": report.get("is_urgent", False)
                }
        
        return result
            
    except Exception as e:
        logger.error(f"Error reading health reports: {e}")
        return {}


async def notify_admins_about_report(bot: Bot, patient_id: str, days_after: int, 
                                      report_text: str, is_urgent: bool = False):
    """
    Отправляет уведомление всем администраторам о новом отчете пациента
    """
    try:
        # Получаем данные пациента
        patient_data = await patients_db.get(patient_id)
        if not patient_data:
            logger.error(f"Patient {patient_id} not found for admin notification")
            return
        
        full_name = patient_data.get("full_name", "Неизвестно")
        department = patient_data.get("department", "Не указано")
        
        # Получаем всех администраторов
        staff = await staff_db.read()
        
        # Формируем сообщение
        if is_urgent:
            message = (
                f"🚨 <b>СРОЧНАЯ ЖАЛОБА НА СОСТОЯНИЕ</b>\n\n"
                f"👤 Пациент: {full_name}\n"
                f"🏥 Отделение: {department}\n\n"
                f"<b>Сообщение:</b>\n{report_text}"
            )
        else:
            message = (
                f"📋 <b>Новый отчет о состоянии</b>\n\n"
                f"👤 Пациент: {full_name}\n"
                f"🏥 Отделение: {department}\n"
                f"📅 День после операции: {days_after}\n\n"
                f"<b>Сообщение:</b>\n{report_text}"
            )
        
        # Отправляем всем админам
        for user_id_str, staff_data in staff.items():
            try:
                admin_id = int(user_id_str)
                await bot.send_message(admin_id, message, parse_mode="HTML")
                logger.info(f"Report notification sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {user_id_str}: {e}")
        
    except Exception as e:
        logger.error(f"Error notifying admins: {e}")
