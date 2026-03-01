"""
SQLite Database Manager для медицинского бота
Асинхронная работа с базой данных через aiosqlite
"""
import aiosqlite
import json
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime

from config import DATABASE_FILE


class SQLiteDatabase:
    """Асинхронный менеджер SQLite базы данных"""
    
    _instance = None
    _initialized = False
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.db_path = DATABASE_FILE
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        async with self._lock:
            if self._initialized:
                return
            
            async with aiosqlite.connect(self.db_path) as db:
                # Включаем WAL режим для лучшей производительности
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                
                # Таблица пациентов
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS patients (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        full_name TEXT NOT NULL,
                        department TEXT,
                        registration_date TEXT,
                        surgery_date TEXT,
                        auto_delete_date TEXT
                    )
                """)
                
                # Индекс для быстрого поиска по user_id
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_patients_user_id 
                    ON patients(user_id)
                """)
                
                # Миграция: добавляем новые колонки если их нет
                cursor = await db.execute("PRAGMA table_info(patients)")
                existing_cols = {row[1] for row in await cursor.fetchall()}
                
                # Добавляем surgery_name и reminder_time
                for col_name, col_type in [("surgery_name", "TEXT"), ("reminder_time", "TEXT")]:
                    if col_name not in existing_cols:
                        await db.execute(f"ALTER TABLE patients ADD COLUMN {col_name} {col_type}")
                
                # Добавляем флаг is_archived (для мяткого удаления)
                if "is_archived" not in existing_cols:
                    await db.execute("ALTER TABLE patients ADD COLUMN is_archived INTEGER DEFAULT 0")

                # Таблица персонала
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS staff (
                        user_id TEXT PRIMARY KEY,
                        role TEXT NOT NULL,
                        assigned_by TEXT,
                        assigned_at TEXT
                    )
                """)
                
                # Таблица напоминаний
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS reminders (
                        id TEXT PRIMARY KEY,
                        patient_id TEXT,
                        reminder_type TEXT,
                        scheduled_time TEXT,
                        data TEXT
                    )
                """)
                
                # Таблица шаблонов напоминаний
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS reminder_templates (
                        day INTEGER PRIMARY KEY,
                        template TEXT NOT NULL
                    )
                """)
                
                # Таблица отчётов о здоровье
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS health_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        patient_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        day INTEGER,
                        text TEXT,
                        is_urgent INTEGER DEFAULT 0,
                        submitted_at TEXT
                    )
                """)
                
                # Индексы для отчётов
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_reports_patient_id 
                    ON health_reports(patient_id)
                """)
                
                await db.commit()
            
            self._initialized = True
    
    async def _get_connection(self):
        """Получить соединение с БД"""
        if not self._initialized:
            await self.init_db()
        return aiosqlite.connect(self.db_path)


class PatientsDB:
    """Менеджер таблицы пациентов с API совместимым с JSONDatabase"""
    
    def __init__(self, sqlite_db: SQLiteDatabase):
        self.db = sqlite_db
    
    async def read(self) -> Dict[str, Any]:
        """Читает всех пациентов как словарь {patient_id: data}"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM patients")
            rows = await cursor.fetchall()
            
            result = {}
            for row in rows:
                result[row["id"]] = {
                    "user_id": row["user_id"],
                    "full_name": row["full_name"],
                    "department": row["department"],
                    "registration_date": row["registration_date"],
                    "surgery_date": row["surgery_date"],
                    "auto_delete_date": row["auto_delete_date"],
                    "surgery_name": row["surgery_name"] if "surgery_name" in row.keys() else None,
                    "reminder_time": row["reminder_time"] if "reminder_time" in row.keys() else None,
                    "is_archived": row["is_archived"] if "is_archived" in row.keys() else 0
                }
            return result
    
    async def update(self, patient_id: str, data: Dict[str, Any]):
        """Добавляет или обновляет пациента"""
        async with await self.db._get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO patients 
                (id, user_id, full_name, department, registration_date, surgery_date, auto_delete_date, surgery_name, reminder_time, is_archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                patient_id,
                data.get("user_id"),
                data.get("full_name"),
                data.get("department"),
                data.get("registration_date"),
                data.get("surgery_date"),
                data.get("auto_delete_date"),
                data.get("surgery_name"),
                data.get("reminder_time"),
                data.get("is_archived", 0)
            ))
            await conn.commit()
    
    async def delete(self, patient_id: str):
        """Удаляет пациента (полное удаление)"""
        async with await self.db._get_connection() as conn:
            await conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
            await conn.commit()

    async def delete_by_user_id(self, user_id: int):
        """Удаляет всех пациентов с данным user_id (полное удаление)"""
        async with await self.db._get_connection() as conn:
            await conn.execute("DELETE FROM patients WHERE user_id = ?", (user_id,))
            await conn.commit()
            
    async def archive(self, patient_id: str):
        """Архивирует пациента (мягкое удаление)"""
        async with await self.db._get_connection() as conn:
            await conn.execute(
                "UPDATE patients SET is_archived = 1 WHERE id = ?", 
                (patient_id,)
            )
            await conn.commit()
    
    async def get(self, patient_id: str, default=None) -> Optional[Dict[str, Any]]:
        """Получает пациента по ID"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM patients WHERE id = ?", (patient_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return default
            
            return {
                "user_id": row["user_id"],
                "full_name": row["full_name"],
                "department": row["department"],
                "registration_date": row["registration_date"],
                "surgery_date": row["surgery_date"],
                "auto_delete_date": row["auto_delete_date"],
                "surgery_name": row["surgery_name"] if "surgery_name" in row.keys() else None,
                "reminder_time": row["reminder_time"] if "reminder_time" in row.keys() else None,
                "is_archived": row["is_archived"] if "is_archived" in row.keys() else 0
            }
    
    async def exists(self, patient_id: str) -> bool:
        """Проверяет существование пациента"""
        async with await self.db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
            )
            return await cursor.fetchone() is not None
    
    async def get_by_user_id(self, user_id: int) -> Optional[tuple]:
        """Получает АКТИВНОГО (не архивного) пациента по Telegram user_id"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM patients WHERE user_id = ? AND (is_archived = 0 OR is_archived IS NULL)", 
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return (row["id"], {
                "user_id": row["user_id"],
                "full_name": row["full_name"],
                "department": row["department"],
                "registration_date": row["registration_date"],
                "surgery_date": row["surgery_date"],
                "auto_delete_date": row["auto_delete_date"],
                "surgery_name": row["surgery_name"] if "surgery_name" in row.keys() else None,
                "reminder_time": row["reminder_time"] if "reminder_time" in row.keys() else None,
                "is_archived": row["is_archived"] if "is_archived" in row.keys() else 0
            })
    
    async def get_by_department(self, department: str) -> List[tuple]:
        """Получает активных (не архивных) пациентов по отделению"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            # Добавлен фильтр по is_archived
            cursor = await conn.execute(
                "SELECT * FROM patients WHERE department = ? AND (is_archived = 0 OR is_archived IS NULL)", 
                (department,)
            )
            rows = await cursor.fetchall()
            
            result = []
            for row in rows:
                result.append((row["id"], {
                    "user_id": row["user_id"],
                    "full_name": row["full_name"],
                    "department": row["department"],
                    "registration_date": row["registration_date"],
                    "surgery_date": row["surgery_date"],
                    "auto_delete_date": row["auto_delete_date"],
                    "surgery_name": row["surgery_name"] if "surgery_name" in row.keys() else None,
                    "reminder_time": row["reminder_time"] if "reminder_time" in row.keys() else None,
                    "is_archived": row["is_archived"] if "is_archived" in row.keys() else 0
                }))
            return result

    async def get_department_counts(self) -> Dict[str, int]:
        """Возвращает количество активных пациентов по отделениям"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            # Добавлен фильтр по is_archived
            cursor = await conn.execute(
                "SELECT department, COUNT(*) as count FROM patients WHERE (is_archived = 0 OR is_archived IS NULL) GROUP BY department"
            )
            rows = await cursor.fetchall()
            return {row["department"]: row["count"] for row in rows}


