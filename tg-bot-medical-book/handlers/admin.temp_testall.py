
@router.message(Command("testall"))
async def cmd_test_all(message: Message):
    """
    Полный системный тест:
    1. БД (персонал, пациенты)
    2. Пациент: Создание -> Архивация -> Повторная регистрация
    3. Отчеты: Пробная генерация Excel
    """
    # Проверка прав (только персонал)
    if not await is_staff(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return

    start_time = datetime.now()
    log = []
    log.append(f"🧪 <b>Запуск полного тестирования системы</b>")
    log.append(f"📅 Дата: {start_time.strftime('%d.%m.%Y %H:%M:%S')}")
    
    test_message = await message.answer("\n".join(log) + "\n\n⏳ <i>Выполнение тестов...</i>", parse_mode="HTML")
    
    try:
        # === ТЕСТ 1: База данных (Персонал) ===
        log.append("\n<b>1. Проверка базы данных (Персонал)</b>")
        try:
            # Проверяем существование текущего админа
            admin_check = await staff_db.exists(str(message.from_user.id))
            if admin_check:
                log.append("✅ Connection OK: Текущий пользователь найден в БД")
            else:
                log.append("⚠️ Warning: Текущий пользователь не найден в БД (возможно Суперадмин без записи)")
                # Для суперадмина это нормально, проверим просто чтение
                await staff_db.read()
                log.append("✅ Connection OK: Чтение таблицы staff успешно")
        except Exception as e:
            log.append(f"❌ ERROR: Сбой работы с БД персонала: {e}")
            raise e

        # === ТЕСТ 2: Жизненный цикл пациента ===
        log.append("\n<b>2. Тест жизненного цикла пациента</b>")
        test_user_id = 888888888 # Специальный ID для этого теста
        
        try:
            # 2.1 Очистка
            await patients_db.delete_by_user_id(test_user_id)
            
            # 2.2 Регистрация (Операция 1)
            p1_id = f"test_sys_{int(datetime.now().timestamp())}_1"
            p1_data = {
                "user_id": test_user_id,
                "full_name": "System Test User",
                "department": DEPARTMENTS[0],
                "registration_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "surgery_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "surgery_name": "Test Surgery 1",
                "is_archived": 0
            }
            await patients_db.update(p1_id, p1_data)
            
            # Проверка
            check_1 = await patients_db.get_by_user_id(test_user_id)
            if check_1 and check_1[0] == p1_id:
                log.append("✅ Шаг 1: Пациент создан и активен")
            else:
                raise Exception("Пациент не найден после создания")

            # 2.3 Архивация (имитация 31 дня)
            from services.reminder_system import delete_patient_after_surgery
            await delete_patient_after_surgery(p1_id)
            
            # Проверка архивации
            check_arch = await patients_db.get(p1_id)
            check_lookup = await patients_db.get_by_user_id(test_user_id)
            
            if check_arch["is_archived"] == 1 and check_lookup is None:
                log.append("✅ Шаг 2: Пациент успешно архивирован и скрыт")
            else:
                raise Exception(f"Ошибка архивации. is_archived={check_arch.get('is_archived')}, lookup={check_lookup}")
            
            # 2.4 Повторная регистрация (Операция 2)
            p2_id = f"test_sys_{int(datetime.now().timestamp())}_2"
            p2_data = {
                "user_id": test_user_id,
                "full_name": "System Test User (Cycle 2)",
                "department": DEPARTMENTS[0],
                "registration_date": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "is_archived": 0
            }
            await patients_db.update(p2_id, p2_data)
            
            # Проверка
            check_2 = await patients_db.get_by_user_id(test_user_id)
            if check_2 and check_2[0] == p2_id:
                log.append("✅ Шаг 3: Повторная регистрация успешна")
            else:
                raise Exception("Ошибка повторной регистрации")
                
        except Exception as e:
            log.append(f"❌ ERROR: Сбой в тесте пациента: {e}")
            raise e

        # === ТЕСТ 3: Генерация Excel ===
        log.append("\n<b>3. Тест генерации отчетов</b>")
        try:
            file_io = await export_patients_to_excel()
            size = file_io.getbuffer().nbytes
            if size > 0:
                log.append(f"✅ Excel сгенерирован в памяти (Размер: {size} байт)")
                log.append("✅ Файловая система чиста (файл не сохранен на диск)")
            else:
                raise Exception("Сгенерирован пустой файл")
        except Exception as e:
            log.append(f"❌ ERROR: Ошибка экспорта: {e}")
            raise e

        # === Финал ===
        duration = (datetime.now() - start_time).total_seconds()
        log.append(f"\n🏁 <b>Тестирование завершено успешно!</b>")
        log.append(f"⏱ Время выполнения: {duration:.2f} сек")
        
        # Очистка тестовых данных
        await patients_db.delete_by_user_id(test_user_id)
        
    except Exception as global_e:
        log.append(f"\n📛 <b>ТЕСТ ПРЕРВАН С ОШИБКОЙ</b>")
        logger.error(f"TestAll Failed: {global_e}")
    
    # Обновляем сообщение
    await test_message.edit_text("\n".join(log), parse_mode="HTML")
