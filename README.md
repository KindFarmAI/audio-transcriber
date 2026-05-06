# Audio Transcriber Skill

## Описание

Скилл для транскрибации аудиофайлов **любой длины** и **YouTube-видео** с автоматическим обходом лимита ASR API (30 секунд).

### Что нового в v4.0
- **User Proxy** — безлимитный источник через cloudflare tunnel на ПК пользователя
- **Scrapingdog API** — новый fallback-источник субтитров
- **Авторотация Supadata ключей** — несколько ключей через запятую, авто-ротация при 100 запросах, авто-сброс каждые 30 дней
- **Цепочка 4 источников** — user_proxy → supadata → scrapingdog → yt-dlp+ASR

### История версий
- **v4.0** — цепочка источников + авторотация ключей + Scrapingdog
- **v3.0** — Supadata API для YouTube субтитров
- **v2.0** — поддержка YouTube через yt-dlp
- **v1.0** — локальные файлы + ASR нарезка

## Цепочка источников (YouTube)

```
1. User Proxy (безлимит, через IP пользователя)
   ↳ cloudflare tunnel → yt_proxy.py → youtube-transcript-api
   ↳ Безлимит, но нужен запущенный прокси на ПК

2. Supadata API (100 бесплатных запросов/мес)
   ↳ Авторотация нескольких ключей
   ↳ Автосброс каждые 30 дней
   ↳ Быстро, работает с cloud-серверов

3. Scrapingdog API
   ↳ Альтернативный источник субтитров
   ↳ Бесплатный ключ встроен

4. yt-dlp + ASR (fallback)
   ↳ Скачивание видео + локальная транскрипция
   ↳ Работает всегда, но медленнее
```

## Структура

```
audio-transcriber/
├── SKILL.md                          ← Описание скилла (для OpenClaw/AutoClaw)
├── README.md                         ← Этот файл
└── scripts/
    └── audio_transcriber.py          ← Основной скрипт (v4.0)
```

## Установка в AutoClaw

### Вариант 1: Скопировать в папку скиллов

```bash
cp -r audio-transcriber/ ~/.autoclaw/skills/
# или
cp -r audio-transcriber/ ~/.openclaw/skills/
```

### Вариант 2: Через репозиторий

```
/install-skill https://github.com/KindFarmAI/audio-transcriber
```

## Использование

### Через скрипт напрямую:

```bash
# YouTube-видео (авто-цепочка источников)
python3 scripts/audio_transcriber.py --input "https://youtube.com/watch?v=XXXXX"

# С несколькими Supadata ключами (авторотация)
SUPADATA_API_KEYS="sd_key1,sd_key2,sd_key3" \
  python3 scripts/audio_transcriber.py --input "URL"

# С user proxy (безлимит)
USER_PROXY_URL="https://xxx.trycloudflare.com" \
  python3 scripts/audio_transcriber.py --input "URL"

# Локальный файл
python3 scripts/audio_transcriber.py --input "file.mp3"

# С переводом
python3 scripts/audio_transcriber.py --input "file.mp3" --translate "ru"

# Без таймстемпов
python3 scripts/audio_transcriber.py --input "URL" --no-timestamps
```

### Через AutoClaw (в чате):

```
Транскрибируй это видео: https://youtube.com/watch?v=XXXXX
Распознай речь в podcast.mp3 и переведи на русский
Что говорится в этом аудио? interview.wav
```

## Зависимости

| Зависимость | Для чего | Обязательна |
|------------|----------|-------------|
| **ffmpeg** | Конвертация и нарезка аудио | Да (для локальных файлов) |
| **z-ai CLI** | Распознавание речи | Да (для локальных файлов) |
| **yt-dlp** | Скачивание YouTube | Нет (только fallback) |
| **python 3.8+** | Запуск скрипта | Да |

## Переменные окружения

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `SUPADATA_API_KEYS` | Ключи supadata.ai через запятую | Пусто |
| `SCRAPINGDOG_API_KEY` | Ключ scrapingdog.com | Встроенный |
| `USER_PROXY_URL` | URL cloudflare tunnel прокси | Пусто |

## API Источники

### Supadata.ai
- Регистрация: https://dash.supadata.ai (через GitHub)
- Free-план: 100 запросов/мес
- Несколько ключей — авторотация
- Автосброс каждые 30 дней

### Scrapingdog
- Сайт: https://scrapingdog.com
- YouTube Transcript API

### User Proxy (самодельный)
- Запуск на ПК: `python yt_proxy.py`
- Автоматически поднимает HTTP-сервер (порт 9090) + cloudflared tunnel
- Даёт безлимитный доступ к YouTube субтитрам через IP пользователя

## Ограничения

- ASR API лимит: 30 секунд на запрос (скилл обходит через нарезку)
- Supadata free: 100 видео/мес (решается добавлением нескольких ключей)
- User Proxy: временный URL, нужен перезапуск при каждом сеансе
- Поддерживаемые форматы: MP3, WAV, M4A, OGG, FLAC, WebM
- Качество транскрипции зависит от чёткости речи и уровня шума
