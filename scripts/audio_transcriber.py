#!/usr/bin/env python3
"""
audio_transcriber.py — Транскрибация аудиофайлов и YouTube-видео.

Поддерживает три режима работы:
  1. Локальные аудиофайлы — через ASR (нарезка на чанки по 29 сек)
  2. YouTube-видео с субтитрами — через Supadata API (быстро, бесплатно)
  3. YouTube-видео без субтитров — через yt-dlp + ASR (если API не даёт результат)

Использование:
    python3 audio_transcriber.py --input "file.mp3"
    python3 audio_transcriber.py --input "https://youtube.com/watch?v=XXXXX"
    python3 audio_transcriber.py --input "song.mp3" --translate "ru"

Требования:
    - ffmpeg (установлен в системе)
    - z-ai CLI (z-ai-web-dev-sdk) — для локальных файлов
    - yt-dlp (для YouTube без субтитров, опционально)
    - Supadata API ключ (для YouTube субтитров, опционально)

Переменные окружения:
    SUPADATA_API_KEY — API ключ для supadata.ai

Автор: KindFarmAI / Zai Chat
Лицензия: MIT
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
from pathlib import Path


# ============================================================
# Supadata API — YouTube транскрипты через прокси
# ============================================================

SUPADATA_API_KEY = os.environ.get("SUPADATA_API_KEY", "")


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


def get_supadata_transcript(video_id: str, lang: str = None) -> dict:
    """Получить транскрипт YouTube-видео через Supadata API.

    Returns:
        dict с ключами: lang, available_langs, content (list of {text, offset, duration})
        или None если не удалось
    """
    if not SUPADATA_API_KEY:
        return None

    url = f"https://api.supadata.ai/v1/youtube/transcript?id={video_id}"
    if lang:
        url += f"&lang={lang}"

    headers = {
        'x-api-key': SUPADATA_API_KEY,
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Origin': 'https://supadata.ai',
        'Referer': 'https://supadata.ai/',
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))

        if result.get('content') and len(result['content']) > 0:
            return result
        return None
    except Exception as e:
        print(f"  [Supadata] Не удалось получить транскрипт: {e}", file=sys.stderr)
        return None


def format_supadata_transcript(data: dict) -> str:
    """Преобразовать результат Supadata в текст с таймстемпами."""
    lines = []
    for seg in data.get('content', []):
        offset_ms = seg.get('offset', 0)
        offset_s = offset_ms / 1000
        minutes = int(offset_s // 60)
        seconds = int(offset_s % 60)
        timestamp = f"[{minutes:02d}:{seconds:02d}]"
        text = seg.get('text', '').strip()
        lines.append(f"{timestamp} {text}")
    return "\n".join(lines)


# ============================================================
# YouTube detection
# ============================================================

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
# YouTube download (yt-dlp) — fallback если Supadata не сработал
# ============================================================

def download_youtube_audio(url: str, output_path: str) -> dict:
    """Скачать аудио с YouTube через yt-dlp.

    Returns:
        dict с ключами: title, duration_str, filepath
    """
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        local_ytdlp = os.path.expanduser("~/.local/bin/yt-dlp")
        if os.path.exists(local_ytdlp):
            ytdlp = local_ytdlp
        else:
            print("[ОШИБКА] yt-dlp не найден. Установите: pip install yt-dlp", file=sys.stderr)
            sys.exit(1)

    print(f"Скачиваю аудио с YouTube...", end=" ", flush=True)

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
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Транскрибация аудиофайлов и YouTube-видео",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 audio_transcriber.py --input "song.mp3"
  python3 audio_transcriber.py --input "https://youtube.com/watch?v=XXXXX"
  python3 audio_transcriber.py --input "podcast.mp3" --translate "ru"
  python3 audio_transcriber.py --input "interview.wav" --output "transcript.txt"

Переменные окружения:
  SUPADATA_API_KEY    API ключ для supadata.ai (YouTube субтитры через прокси)
        """
    )

    parser.add_argument("--input", "-i", required=True, help="Путь к аудиофайлу или YouTube-ссылка")
    parser.add_argument("--output", "-o", default=None, help="Путь к файлу с результатом")
    parser.add_argument("--translate", "-t", default=None, help="Перевести на язык (например: ru, en, de)")
    parser.add_argument("--lang", "-l", default=None, help="Язык YouTube-субтитров (например: ru, en)")
    parser.add_argument("--chunk-size", "-c", type=int, default=29, help="Размер чанка в секундах (по умолчанию: 29)")
    parser.add_argument("--no-timestamps", action="store_true", help="Убрать таймстемпы из результата")

    args = parser.parse_args()
    input_path = args.input

    is_yt = is_youtube_url(input_path)

    # =============================================
    # YouTube путь — сначала пробуем Supadata API
    # =============================================
    if is_yt:
        video_id = extract_youtube_id(input_path)
        print(f"Источник: YouTube (ID: {video_id})")

        if SUPADATA_API_KEY:
            print("Пробую получить субтитры через Supadata API...", end=" ", flush=True)
            transcript_data = get_supadata_transcript(video_id, lang=args.lang)

            if transcript_data:
                lang = transcript_data.get('lang', '?')
                segments = transcript_data.get('content', [])
                print(f"OK ({lang}, {len(segments)} сегментов)")

                last_offset = segments[-1].get('offset', 0) + segments[-1].get('duration', 0)
                duration_s = last_offset / 1000
                minutes = int(duration_s // 60)
                seconds = int(duration_s % 60)

                if args.no_timestamps:
                    text = " ".join(seg.get('text', '').strip() for seg in segments)
                else:
                    text = format_supadata_transcript(transcript_data)

                raw_json_path = os.path.join(tempfile.gettempdir(), f"yt_transcript_{video_id}.json")
                with open(raw_json_path, 'w', encoding='utf-8') as f:
                    json.dump(transcript_data, f, indent=2, ensure_ascii=False)

                # Получаем название видео через noembed
                title = "YouTube Video"
                try:
                    noembed_url = f"https://noembed.com/embed?url={input_path}"
                    req = urllib.request.Request(noembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                    resp = urllib.request.urlopen(req, timeout=10)
                    noembed_data = json.loads(resp.read().decode('utf-8'))
                    title = noembed_data.get('title', title)
                except Exception:
                    pass

                result_parts = [
                    f"## Транскрипция: {title}",
                    f"",
                    f"**Источник:** YouTube",
                    f"**Video ID:** {video_id}",
                    f"**Длительность:** {minutes}:{seconds:02d}",
                    f"**Язык субтитров:** {lang}",
                    f"**Сегментов:** {len(segments)}",
                    f"**URL:** {input_path}",
                    f"**Метод:** Supadata API",
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

            else:
                print("субтитров нет или не удалось получить")

        # Fallback: скачиваем через yt-dlp и транскрибируем через ASR
        print("Использую yt-dlp + ASR (fallback)...")

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
