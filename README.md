# Audio Transcriber Skill

## Описание

Скилл для транскрибации аудиофайлов **любой длины** и **YouTube-видео** с автоматическим обходом лимита ASR API (30 секунд).

### Что нового в v3.0
- **Supadata API** для мгновенного получения YouTube-субтитров (без скачивания видео!)
- Автоматический fallback на yt-dlp + ASR если субтитров нет
- Таймстемпы в транскрипте
- Автоопределение названия видео

## Что делает

1. **YouTube:** Получает субтитры через Supadata API (мгновенно, ~2 сек)
2. **YouTube fallback:** Если нет субтитров — скачивает через yt-dlp, режет на чанки, транскрибирует через ASR
3. **Локальные файлы:** Проверяет реальную длину, конвертирует в WAV 16kHz, режет на чанки по 29 сек, транскрибирует
4. Склеивает результат, убирая дубликаты на стыках
5. Опционально переводит через LLM

## Структура

```
audio-transcriber/
├── SKILL.md                          ← Описание скилла (для OpenClaw)
├── README.md                         ← Этот файл
└── scripts/
    └── audio_transcriber.py          ← Основной скрипт
```

## Установка в OpenClaw

### Вариант 1: Скопировать в папку скиллов

```bash
cp -r audio-transcriber/ ~/.openclaw/skills/
```

### Вариант 2: Через репозиторий

```
/install-skill https://github.com/KindFarmAI/audio-transcriber
```

## Использование

### Через скрипт напрямую:

```bash
# YouTube-видео (через Supadata API)
SUPADATA_API_KEY=sd_xxx python3 scripts/audio_transcriber.py \
  --input "https://youtube.com/watch?v=XXXXX"

# Локальный файл
python3 scripts/audio_transcriber.py --input "file.mp3"

# С переводом
python3 scripts/audio_transcriber.py --input "file.mp3" --translate "ru"

# Без таймстемпов
python3 scripts/audio_transcriber.py --input "https://youtube.com/watch?v=X" --no-timestamps

# Указать язык субтитров
python3 scripts/audio_transcriber.py --input "https://youtube.com/watch?v=X" --lang en
```

### Через OpenClaw (в чате):

```
Транскрибируй это видео: https://youtube.com/watch?v=XXXXX
Распознай речь в podcast.mp3 и переведи на русский
Что говорится в этом аудио? interview.wav
```

## Зависимости

- **ffmpeg** — конвертация и нарезка аудио
- **z-ai CLI** (z-ai-web-dev-sdk) — распознавание речи
- **yt-dlp** — скачивание YouTube (только для fallback)
- **Supadata API ключ** — для YouTube субтитров (100 бесплатно/мес)

## Установка зависимостей

```bash
# Ubuntu/Debian
sudo apt install ffmpeg python3
pip install yt-dlp

# macOS
brew install ffmpeg python3
pip install yt-dlp
```

## Supadata API

Регистрация: https://dash.supadata.ai (через GitHub)

Free-план: 100 запросов/мес (1 транскрипт = 1 кредит)

```bash
# Задать ключ через переменную окружения
export SUPADATA_API_KEY=sd_xxxxxxxxxxxx

# Или указать перед командой
SUPADATA_API_KEY=sd_xxx python3 scripts/audio_transcriber.py --input "URL"
```

## Ограничения

- ASR API лимит: 30 секунд на запрос (скилл обходит через нарезку)
- Supadata free: 100 видео/мес
- Поддерживаемые форматы: MP3, WAV, M4A, OGG, FLAC, WebM
- Качество транскрипции зависит от чёткости речи и уровня шума
- Инструментальные фрагменты (без речи) пропускаются автоматически
- YouTube может блокировать yt-dlp с cloud-серверов (Supadata решает эту проблему)
