#!/bin/bash
#
# Скрипт установки Telegram бота для медицинского учреждения
# Запуск: bash install.sh
#

set -e

# ===== КОНФИГУРАЦИЯ =====
# Замените на вашу ссылку на архив с облака (прямая ссылка на скачивание)
CLOUD_URL="ВСТАВЬТЕ_ССЫЛКУ_НА_АРХИВ_С_ОБЛАКА"

# Токен бота (получить у @BotFather)
BOT_TOKEN="ВСТАВЬТЕ_ВАШ_ТОКЕН_БОТА"

# Telegram ID суперадминистратора (узнать у @userinfobot)
SUPERADMIN_ID="ВСТАВЬТЕ_ВАШ_TELEGRAM_ID"

# Директория установки
INSTALL_DIR="/opt/medicalbook-bot"

# Имя пользователя для запуска бота
BOT_USER="medbot"

# ===== ЦВЕТА ДЛЯ ВЫВОДА =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Установка MedicalBook Telegram Bot   ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# ===== ПРОВЕРКА ROOT =====
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Этот скрипт должен быть запущен от root${NC}"
   echo "Используйте: sudo bash install.sh"
   exit 1
fi

# ===== ПРОВЕРКА КОНФИГУРАЦИИ =====
if [[ "$CLOUD_URL" == "ВСТАВЬТЕ_ССЫЛКУ_НА_АРХИВ_С_ОБЛАКА" ]]; then
    echo -e "${RED}Ошибка: Не указана ссылка на архив!${NC}"
    echo "Откройте install.sh и замените CLOUD_URL на вашу ссылку"
    exit 1
fi

if [[ "$BOT_TOKEN" == "ВСТАВЬТЕ_ВАШ_ТОКЕН_БОТА" ]]; then
    echo -e "${RED}Ошибка: Не указан токен бота!${NC}"
    echo "Откройте install.sh и замените BOT_TOKEN на ваш токен от @BotFather"
    exit 1
fi

if [[ "$SUPERADMIN_ID" == "ВСТАВЬТЕ_ВАШ_TELEGRAM_ID" ]]; then
    echo -e "${RED}Ошибка: Не указан ID суперадминистратора!${NC}"
    echo "Откройте install.sh и замените SUPERADMIN_ID на ваш Telegram ID"
    exit 1
fi

# ===== УСТАНОВКА ЗАВИСИМОСТЕЙ =====
echo -e "${YELLOW}[1/7] Установка системных зависимостей...${NC}"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv unzip curl wget sqlite3

# ===== СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ =====
echo -e "${YELLOW}[2/7] Создание пользователя ${BOT_USER}...${NC}"
if id "$BOT_USER" &>/dev/null; then
    echo "Пользователь $BOT_USER уже существует"
else
    useradd -r -s /bin/false -m -d /home/$BOT_USER $BOT_USER
    echo "Пользователь $BOT_USER создан"
fi

# ===== СКАЧИВАНИЕ БОТА =====
echo -e "${YELLOW}[3/7] Скачивание бота с облака...${NC}"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# Определяем тип ссылки и скачиваем
if [[ "$CLOUD_URL" == *"drive.google.com"* ]]; then
    # Google Drive
    FILE_ID=$(echo $CLOUD_URL | grep -oP '(?<=d/)[^/]+|(?<=id=)[^&]+')
    wget --quiet --show-progress -O bot.zip "https://drive.google.com/uc?export=download&id=$FILE_ID"
elif [[ "$CLOUD_URL" == *"dropbox.com"* ]]; then
    # Dropbox
    wget --quiet --show-progress -O bot.zip "${CLOUD_URL/www.dropbox.com/dl.dropboxusercontent.com}"
elif [[ "$CLOUD_URL" == *"yandex"* ]]; then
    # Яндекс.Диск - нужна прямая ссылка
    curl -L -o bot.zip "$CLOUD_URL"
else
    # Прямая ссылка
    wget --quiet --show-progress -O bot.zip "$CLOUD_URL"
fi

# ===== РАСПАКОВКА =====
echo -e "${YELLOW}[4/7] Распаковка архива...${NC}"
if [[ -f bot.zip ]]; then
    unzip -o bot.zip -d .
    rm bot.zip
    
    # Если внутри архива есть вложенная папка, переместить содержимое
    NESTED_DIR=$(find . -maxdepth 1 -type d -name '*bot*' | head -1)
    if [[ -n "$NESTED_DIR" && "$NESTED_DIR" != "." ]]; then
        mv "$NESTED_DIR"/* . 2>/dev/null || true
        rm -rf "$NESTED_DIR"
    fi
else
    echo -e "${RED}Ошибка: Не удалось скачать архив${NC}"
    exit 1
fi

# ===== СОЗДАНИЕ ВИРТУАЛЬНОГО ОКРУЖЕНИЯ =====
echo -e "${YELLOW}[5/7] Создание виртуального окружения Python...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ===== СОЗДАНИЕ .env ФАЙЛА =====
echo -e "${YELLOW}[6/7] Настройка конфигурации...${NC}"
cat > .env << EOF
# Конфигурация MedicalBook Telegram Bot
# Создано автоматически скриптом установки

BOT_TOKEN=$BOT_TOKEN
SUPERADMIN_ID=$SUPERADMIN_ID
TIMEZONE=Asia/Novosibirsk
DB_PATH=data/medical_bot.db
EOF

# Создаем необходимые директории
mkdir -p data log

# Устанавливаем права
chown -R $BOT_USER:$BOT_USER $INSTALL_DIR
chmod 600 .env

# ===== СОЗДАНИЕ SYSTEMD СЕРВИСА =====
echo -e "${YELLOW}[7/7] Создание systemd сервиса...${NC}"
cat > /etc/systemd/system/medicalbook-bot.service << EOF
[Unit]
Description=MedicalBook Telegram Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_USER
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/bin
ExecStart=$INSTALL_DIR/venv/bin/python bot.py
Restart=always
RestartSec=10

# Ресурсы
CPUQuota=200%
MemoryMax=2G
OOMScoreAdjust=-100

# Логирование
StandardOutput=append:$INSTALL_DIR/log/bot.log
StandardError=append:$INSTALL_DIR/log/bot.log

[Install]
WantedBy=multi-user.target
EOF

# Перезагружаем systemd и включаем сервис
systemctl daemon-reload
systemctl enable medicalbook-bot.service

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно! ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Директория установки: ${YELLOW}$INSTALL_DIR${NC}"
echo ""
echo -e "Управление ботом:"
echo -e "  ${GREEN}sudo systemctl start medicalbook-bot${NC}   - Запустить бота"
echo -e "  ${GREEN}sudo systemctl stop medicalbook-bot${NC}    - Остановить бота"
echo -e "  ${GREEN}sudo systemctl restart medicalbook-bot${NC} - Перезапустить бота"
echo -e "  ${GREEN}sudo systemctl status medicalbook-bot${NC}  - Статус бота"
echo ""
echo -e "Просмотр логов:"
echo -e "  ${GREEN}sudo journalctl -u medicalbook-bot -f${NC}  - Логи в реальном времени"
echo -e "  ${GREEN}tail -f $INSTALL_DIR/log/bot.log${NC}  - Файл логов"
echo ""
echo -e "${YELLOW}Запустите бота командой:${NC}"
echo -e "  sudo systemctl start medicalbook-bot"
echo ""