class StaffDB:
    """Менеджер таблицы персонала с API совместимым с JSONDatabase"""
    
    def __init__(self, sqlite_db: SQLiteDatabase):
        self.db = sqlite_db
    
    async def read(self) -> Dict[str, Any]:
        """Читает весь персонал как словарь {user_id: data}"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM staff")
            rows = await cursor.fetchall()
            
            result = {}
            for row in rows:
                result[row["user_id"]] = {
                    "user_id": int(row["user_id"]) if row["user_id"].isdigit() else row["user_id"],
                    "role": row["role"],
                    "assigned_by": row["assigned_by"],
                    "assigned_at": row["assigned_at"]
                }
            return result
    
    async def update(self, user_id: str, data: Dict[str, Any]):
        """Добавляет или обновляет сотрудника"""
        async with await self.db._get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO staff 
                (user_id, role, assigned_by, assigned_at)
                VALUES (?, ?, ?, ?)
            """, (
                str(user_id),
                data.get("role"),
                data.get("assigned_by"),
                data.get("assigned_at")
            ))
            await conn.commit()
    
    async def delete(self, user_id: str):
        """Удаляет сотрудника"""
        async with await self.db._get_connection() as conn:
            await conn.execute("DELETE FROM staff WHERE user_id = ?", (str(user_id),))
            await conn.commit()
    
    async def get(self, user_id: str, default=None) -> Optional[Dict[str, Any]]:
        """Получает сотрудника по user_id"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM staff WHERE user_id = ?", (str(user_id),)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return default
            
            return {
                "user_id": int(row["user_id"]) if row["user_id"].isdigit() else row["user_id"],
                "role": row["role"],
                "assigned_by": row["assigned_by"],
                "assigned_at": row["assigned_at"]
            }
    
    async def exists(self, user_id: str) -> bool:
        """Проверяет существование сотрудника"""
        async with await self.db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM staff WHERE user_id = ?", (str(user_id),)
            )
            return await cursor.fetchone() is not None


class RemindersDB:
    """Менеджер таблицы напоминаний с API совместимым с JSONDatabase"""
    
    def __init__(self, sqlite_db: SQLiteDatabase):
        self.db = sqlite_db
    
    async def read(self) -> Dict[str, Any]:
        """Читает все напоминания как словарь {reminder_id: data}"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM reminders")
            rows = await cursor.fetchall()
            
            result = {}
            for row in rows:
                data = json.loads(row["data"]) if row["data"] else {}
                result[row["id"]] = {
                    "patient_id": row["patient_id"],
                    "type": row["reminder_type"],
                    "scheduled_time": row["scheduled_time"],
                    **data
                }
            return result
    
    async def update(self, reminder_id: str, data: Dict[str, Any]):
        """Добавляет или обновляет напоминание"""
        # Извлекаем основные поля, остальное в JSON
        patient_id = data.pop("patient_id", None)
        reminder_type = data.pop("type", None)
        scheduled_time = data.pop("scheduled_time", None)
        extra_data = json.dumps(data, ensure_ascii=False) if data else None
        
        async with await self.db._get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO reminders 
                (id, patient_id, reminder_type, scheduled_time, data)
                VALUES (?, ?, ?, ?, ?)
            """, (reminder_id, patient_id, reminder_type, scheduled_time, extra_data))
            await conn.commit()
    
    async def delete(self, reminder_id: str):
        """Удаляет напоминание"""
        async with await self.db._get_connection() as conn:
            await conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            await conn.commit()
    
    async def get(self, reminder_id: str, default=None) -> Optional[Dict[str, Any]]:
        """Получает напоминание по ID"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return default
            
            data = json.loads(row["data"]) if row["data"] else {}
            return {
                "patient_id": row["patient_id"],
                "type": row["reminder_type"],
                "scheduled_time": row["scheduled_time"],
                **data
            }
    
    async def exists(self, reminder_id: str) -> bool:
        """Проверяет существование напоминания"""
        async with await self.db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM reminders WHERE id = ?", (reminder_id,)
            )
            return await cursor.fetchone() is not None
    
    async def delete_by_patient(self, patient_id: str):
        """Удаляет все напоминания пациента"""
        async with await self.db._get_connection() as conn:
            await conn.execute(
                "DELETE FROM reminders WHERE patient_id = ?", (patient_id,)
            )
            await conn.commit()


