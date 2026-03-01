# Скрипт очистки проекта перед архивированием / сбросом
# Запуск: .\cleanup.ps1

Write-Host "========================================" -ForegroundColor Green
Write-Host "  Очистка проекта" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

Write-Host "[1/6] Удаление кэша Python (__pycache__)..." -ForegroundColor Yellow
Get-ChildItem -Path . -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Directory -Recurse -Filter ".pytest_cache" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "       Готово" -ForegroundColor Green

Write-Host "[2/6] Удаление виртуального окружения (.venv)..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Remove-Item -Recurse -Force ".venv" -ErrorAction SilentlyContinue
    Write-Host "       Готово" -ForegroundColor Green
} else {
    Write-Host "       Не найдено" -ForegroundColor Gray
}

Write-Host "[3/6] Удаление файлов логов..." -ForegroundColor Yellow
Remove-Item -Force "*.log" -ErrorAction SilentlyContinue
if (Test-Path "logs") {
    Remove-Item -Recurse -Force "logs" -ErrorAction SilentlyContinue
}
if (Test-Path "log") {
    Remove-Item -Recurse -Force "log" -ErrorAction SilentlyContinue
}
Write-Host "       Готово" -ForegroundColor Green

Write-Host "[4/6] Очистка базы данных и отчетов..." -ForegroundColor Yellow
# SQLite
if (Test-Path "data\medical_bot.db") {
    Remove-Item -Force "data\medical_bot.db" -ErrorAction SilentlyContinue
    Write-Host "       Удалена БД: medical_bot.db" -ForegroundColor Gray
}

# Legacy JSON
$dataFiles = @("data\patients.json", "data\staff.json", "data\reminders.json")
foreach ($file in $dataFiles) {
    if (Test-Path $file) {
        Remove-Item -Force $file -ErrorAction SilentlyContinue
        Write-Host "       Удален: $file" -ForegroundColor Gray
    }
}

# Excel reports
Remove-Item -Force "patients_*.xlsx" -ErrorAction SilentlyContinue
Remove-Item -Force "Отчет_о_*.xlsx" -ErrorAction SilentlyContinue

Write-Host "       Готово" -ForegroundColor Green

Write-Host "[5/6] Удаление секретов и временных файлов (.env, temp)..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Remove-Item -Force ".env" -ErrorAction SilentlyContinue
    Write-Host "       Удален: .env" -ForegroundColor Green
}
if (Test-Path "handlers\admin.temp_snippet.py") {
    Remove-Item -Force "handlers\admin.temp_snippet.py" -ErrorAction SilentlyContinue
    Write-Host "       Удален: handlers\admin.temp_snippet.py" -ForegroundColor Green
} else {
    Write-Host "       Не найден" -ForegroundColor Gray
}

Write-Host "[6/6] Удаление временных файлов..." -ForegroundColor Yellow
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue }
if (Test-Path "*.spec") { Remove-Item -Force "*.spec" -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Очистка завершена!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
