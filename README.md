# Telegram VPN Bot

Бот для Telegram с функциями управления VPN через Outline API и интеграцией с платёжной системой ЮKassa.

## Особенности
- Управление VPN-ключами через Outline API
- Интеграция с ЮKassa для обработки платежей
- MongoDB для хранения пользователей, подписок и ключей доступа
- Административная панель через интерфейс Telegram
- Гибкие тарифные планы с различными периодами и ценами

## Требования
- Python 3.11 или выше
- MongoDB
- Outline VPN Server
- Доступ к API Telegram Bot
- Аккаунт ЮKassa

## Инструкция по установке

### 1. Подготовка сервера

```bash
# Установка необходимых пакетов
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Настройка окружения

Скопируйте файл `.env.example` в `.env` и заполните необходимые переменные:

```bash
cp .env.example .env
nano .env
```

Необходимые переменные:
- `BOT_TOKEN` - токен Telegram бота
- `YUKASSA_SHOP_ID` - ID магазина в ЮKassa
- `YUKASSA_SECRET_KEY` - секретный ключ ЮKassa
- `ADMIN_IDS` - ID администраторов (через запятую)
- `MONGODB_URI` - URI подключения к MongoDB
- `OUTLINE_API_URL` - URL API Outline VPN сервера

### 3. Установка зависимостей

Создайте файл requirements.txt со следующим содержимым:

```
aiohttp==3.9.5
python-telegram-bot==20.8
pymongo==4.6.1
python-dotenv==1.0.1
yookassa==3.2.1
email-validator==2.1.1
flask==3.0.3
gunicorn==22.0.0
flask-sqlalchemy==3.1.1
psycopg2-binary==2.9.9
telegram==0.0.1
```

И установите зависимости:

```bash
pip install -r requirements.txt
```

### 4. Настройка Systemd для запуска бота

Создайте файл сервиса для Telegram бота:

```bash
sudo nano /etc/systemd/system/telegram-vpn-bot.service
```

Содержимое файла:

```
[Unit]
Description=Telegram VPN Bot
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/bot
ExecStart=/path/to/bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Настройка Nginx для Flask API

Создайте файл конфигурации:

```bash
sudo nano /etc/nginx/sites-available/vpn-bot-api
```

Содержимое файла:

```
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Активируйте конфигурацию:

```bash
sudo ln -s /etc/nginx/sites-available/vpn-bot-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 6. Настройка веб-хука ЮKassa

В личном кабинете ЮKassa настройте URL для уведомлений:
`https://yourdomain.com/webhook/payment`

### 7. Запуск служб

```bash
# Запуск Flask API
sudo systemctl enable telegram-vpn-bot-api.service
sudo systemctl start telegram-vpn-bot-api.service

# Запуск Telegram Bot
sudo systemctl enable telegram-vpn-bot.service
sudo systemctl start telegram-vpn-bot.service
```

### 8. Проверка статуса

```bash
sudo systemctl status telegram-vpn-bot.service
sudo systemctl status telegram-vpn-bot-api.service
```

### 9. Просмотр логов

```bash
sudo journalctl -u telegram-vpn-bot.service -f
sudo journalctl -u telegram-vpn-bot-api.service -f
```

## Файл конфигурации для Flask API

Создайте файл сервиса для Flask API:

```bash
sudo nano /etc/systemd/system/telegram-vpn-bot-api.service
```

Содержимое файла:

```
[Unit]
Description=Telegram VPN Bot API
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/bot
ExecStart=/path/to/bot/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 2 app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Тестирование ЮKassa

Для тестирования платежной системы используйте данные из тестового аккаунта ЮKassa.