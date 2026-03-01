"""
Медицинский Telegram Бот
Точка входа приложения
"""
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat

from config import BOT_TOKEN,  SUPERADMIN_ID
from handlers import common, patient, admin
from services import reminder_system
from services.database import staff_db, sqlite_db
from utils.logger import log_admin_action

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


async def setup_bot_commands(bot: Bot):
    """Устанавливает команды бота для меню Telegram"""
    
    # Команды для всех пользователей (пациенты)
    user_commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="register", description="📝 Регистрация пациента"),
        BotCommand(command="info", description="👤 Моя информация"),
        BotCommand(command="report", description="🚨 Сообщить об ухудшении"),
        BotCommand(command="help", description="ℹ️ Помощь"),
    ]
    
    # Команды для персонала
    staff_commands = [
        BotCommand(command="start", description="🏠 Панель управления"),
        BotCommand(command="patients", description="👥 Список пациентов"),
        BotCommand(command="test", description="🧪 Тест напоминаний"),
        BotCommand(command="help", description="ℹ️ Помощь"),
    ]
    
    # Устанавливаем команды по умолчанию для всех
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    
    # Устанавливаем команды для персонала
    staff = await staff_db.read()
    for user_id_str in staff.keys():
        try:
            user_id = int(user_id_str)
            await bot.set_my_commands(
                staff_commands, 
                scope=BotCommandScopeChat(chat_id=user_id)
            )
        except Exception as e:
            logger.warning(f"Could not set commands for user {user_id_str}: {e}")
    
    logger.info("Bot commands registered")


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    logger.info("Bot starting...")
    
    # Инициализируем SQLite базу данных
    await sqlite_db.init_db()
    logger.info("SQLite database initialized")
    
    # Инициализируем суперадмина в базе персонала
    staff = await staff_db.read()
    if str(SUPERADMIN_ID) not in staff:
        await staff_db.update(str(SUPERADMIN_ID), {
            "user_id": SUPERADMIN_ID,
            "role": "superadmin",
            "assigned_at": "system"
        })
        logger.info(f"Superadmin {SUPERADMIN_ID} initialized")
    
    # Устанавливаем команды бота
    await setup_bot_commands(bot)
    
    # Запускаем планировщик
    reminder_system.start_scheduler()
    
    # Восстанавливаем задачи из базы данных
    await reminder_system.restore_surgery_reminders(bot)
    
    # Логируем запуск бота
    log_admin_action(SUPERADMIN_ID, "Бот запущен", f"Суперадмин ID: {SUPERADMIN_ID}")
    
    logger.info("Bot started successfully!")


async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("Bot shutting down...")
    
    # Останавливаем планировщик
    reminder_system.shutdown_scheduler()
    
    logger.info("Bot stopped")


async def main():
    """Главная функция"""
    
    # Проверяем токен
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN not set! Please create .env file or set environment variable.")
        logger.error("Example: BOT_TOKEN=your_bot_token_from_botfather")
        sys.exit(1)
    
    # Проверяем SUPERADMIN_ID
    if SUPERADMIN_ID == 0:
        logger.error("SUPERADMIN_ID not set! Please create .env file or set environment variable.")
        logger.error("Example: SUPERADMIN_ID=your_telegram_id")
        sys.exit(1)
    
    # Инициализируем бота и диспетчер
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    
    # Регистрируем роутеры
    # Порядок важен: сначала админ, потом пациент, потом общие
    dp.include_router(admin.router)
    dp.include_router(patient.router)
    dp.include_router(common.router)
    
    # Действия при запуске/остановке
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Обработчик ошибок
    @dp.error()
    async def global_error_handler(event):
        logger.error(f"Global error: {event.exception}", exc_info=True)

    try:
        # Запускаем бота
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
