"""
Новая система напоминаний на основе даты операции
Автоматические напоминания через 5, 10, 30 дней после операции
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from aiogram import Bot
import pytz
import uuid

from config import TIMEZONE, REMINDER_INTERVALS, DEFAULT_REMINDER_TEMPLATES, AUTO_DELETE_DAY
from services.database import patients_db, reminder_templates_db

logger = logging.getLogger(__name__)

# Глобальный scheduler
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


async def get_reminder_templates():
    """Получает текущие шаблоны напоминаний из SQLite"""
    templates = await reminder_templates_db.read()
    if not templates:
        # Инициализируем шаблонами по умолчанию
        for interval, text in DEFAULT_REMINDER_TEMPLATES.items():
            await reminder_templates_db.update(interval, text)
            templates[interval] = text
    return templates


async def update_reminder_template(interval: int, text: str):
    """Обновляет шаблон напоминания для определенного интервала"""
    await reminder_templates_db.update(interval, text)
    logger.info(f"Updated reminder template for {interval} days")


async def send_surgery_reminder(bot: Bot, user_id: int, days_after: int, patient_id: str):
    """
    Отправляет напоминание пациенту через N дней после операции
    """
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        templates = await get_reminder_templates()
        # SQLite возвращает int ключи, пробуем оба варианта
        message_text = templates.get(days_after) or templates.get(str(days_after), f"Прошло {days_after} дней после операции.")
        
        # Добавляем кнопку для отправки отчета о состоянии
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Сообщить о состоянии",
                callback_data=f"report:{patient_id}:{days_after}"
            )]
        ])
        
        await bot.send_message(
            user_id,
            f"🏥 <b>Напоминание</b>\n\n{message_text}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Surgery reminder sent to {user_id}: {days_after} days")
        
    except Exception as e:
        logger.error(f"Error sending surgery reminder to {user_id}: {e}")


async def delete_patient_after_surgery(patient_id: str):
    """
    Архивирует пациента (мягкое удаление) через 31 день после операции
    """
    try:
        # Вместо полного удаления теперь делаем архивацию
        await patients_db.archive(patient_id)
                
        logger.info(f"Patient {patient_id} auto-archived after 31 days")
            
        # Удаляем все задачи из планировщика (напоминания больше не нужны)
        for interval in REMINDER_INTERVALS:
            job_id = f"reminder_{patient_id}_{interval}"
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
                    
    except Exception as e:
        logger.error(f"Error archiving patient {patient_id}: {e}")



async def create_surgery_reminders(bot: Bot, patient_id: str, surgery_date: datetime):
    """
    Создает автоматические напоминания для пациента после операции
    
    Args:
        bot: Экземпляр бота
        patient_id: ID пациента
        surgery_date: Дата операции
    """
    try:
        patient_data = await patients_db.get(patient_id)
        if not patient_data:
            logger.error(f"Patient {patient_id} not found")
            return
            
        user_id = patient_data["user_id"]
        tz = pytz.timezone(TIMEZONE)
        
        # Определяем время напоминания
        rem_time_str = patient_data.get("reminder_time")
        r_hour, r_minute = 12, 0
        if rem_time_str:
            try:
                dt_obj = datetime.strptime(rem_time_str, "%H:%M")
                r_hour, r_minute = dt_obj.hour, dt_obj.minute
            except ValueError:
                pass

        # Создаем напоминания для каждого интервала
        for days in REMINDER_INTERVALS:
            # Устанавливаем время напоминания
            reminder_date = surgery_date + timedelta(days=days)
            reminder_date = reminder_date.replace(hour=r_hour, minute=r_minute, second=0, microsecond=0)
            
            # Проверяем что дата в будущем
            if reminder_date > datetime.now(tz):
                job_id = f"reminder_{patient_id}_{days}"
                
                # Удаляем старую задачу если существует
                try:
                    scheduler.remove_job(job_id)
                except Exception:
                    pass
                
                # Добавляем новую задачу
                scheduler.add_job(
                    send_surgery_reminder,
                    trigger=DateTrigger(run_date=reminder_date),
                    args=[bot, user_id, days, patient_id],
                    id=job_id,
                    replace_existing=True
                )
                
                logger.info(f"Created reminder for patient {patient_id}: {days} days at {reminder_date}")
        
        # Создаем задачу автоудаления через 31 день
        delete_date = surgery_date + timedelta(days=AUTO_DELETE_DAY)
        if delete_date > datetime.now(tz):
            delete_job_id = f"delete_{patient_id}"
            
            try:
                scheduler.remove_job(delete_job_id)
            except Exception:
                pass
            
            scheduler.add_job(
                delete_patient_after_surgery,
                trigger=DateTrigger(run_date=delete_date),
                args=[patient_id],
                id=delete_job_id,
                replace_existing=True
            )
            
            logger.info(f"Created auto-delete job for patient {patient_id} at {delete_date}")
                
        logger.info(f"All surgery reminders created for patient {patient_id}")
        
    except Exception as e:
        logger.error(f"Error creating surgery reminders: {e}")


async def cancel_surgery_reminders(patient_id: str):
    """
    Отменяет все напоминания для пациента
    """
    try:
        for days in REMINDER_INTERVALS:
            job_id = f"reminder_{patient_id}_{days}"
            try:
                scheduler.remove_job(job_id)
                logger.info(f"Cancelled reminder {job_id}")
            except Exception:
                pass
        
        # Также отменяем задачу удаления
        delete_job_id = f"delete_{patient_id}"
        try:
            scheduler.remove_job(delete_job_id)
            logger.info(f"Cancelled auto-delete {delete_job_id}")
        except Exception:
            pass
                
    except Exception as e:
        logger.error(f"Error cancelling reminders for {patient_id}: {e}")


async def restore_surgery_reminders(bot: Bot):
    """
    Восстанавливает все напоминания из базы данных при запуске бота
    """
    logger.info("Restoring surgery reminders from database...")
    
    try:
        patients = await patients_db.read()
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        
        for patient_id, patient_data in patients.items():
            try:
                # Пропускаем архивных пациентов
                if patient_data.get("is_archived"):
                    continue

                surgery_date_str = patient_data.get("surgery_date")
                if not surgery_date_str:
                    continue
                    
                surgery_date = datetime.fromisoformat(surgery_date_str)
                
                # Определяем время
                rem_time_str = patient_data.get("reminder_time")
                r_hour, r_minute = 12, 0
                if rem_time_str:
                    try:
                        dt_obj = datetime.strptime(rem_time_str, "%H:%M")
                        r_hour, r_minute = dt_obj.hour, dt_obj.minute
                    except ValueError:
                        pass

                # Восстанавливаем напоминания
                for days in REMINDER_INTERVALS:
                    reminder_date = surgery_date + timedelta(days=days)
                    reminder_date = reminder_date.replace(hour=r_hour, minute=r_minute, second=0, microsecond=0)
                    
                    if reminder_date > now:
                        # Напоминание еще не прошло
                        job_id = f"reminder_{patient_id}_{days}"
                        
                        scheduler.add_job(
                            send_surgery_reminder,
                            trigger=DateTrigger(run_date=reminder_date),
                            args=[bot, patient_data["user_id"], days, patient_id],
                            id=job_id,
                            replace_existing=True
                        )
                        logger.info(f"Restored reminder: {job_id}")

                # Восстанавливаем задачу удаления
                delete_date = surgery_date + timedelta(days=AUTO_DELETE_DAY)
                if delete_date <= now:
                    # 31 день прошел, удаляем пациента
                    logger.info(f"Auto-deleting expired patient {patient_id}")
                    await delete_patient_after_surgery(patient_id)
                else:
                    # Восстанавливаем задачу удаления
                    delete_job_id = f"delete_{patient_id}"
                    scheduler.add_job(
                        delete_patient_after_surgery,
                        trigger=DateTrigger(run_date=delete_date),
                        args=[patient_id],
                        id=delete_job_id,
                        replace_existing=True
                    )
                    logger.info(f"Restored auto-delete job: {delete_job_id}")
                        
            except Exception as e:
                logger.error(f"Error restoring reminders for patient {patient_id}: {e}")
        
        logger.info("Surgery reminders restoration completed")
        
    except Exception as e:
        logger.error(f"Error restoring surgery reminders: {e}")


def start_scheduler():
    """Запускает планировщик"""
    if not scheduler.running:
        scheduler.start()
        logger.info("Reminder scheduler started")


def shutdown_scheduler():
    """Останавливает планировщик"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Reminder scheduler stopped")
