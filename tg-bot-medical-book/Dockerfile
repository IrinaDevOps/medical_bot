FROM python:3.12.12-alpine3.23

WORKDIR /app

# Копируем весь проект
COPY . . 

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt


CMD ["python", "bot.py"]
