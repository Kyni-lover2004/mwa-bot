# MWA METHOD bot

Telegram-бот бесплатного 3-дневного знакомства с методом MWA: описание бота и кнопка
«Начать» → WELCOME → проверка подписки на канал → DAY 1 / MIND → через 24 часа DAY 2 / BODY →
через 24 часа DAY 3 / ENERGY и сразу финал с кнопками программы, заявки и канала. ТЗ - в [mwa_bot_tz.md](mwa_bot_tz.md).

Стек: Python 3.12, aiogram 3, SQLAlchemy (SQLite), pydantic-settings.

## Локальный запуск

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env    # вписать BOT_TOKEN
.venv/bin/python -m mwa_bot
```

Локально бот забирает апдейты сам (polling). Чтобы не ждать сутки между днями,
поставьте в `.env` `DAY_INTERVAL_MINUTES=2`.

Один токен - один запущенный бот. Локальный запуск снимает webhook, и бот на Render
перестанет получать сообщения до своего перезапуска. Для разработки удобнее отдельный
тестовый бот от @BotFather.

Тесты и линтер:

```bash
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## Настройки (.env или переменные окружения)

| Переменная | По умолчанию | Что это |
|---|---|---|
| `BOT_TOKEN` | - | токен от @BotFather, обязателен |
| `CHANNEL_ID` | пусто | канал для проверки подписки (`@mwamethod`); бот должен быть его администратором. Пусто - проверка выключена |
| `CHANNEL_URL` | `https://t.me/mwamethod` | канал: кнопки «ПОДПИСАТЬСЯ НА MWA» и «TELEGRAM-КАНАЛ MWA» |
| `PROGRAM_URL` | `https://mwamethod.com` | кнопка финала «ОТКРЫТЬ ПРОГРАММУ MWA» |
| `APPLY_URL` | `https://mwamethod.com/#participation` | кнопка финала «ОФОРМИТЬ УЧАСТИЕ» (заявка / оплата) |
| `DAY_INTERVAL_MINUTES` | `1440` | пауза между днями |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/mwa_bot.db` | база данных |
| `WEBHOOK_BASE_URL` | пусто | публичный адрес для режима webhook; на Render берётся из `RENDER_EXTERNAL_URL` |
| `PORT` | `8080` | порт HTTP-сервера в режиме webhook |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Деплой на Render (демо, бесплатный тариф)

1. Dashboard → New → Blueprint → выбрать этот репозиторий. Render прочитает `render.yaml`.
2. Вписать `BOT_TOKEN`, когда Render его спросит.
3. После деплоя бот сам поставит webhook на адрес сервиса и обновит описание бота.

Ограничения бесплатного тарифа, важные для этого бота:

- Сервис засыпает через 15 минут без входящих запросов. Сообщение пользователя будит его
  примерно за минуту, но пока бот спит, планировщик стоит и дни не уходят. Поэтому в
  `render.yaml` для демо стоит интервал 2 минуты.
- Файловая система стирается при каждом деплое, перезапуске и засыпании, вместе с базой
  SQLite: прогресс пользователей теряется.

Для настоящих пользователей нужен платный Background Worker с постоянным диском под
`data/` (или внешний Postgres) и интервал 1440 минут.

## Контент

Тексты, картинка WELCOME и видео дней лежат в [content/](content/), правила - в
[content/README.md](content/README.md). Бот проверяет контент при старте и не запустится,
если Telegram что-то не примет.

## Устройство

- `mwa_bot/__main__.py` - точка входа: polling локально, webhook на хостинге
- `mwa_bot/handlers/` - `/start` и кнопки онбординга
- `mwa_bot/flow.py` - доставка этапов: какой следующий и когда
- `mwa_bot/scheduler.py` - фоновая рассылка DAY 2, DAY 3 и финала по расписанию
- `mwa_bot/content/` - загрузка и проверка контента, отправка с кешем file_id
- `mwa_bot/db/` - модели и операции с базой
- `mwa_bot/webhook.py` - HTTP-сервер для webhook и `/health`
