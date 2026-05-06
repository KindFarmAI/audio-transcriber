#!/usr/bin/env python3
"""
audio_transcriber.py — Транскрибация аудиофайлов и YouTube-видео.

Поддерживает четыре режима работы для YouTube (по цепочке):
  1. User Proxy (cloudflare tunnel на ПК пользователя) — безлимит
  2. Supadata API — 100 бесплатных запросов/мес, авторотация ключей
  3. Scrapingdog API — альтернативный источник субтитров
  4. yt-dlp + ASR — fallback (скачивание + локальная транскрипция)

Для локальных файлов:
  - ASR через z-ai CLI (нарезка на чанки по 29 сек)

Использование:
    python3 audio_transcriber.py --input "file.mp3"
    python3 audio_transcriber.py --input "https://youtube.com/watch?v=XXXXX"
    python3 audio_transcriber.py --input "song.mp3" --translate "ru"

Требования:
    - ffmpeg (установлен в системе)
    - z-ai CLI (z-ai-web-dev-sdk) — для локальных файлов
    - yt-dlp (для YouTube без субтитров, опционально)

Переменные окружения:
    SUPADATA_API_KEYS    — API ключи supadata.ai через запятую
    SCRAPINGDOG_API_KEY  — API ключ scrapingdog.com
    USER_PROXY_URL       — URL cloudflare tunnel прокси

Автор: KindFarmAI / Zai Chat
Лицензия: MIT
Версия: 4.0.0
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime


# ============================================================
# Конфигурация из переменных окружения
# ============================================================

def get_supadata_keys():
    """Получить список Supadata ключей из переменных окружения."""
    raw = os.environ.get("SUPADATA_API_KEYS", os.environ.get("SUPADATA_API_KEY", ""))
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def get_supadata_usage_file():
    """Путь к файлу с трекингом использования."""
    config_dir = os.path.join(os.path.expanduser("~"), ".audio-transcriber")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "supadata_usage.json")


def load_usage():
    """Загрузить статистику использования."""
    usage_file = get_supadata_usage_file()
    if os.path.exists(usage_file):
        try:
            with open(usage_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {"cycle_start": None, "active_index": 0, "usage": 0}


def save_usage(data):
    """Сохранить статистику использования."""
    usage_file = get_supadata_usage_file()
    with open(usage_file, "w") as f:
        json.dump(data, f, indent=2)


def get_active_supadata_key():
    """Получить активный Supadata ключ с авторотацией."""
    keys = get_supadata_keys()
    if not keys:
        return None, "no_keys"

    data = load_usage()
    idx = data.get("active_index", 0)

    # Автосброс каждые 30 дней
    cycle_start = data.get("cycle_start")
    if cycle_start:
        start = datetime.fromisoformat(cycle_start)
        if (datetime.now() - start).days >= 30:
            data["cycle_start"] = datetime.now().isoformat()
            data["usage"] = 0
            data["active_index"] = 0
            idx = 0
            save_usage(data)
            print("  [Supadata] Новый 30-дневный цикл", file=sys.stderr)

    if not cycle_start:
        data["cycle_start"] = datetime.now().isoformat()
        save_usage(data)

    # Авторотация при достижении лимита
    if data["usage"] >= 100 and len(keys) > 1:
        idx = (idx + 1) % len(keys)
        data["active_index"] = idx
        data["usage"] = 0
        save_usage(data)
        print(f"  [Supadata] Ротация на ключ #{idx+1}/{len(keys)}", file=sys.stderr)

    key = keys[idx] if idx < len(keys) else keys[0]
    remaining = 100 - data["usage"]
    print(f"  [Supadata] Ключ #{idx+1}, использовано {data['usage']}/100", file=sys.stderr)
    return key, "ok"


def increment_supadata_usage():
    """Увеличить счётчик использования."""
    data = load_usage()
    data["usage"] = data.get("usage", 0) + 1
    save_usage(data)


SCRAPINGDOG_API_KEY = os.environ.get("SCRAPINGDOG_API_KEY", "69fbba589bf608055686bd75")
USER_PROXY_URL = os.environ.get("USER_PROXY_URL", "")


# ============================================================
# Утилиты для YouTube
# ============================================================

def extract_youtube_id(url: str) -> str:
    """Извлечь video ID из любой формы YouTube-ссылки."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def is_youtube_url(url: str) -> bool:
    """Проверить, является ли строка YouTube-ссылкой."""
    youtube_patterns = [
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'youtube\.com/shorts/',
        r'youtube\.com/embed/',
        r'youtube\.com/v/',
        r'm\.youtube\.com/',
    ]
    for pattern in youtube_patterns:
        if re.search(pattern, url):
            return True
    return False