class ReminderTemplatesDB:
    """Менеджер шаблонов напоминаний"""
    
    def __init__(self, sqlite_db: SQLiteDatabase):
        self.db = sqlite_db
    
    async def read(self) -> Dict[int, str]:
        """Читает все шаблоны"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM reminder_templates")
            rows = await cursor.fetchall()
            
            return {row["day"]: row["template"] for row in rows}
    
    async def update(self, day: int, template: str):
        """Обновляет шаблон для дня"""
        async with await self.db._get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO reminder_templates (day, template)
                VALUES (?, ?)
            """, (day, template))
            await conn.commit()
    
    async def get(self, day: int, default=None) -> Optional[str]:
        """Получает шаблон по дню"""
        async with await self.db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT template FROM reminder_templates WHERE day = ?", (day,)
            )
            row = await cursor.fetchone()
            return row[0] if row else default


class HealthReportsDB:
    """Менеджер отчётов о здоровье"""
    
    def __init__(self, sqlite_db: SQLiteDatabase):
        self.db = sqlite_db
    
    async def save_report(self, patient_id: str, user_id: int, day: int, 
                          text: str, is_urgent: bool = False) -> int:
        """Сохраняет отчёт о здоровье"""
        async with await self.db._get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO health_reports 
                (patient_id, user_id, day, text, is_urgent, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                patient_id,
                user_id,
                day,
                text,
                1 if is_urgent else 0,
                datetime.now().isoformat()
            ))
            await conn.commit()
            return cursor.lastrowid
    
    async def get_patient_reports(self, patient_id: str) -> List[Dict[str, Any]]:
        """Получает все отчёты пациента"""
        async with await self.db._get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM health_reports 
                WHERE patient_id = ? 
                ORDER BY submitted_at DESC
            """, (patient_id,))
            rows = await cursor.fetchall()
            
            return [{
                "id": row["id"],
                "patient_id": row["patient_id"],
                "user_id": row["user_id"],
                "day": row["day"],
                "text": row["text"],
                "is_urgent": bool(row["is_urgent"]),
                "submitted_at": row["submitted_at"]
            } for row in rows]
    
    async def get_reports_by_day(self, patient_id: str) -> Dict[int, Dict[str, Any]]:
        """Получает отчёты пациента сгруппированные по дням"""
        reports = await self.get_patient_reports(patient_id)
        result = {}
        for report in reports:
            day = report.get("day", 0)
            if day not in result:
                result[day] = report
        return result


# Глобальный экземпляр базы данных
sqlite_db = SQLiteDatabase()

# Глобальные экземпляры менеджеров таблиц (совместимы с API JSONDatabase)
patients_db = PatientsDB(sqlite_db)
staff_db = StaffDB(sqlite_db)
reminders_db = RemindersDB(sqlite_db)
reminder_templates_db = ReminderTemplatesDB(sqlite_db)
health_reports_db = HealthReportsDB(sqlite_db)
