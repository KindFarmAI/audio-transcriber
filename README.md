# Audio Transcriber Skill

## Описание

Скилл для транскрибации аудиофайлов **любой длины** с автоматическим обходом лимита ASR API (30 секунд).

## Что делает

1. Проверяет **реальную** длину аудио (не метаданные!)
2. Конвертирует любой формат в WAV 16kHz моно
3. Нарезает на чанки по 29 секунд
4. Транскрибирует каждый чанк через ASR
5. Склеивает результат, убирая дубликаты на стыках
6. Опционально переводит через LLM

## Формат файлов

```
audio-transcriber/
├── SKILL.md                          ← Описание скилла (для OpenClaw)
└── scripts/
    └── audio_transcriber.py          ← Основной скрипт
```

## Установка в OpenClaw

### Вариант 1: Скопировать в папку скиллов

1. Скопируй всю папку `audio-transcriber` в директорию скиллов OpenClaw:
   ```
   cp -r audio-transcriber/ ~/.openclaw/skills/
   ```

2. Перезапусти OpenClaw (или обнови список скиллов).

### Вариант 2: Через репозиторий

1. Залей папку на GitHub
2. В OpenClaw добавь репозиторий скиллов:
   ```
   /install-skill https://github.com/KindFarmAI/audio-transcriber
   ```

## Использование

### Через скрипт напрямую:

```bash
# Базовая транскрипция
python3 scripts/audio_transcriber.py --input "file.mp3"

# Транскрипция с переводом
python3 scripts/audio_transcriber.py --input "file.mp3" --translate "ru"

# Сохранить результат в файл
python3 scripts/audio_transcriber.py --input "file.mp3" --output "transcript.txt"

# Другой размер чанка
python3 scripts/audio_transcriber.py --input "file.mp3" --chunk-size 25
```

### Через OpenClaw (в чате):

```
Транскрибируй этот файл: /path/to/audio.mp3
Распознай речь в podcast.mp3 и переведи на русский
Что говорится в этом аудио? interview.wav
```

## Зависимости

- **ffmpeg** — конвертация и нарезка аудио
- **z-ai CLI** (z-ai-web-dev-sdk) — распознавание речи
- Python 3.8+

## Установка зависимостей

```bash
# Ubuntu/Debian
sudo apt install ffmpeg python3

# macOS
brew install ffmpeg python3

# z-ai CLI уже установлен с OpenClaw
```

## Ограничения

- ASR API лимит: 30 секунд на запрос (скилл обходит через нарезку)
- Поддерживаемые форматы: MP3, WAV, M4A, OGG, FLAC, WebM и другие (через ffmpeg)
- Качество транскрипции зависит от чёткости речи и уровня шума
- Инструментальные фрагменты (без речи) пропускаются автоматически

## Пример вывода

```
## Транскрипция: Era - Ameno.mp3

**Длительность:** 4:14
**Формат:** MP3
**Перевод на:** RU

### Текст:

Dorime interimo ad apare dorime, ameno ameno lanciremo dorime...

---
### Перевод:

Дориме, проведи меня сквозь тьму...
```