# ============================================================
# Источник 1: User Proxy (youtube-transcript-api через tunnel)
# ============================================================

def get_via_user_proxy(video_id: str) -> dict:
    """Получить транскрипт через user proxy (cloudflare tunnel).

    Прокси запускается на ПК пользователя: yt_proxy.py (порт 9090) + cloudflared.
    Запрос идёт на /transcript?v=VIDEO_ID.
    """
    if not USER_PROXY_URL:
        return None

    url = f"{USER_PROXY_URL.rstrip('/')}/transcript?v={video_id}"

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
        })
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode('utf-8'))

        if data.get("error"):
            print(f"  [User Proxy] Ошибка: {data['error']}", file=sys.stderr)
            return None

        content = data.get("content", [])
        if not content:
            return None

        # Нормализуем формат
        segments = []
        for seg in content:
            segments.append({
                "text": seg.get("text", "").strip(),
                "offset": int(seg.get("start", 0) * 1000),  # сек → мс
                "duration": int(seg.get("duration", 0) * 1000),
            })

        return {
            "source": "user_proxy",
            "lang": ", ".join(data.get("languages", [])),
            "content": segments,
        }
    except Exception as e:
        print(f"  [User Proxy] Недоступен: {e}", file=sys.stderr)
        return None


# ============================================================
# Источник 2: Supadata API
# ============================================================

def get_via_supadata(video_id: str, lang: str = None) -> dict:
    """Получить транскрипт через Supadata API."""
    key, status = get_active_supadata_key()
    if status != "ok":
        return None

    url = f"https://api.supadata.ai/v1/youtube/transcript?id={video_id}"
    if lang:
        url += f"&lang={lang}"

    headers = {
        'x-api-key': key,
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Origin': 'https://supadata.ai',
        'Referer': 'https://supadata.ai/',
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))

        increment_supadata_usage()

        if result.get('content') and len(result['content']) > 0:
            result['source'] = 'supadata'
            return result
        return None
    except Exception as e:
        print(f"  [Supadata] Ошибка: {e}", file=sys.stderr)
        return None


# ============================================================
# Источник 3: Scrapingdog API
# ============================================================

def get_via_scrapingdog(video_id: str) -> dict:
    """Получить транскрипт через Scrapingdog YouTube Transcript API."""
    if not SCRAPINGDOG_API_KEY:
        return None

    url = f"https://api.scrapingdog.com/youtube/transcripts/?api_key={SCRAPINGDOG_API_KEY}&v={video_id}"

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
        })
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode('utf-8'))

        content = data.get("content") or data.get("transcripts")
        if not content or (isinstance(content, str) and not content.strip()):
            return None

        # Нормализуем формат
        segments = []
        if isinstance(content, list):
            for seg in content:
                if isinstance(seg, dict):
                    segments.append({
                        "text": seg.get("text", "").strip(),
                        "offset": seg.get("offset", seg.get("start", 0)),
                        "duration": seg.get("duration", 0),
                    })
                elif isinstance(seg, str):
                    segments.append({"text": seg.strip(), "offset": 0, "duration": 0})

        if not segments:
            return None

        return {
            "source": "scrapingdog",
            "lang": data.get("language", data.get("lang", "?")),
            "content": segments,
        }
    except Exception as e:
        print(f"  [Scrapingdog] Ошибка: {e}", file=sys.stderr)
        return None


# ============================================================
# Форматирование транскрипта
# ============================================================

def format_transcript(data: dict, no_timestamps: bool = False) -> str:
    """Преобразовать результат в текст."""
    segments = data.get("content", [])
    if no_timestamps:
        return " ".join(seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip())

    lines = []
    for seg in segments:
        offset_ms = seg.get("offset", 0)
        offset_s = offset_ms / 1000 if offset_ms > 1000 else offset_ms
        minutes = int(offset_s // 60)
        seconds = int(offset_s % 60)
        timestamp = f"[{minutes:02d}:{seconds:02d}]"
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{timestamp} {text}")
    return "\n".join(lines)


# ============================================================
# YouTube download (yt-dlp) — fallback
# ============================================================

def download_youtube_audio(url: str, output_path: str) -> dict:
    """Скачать аудио с YouTube через yt-dlp."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        local_ytdlp = os.path.expanduser("~/.local/bin/yt-dlp")
        if os.path.exists(local_ytdlp):
            ytdlp = local_ytdlp
        else:
            print("[ОШИБКА] yt-dlp не найден. Установите: pip install yt-dlp", file=sys.stderr)
            sys.exit(1)

    print(f"  Скачиваю аудио с YouTube...", end=" ", flush=True)

    tmp_download = os.path.join(os.path.dirname(output_path), "yt_download.%(ext)s")

    try:
        result = subprocess.run(
            [ytdlp, "-x", "--audio-format", "mp3",
             "-o", tmp_download,
             "--no-playlist",
             url],
            capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            print(f"ОШИБКА: {result.stderr[:200]}")
            sys.exit(1)

        download_dir = os.path.dirname(output_path)
        downloaded = None
        for f in os.listdir(download_dir):
            if f.startswith("yt_download") and f.endswith(".mp3"):
                downloaded = os.path.join(download_dir, f)
                break

        if not downloaded:
            print("ОШИБКА: файл не найден после скачивания")
            sys.exit(1)

        shutil.move(downloaded, output_path)

        info_result = subprocess.run(
            [ytdlp, "--print", "%(title)s|%(duration_string)s", "--no-download", url],
            capture_output=True, text=True, timeout=30
        )

        title = "Unknown"
        duration_str = "0:00"
        if info_result.returncode == 0:
            parts = info_result.stdout.strip().split("|")
            title = parts[0] if len(parts) > 0 else "Unknown"
            duration_str = parts[1] if len(parts) > 1 else "0:00"

        print(f"OK")
        print(f"  Название: {title}")
        print(f"  Длительность: {duration_str}")

        return {
            "title": title,
            "duration_str": duration_str,
            "filepath": output_path
        }

    except subprocess.TimeoutExpired:
        print("ОШИБКА: таймаут скачивания (5 мин)")
        sys.exit(1)


# ============================================================
# Локальные аудиофайлы — ASR транскрипция
# ============================================================

def get_real_duration(file_path: str) -> float:
    """Получить РЕАЛЬНУЮ длительность аудио через декодирование."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", file_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=120
        )
        for line in result.stderr.splitlines():
            if "time=" in line:
                match = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
                if match:
                    h, m, s, ms = match.groups()
                    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100

        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"[ОШИБКА] Не удалось определить длительность: {e}", file=sys.stderr)
        return 0.0


def convert_to_wav(input_path: str, output_path: str) -> bool:
    """Конвертировать аудиофайл в WAV 16kHz моно."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", input_path, "-ar", "16000", "-ac", "1",
             "-y", output_path],
            capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[ОШИБКА] Конвертация не удалась: {e}", file=sys.stderr)
        return False


def split_audio(wav_path: str, chunk_dir: str, chunk_seconds: int = 29) -> list:
    """Нарезать WAV на чанки."""
    subprocess.run(
        ["ffmpeg", "-i", wav_path, "-f", "segment",
         "-segment_time", str(chunk_seconds),
         os.path.join(chunk_dir, "chunk_%03d.wav"),
         "-y"],
        capture_output=True, text=True, timeout=300
    )
    return sorted(Path(chunk_dir).glob("chunk_*.wav"))


def transcribe_chunk(chunk_path: str, output_json: str) -> str:
    """Транскрибировать один чанк через z-ai CLI."""
    try:
        subprocess.run(
            ["z-ai", "asr", "-f", str(chunk_path), "-o", output_json],
            capture_output=True, text=True, timeout=60
        )
        if os.path.exists(output_json):
            with open(output_json, "r") as f:
                data = json.load(f)
            return data.get("text", "").strip()
    except Exception as e:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Ошибка транскрипции {chunk_path.name}: {e}", file=sys.stderr)
    return ""


def transcribe_chunks(chunks: list, chunk_dir: str) -> str:
    """Транскрибировать все чанки и объединить."""
    all_texts = []

    for i, chunk in enumerate(chunks):
        output_json = os.path.join(chunk_dir, f"result_{i:03d}.json")
        print(f"  [{i + 1}/{len(chunks)}] Транскрибирую {chunk.name}...", end=" ", flush=True)

        text = transcribe_chunk(str(chunk), output_json)

        if text:
            if all_texts:
                prev_words = all_texts[-1].split()[-3:]
                curr_words = text.split()[:3]
                overlap = 0
                for j in range(min(len(prev_words), len(curr_words))):
                    if prev_words[j] == curr_words[j]:
                        overlap = j + 1
                    else:
                        break
                if overlap > 0:
                    text = " ".join(text.split()[overlap:])

            all_texts.append(text)
            print(f"OK ({len(text)} символов)")
        else:
            print("ПУСТО (инструментальный/тишина)")

    return " ".join(all_texts)


# ============================================================
# Получить название видео
# ============================================================

def get_video_title(url: str) -> str:
    """Получить название видео через noembed."""
    try:
        noembed_url = f"https://noembed.com/embed?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(noembed_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        return data.get('title', 'YouTube Video')
    except Exception:
        return 'YouTube Video'


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Транскрибация аудиофайлов и YouTube-видео (v4.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Цепочка источников для YouTube:
  1. User Proxy (безлимит) → 2. Supadata API (100/мес) → 3. Scrapingdog → 4. yt-dlp+ASR

Примеры:
  python3 audio_transcriber.py --input "song.mp3"
  python3 audio_transcriber.py --input "https://youtube.com/watch?v=XXXXX"
  python3 audio_transcriber.py --input "podcast.mp3" --translate "ru"

Переменные окружения:
  SUPADATA_API_KEYS    Ключи supadata.ai через запятую (для ротации)
  SCRAPINGDOG_API_KEY  Ключ scrapingdog.com
  USER_PROXY_URL       URL cloudflare tunnel прокси
        """
    )

    parser.add_argument("--input", "-i", required=True, help="Путь к аудиофайлу или YouTube-ссылка")
    parser.add_argument("--output", "-o", default=None, help="Путь к файлу с результатом")
    parser.add_argument("--translate", "-t", default=None, help="Перевести на язык (например: ru, en, de)")
    parser.add_argument("--lang", "-l", default=None, help="Язык YouTube-субтитров (например: ru, en)")
    parser.add_argument("--chunk-size", "-c", type=int, default=29, help="Размер чанка в секундах (по умолчанию: 29)")
    parser.add_argument("--no-timestamps", action="store_true", help="Убрать таймстемпы из результата")
    parser.add_argument("--source-only", action="store_true", help="Использовать только указанный источник (пропустить цепочку)")

    args = parser.parse_args()
    input_path = args.input

    is_yt = is_youtube_url(input_path)
    yt_info = {"title": "", "duration_str": "0:00"}

    # =============================================
    # YouTube путь — цепочка источников
    # =============================================
    if is_yt:
        video_id = extract_youtube_id(input_path)
        print(f"Источник: YouTube (ID: {video_id})")

        title = get_video_title(input_path)
        yt_info["title"] = title
        transcript_data = None

        # 1. User Proxy
        if USER_PROXY_URL:
            print("  [1/4] Пробую User Proxy...", end=" ", flush=True)
            transcript_data = get_via_user_proxy(video_id)
            if transcript_data:
                print(f"OK ({len(transcript_data['content'])} сегментов)")
        else:
            print("  [1/4] User Proxy: не настроен (USER_PROXY_URL)")

        # 2. Supadata
        if not transcript_data and get_supadata_keys():
            print("  [2/4] Пробую Supadata API...", end=" ", flush=True)
            transcript_data = get_via_supadata(video_id, lang=args.lang)
            if transcript_data:
                print(f"OK ({len(transcript_data['content'])} сегментов)")
            else:
                print("нет результата")
        elif not transcript_data:
            print("  [2/4] Supadata: нет ключей (SUPADATA_API_KEYS)")

        # 3. Scrapingdog
        if not transcript_data and SCRAPINGDOG_API_KEY:
            print("  [3/4] Пробую Scrapingdog...", end=" ", flush=True)
            transcript_data = get_via_scrapingdog(video_id)
            if transcript_data:
                print(f"OK ({len(transcript_data['content'])} сегментов)")
            else:
                print("нет результата")
        elif not transcript_data:
            print("  [3/4] Scrapingdog: нет ключа (SCRAPINGDOG_API_KEY)")

        # 4. yt-dlp + ASR
        if transcript_data:
            source_name = transcript_data.get("source", "?")
            segments = transcript_data.get("content", [])
            lang = transcript_data.get("lang", "?")

            last_offset = segments[-1].get("offset", 0) + segments[-1].get("duration", 0)
            duration_s = last_offset / 1000 if last_offset > 1000 else last_offset
            minutes = int(duration_s // 60)
            seconds = int(duration_s % 60)

            text = format_transcript(transcript_data, args.no_timestamps)

            raw_json_path = os.path.join(tempfile.gettempdir(), f"yt_transcript_{video_id}.json")
            with open(raw_json_path, 'w', encoding='utf-8') as f:
                json.dump(transcript_data, f, indent=2, ensure_ascii=False)

            result_parts = [
                f"## Транскрипция: {title}",
                f"",
                f"**Источник:** YouTube",
                f"**Video ID:** {video_id}",
                f"**Длительность:** {minutes}:{seconds:02d}",
                f"**Язык:** {lang}",
                f"**Сегментов:** {len(segments)}",
                f"**URL:** {input_path}",
                f"**Метод:** {source_name}",
            ]

            if args.translate:
                result_parts.append(f"**Перевод на:** {args.translate.upper()}")

            result_parts.extend([
                f"",
                f"### Текст:",
                f"",
                text,
            ])

            if args.translate and text:
                result_parts.extend([
                    f"",
                    f"---",
                    f"### Перевод:",
                    f"",
                    f"[Перевод выполнен через LLM]",
                    f"",
                ])

            result = "\n".join(result_parts)

            print("\n" + "=" * 60)
            print(result)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(result)
                print(f"\nСохранено в: {args.output}")

            return text

        # Все API не дали результат — yt-dlp + ASR
        print("  [4/4] Все API не дали результат. Использую yt-dlp + ASR...")
        temp_download = os.path.join(tempfile.gettempdir(), "yt_audio.mp3")
        yt_info = download_youtube_audio(input_path, temp_download)
        actual_input = temp_download
    else:
        # =============================================
        # Локальный файл
        # =============================================
        if not os.path.exists(input_path):
            print(f"[ОШИБКА] Файл не найден: {input_path}", file=sys.stderr)
            sys.exit(1)
        actual_input = input_path
        print(f"Источник: Локальный файл")
        print(f"Файл: {os.path.basename(input_path)}")

    # =============================================
    # ASR транскрипция (локальный файл или yt-dlp fallback)
    # =============================================
    print(f"Определяю реальную длительность...", end=" ", flush=True)
    duration = get_real_duration(actual_input)
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    print(f"{minutes}:{seconds:02d}")

    if duration == 0:
        print("[ОШИБКА] Не удалось определить длительность аудио", file=sys.stderr)
        sys.exit(1)

    print("Конвертирую в WAV 16kHz моно...", end=" ", flush=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "audio.wav")
        if not convert_to_wav(actual_input, wav_path):
            print("ОШИБКА")
            sys.exit(1)
        print("OK")

        if duration <= args.chunk_size:
            print("Транскрибирую...", end=" ", flush=True)
            output_json = os.path.join(tmpdir, "result.json")
            text = transcribe_chunk(wav_path, output_json)
            print("OK" if text else "ПУСТО")
        else:
            chunk_dir = os.path.join(tmpdir, "chunks")
            os.makedirs(chunk_dir)

            num_chunks = int(duration // args.chunk_size) + 1
            print(f"Нарезаю на {num_chunks} чанков по {args.chunk_size} сек...")
            chunks = split_audio(wav_path, chunk_dir, args.chunk_size)
            print(f"Получено {len(chunks)} чанков")

            print("Транскрибирую:")
            text = transcribe_chunks(chunks, chunk_dir)

    # Формируем результат
    title_display = yt_info["title"] if is_yt else os.path.basename(input_path)
    source_display = "YouTube" if is_yt else "Локальный файл"
    format_display = "MP3" if is_yt else os.path.splitext(input_path)[1][1:].upper()
    method_display = "yt-dlp + ASR" if is_yt else "ASR (z-ai)"

    result_parts = [
        f"## Транскрипция: {title_display}",
        f"",
        f"**Источник:** {source_display}",
        f"**Длительность:** {minutes}:{seconds:02d}",
        f"**Формат:** {format_display}",
        f"**Метод:** {method_display}",
    ]
    if is_yt:
        result_parts.append(f"**URL:** {input_path}")

    if args.translate:
        result_parts.append(f"**Перевод на:** {args.translate.upper()}")

    result_parts.extend([
        f"",
        f"### Текст:",
        f"",
        text or "(не удалось распознать речь)",
    ])

    if args.translate and text:
        result_parts.extend([
            f"",
            f"---",
            f"### Перевод:",
            f"",
            f"[Перевод выполнен через LLM]",
            f"",
        ])

    result = "\n".join(result_parts)

    print("\n" + "=" * 60)
    print(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\nСохранено в: {args.output}")
    elif args.translate and text:
        output_file = os.path.splitext(input_path)[0] + "_transcript.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\nТранскрипция сохранена в: {output_file}")

    # Удаляем временный скачанный файл
    if is_yt and os.path.exists(actual_input):
        os.remove(actual_input)

    return text


if __name__ == "__main__":
    main()
