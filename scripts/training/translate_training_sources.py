from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import generate_localized_training_pdfs as pdfgen


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "docs" / "training"
TMP_DIR = ROOT / "tmp" / "pdfs"
CACHE_PATH = TMP_DIR / "training_translation_cache.json"

LANGS = {
    "uz": {
        "tl": "uz",
        "folder": "uz",
        "header_left": "Milana ERP o'quv qo'llanmasi",
        "combined_title": "Milana ERP o'quv to'plami",
        "combined_subtitle": "Bo'lim qo'llanmalari va Super Admin uchun to'liq ma'lumot",
        "combined_filename": "Milana_ERP_Oquv_Toplami_Barcha_Bolimlar.pdf",
        "cover_source": "Manba: docs/training/uz",
        "page_label": "Sahifa",
    },
    "ru": {
        "tl": "ru",
        "folder": "ru",
        "header_left": "Учебное руководство Milana ERP",
        "combined_title": "Учебный пакет Milana ERP",
        "combined_subtitle": "Руководства отделов и полная инструкция Super Admin",
        "combined_filename": "Milana_ERP_Uchebnyy_Paket_Vse_Otdely.pdf",
        "cover_source": "Источник: docs/training/ru",
        "page_label": "Страница",
    },
}

POST_REPLACEMENTS = {
    "uz": {
        "Tomoshabinlar": "Auditoriya",
        "supervayzerlar": "supervisorlar",
        "murabbiylar": "trenerlar",
        "mashq qilishlari mumkin": "o'qishi mumkin",
        "Jarayonning toʻliq koʻrinishi": "To'liq jarayon sharhi",
        "Jarayonning to'liq ko'rinishi": "To'liq jarayon sharhi",
        "Sotish": "Sotuv",
        "Mato va aksessuarlarni saqlash": "Mato va furnitura ombori",
        "Mato va aksessuarlar saqlash": "Mato va furnitura ombori",
        "Kesish": "Bichish",
        "kesish": "bichish",
        "Chop etilmoqda": "Pechat",
        "chop etilmoqda": "pechat",
        "Tayyor mahsulot xotirasi": "Tayyor mahsulot ombori",
        "Tayyor mahsulot saqlash": "Tayyor mahsulot ombori",
        "Chiqindilar boʻlimi": "Chiqindi bo'limi",
        "Chiqindilar bo'limi": "Chiqindi bo'limi",
        "Menejment / Admin": "Rahbariyat / Admin",
        "Menejment/Admin": "Rahbariyat / Admin",
        "Boshqaruv / Admin": "Rahbariyat / Admin",
        "To'liq kirish qo'llanma": "To'liq huquqli qo'llanma",
        "Super admin haqida toʻliq maʼlumot": "Super Admin to'liq ma'lumot",
        "Super administrator": "Super Admin",
        "Super Administrator": "Super Admin",
        "Ma'lumotlar konsoli": "Data Console",
        "Maʼlumotlar konsoli": "Data Console",
        "MCP kirish": "MCP Access",
    },
    "ru": {
        "Библиотека обучения отдела": "Учебная библиотека по отделам",
        "Руководства отдела": "Руководства отделов",
        "Покупки": "Закупки",
        "Хранилище тканей и аксессуаров": "Склад ткани и фурнитуры",
        "Хранение тканей и аксессуаров": "Склад ткани и фурнитуры",
        "Резание": "Раскрой",
        "Шитье": "Швейный отдел",
        "Хранилище готовой продукции": "Склад готовой продукции",
        "ГотовоХранение": "Склад готовой продукции",
        "Отдел мусора": "Отдел отходов",
        "Управление/Администратор": "Руководство / Админ",
        "Управление/Админ": "Руководство / Админ",
        "Полная информация о суперадминистраторе": "Super Admin: полная инструкция",
        "суперадминистратор": "Super Admin",
        "Суперадминистратор": "Super Admin",
        "Консоль данных": "Data Console",
        "MCP Доступ": "MCP Access",
    },
}


def load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, str]) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


CACHE = load_cache()
DELIMITER = "\nQQQSEGMENTSEPQQQ\n"


def should_translate(text: str) -> bool:
    return bool(re.search(r"[A-Za-zА-Яа-я]", text)) and not re.fullmatch(r"[\W_0-9]+", text)


def protect_tokens(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def add(value: str) -> str:
        key = f"QQQCODE{len(replacements)}QQQ"
        replacements[key] = value
        return key

    text = re.sub(r"`[^`]+`", lambda match: add(match.group(0)), text)
    text = re.sub(r"(?<=\]\()[^)]+(?=\))", lambda match: add(match.group(0)), text)
    text = re.sub(r"https?://\S+", lambda match: add(match.group(0)), text)

    def protect_upper_token(match: re.Match[str]) -> str:
        value = match.group(0)
        if re.fullmatch(r"QQQCODE\d+QQQ", value):
            return value
        return add(value)

    text = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", protect_upper_token, text)
    return text, replacements


def restore_tokens(text: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def translate_text(text: str, target_lang: str) -> str:
    return translate_many([text], target_lang)[0]


def call_translate_raw(protected: str, target_lang: str) -> str:
    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&dt=t&tl="
        + urllib.parse.quote(target_lang)
        + "&q="
        + urllib.parse.quote(protected)
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return "".join(part[0] for part in payload[0] if part and part[0])
        except Exception as exc:  # noqa: BLE001 - retry network translation failures.
            last_error = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Translation failed for {target_lang}: {protected[:80]}") from last_error


def translate_many(texts: list[str], target_lang: str) -> list[str]:
    results: list[str | None] = [None] * len(texts)
    pending: list[tuple[int, str, dict[str, str], str]] = []

    for idx, text in enumerate(texts):
        if not text.strip() or not should_translate(text):
            results[idx] = text
            continue
        protected, replacements = protect_tokens(text)
        cache_key = f"v2:en:{target_lang}:{protected}"
        if cache_key in CACHE:
            results[idx] = restore_tokens(CACHE[cache_key], replacements)
        else:
            pending.append((idx, protected, replacements, cache_key))

    batch: list[tuple[int, str, dict[str, str], str]] = []
    batch_chars = 0

    def flush_batch() -> None:
        nonlocal batch, batch_chars
        if not batch:
            return
        joined = DELIMITER.join(item[1] for item in batch)
        translated_joined = call_translate_raw(joined, target_lang)
        translated_parts = translated_joined.split(DELIMITER)
        if len(translated_parts) != len(batch):
            translated_parts = [call_translate_raw(item[1], target_lang) for item in batch]
        for (idx, protected, replacements, cache_key), translated in zip(batch, translated_parts, strict=True):
            CACHE[cache_key] = translated
            results[idx] = restore_tokens(translated, replacements)
        if len(CACHE) % 50 < len(batch):
            save_cache(CACHE)
        batch = []
        batch_chars = 0

    for item in pending:
        item_size = len(item[1]) + len(DELIMITER)
        if batch and (len(batch) >= 25 or batch_chars + item_size > 4500):
            flush_batch()
        batch.append(item)
        batch_chars += item_size
    flush_batch()

    return [result if result is not None else text for result, text in zip(results, texts, strict=True)]


def translate_text_legacy(text: str, target_lang: str) -> str:
    if not text.strip() or not should_translate(text):
        return text
    protected, replacements = protect_tokens(text)
    cache_key = f"v2:en:{target_lang}:{protected}"
    if cache_key in CACHE:
        return restore_tokens(CACHE[cache_key], replacements)

    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&dt=t&tl="
        + urllib.parse.quote(target_lang)
        + "&q="
        + urllib.parse.quote(protected)
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(part[0] for part in payload[0] if part and part[0])
            CACHE[cache_key] = translated
            if len(CACHE) % 50 == 0:
                save_cache(CACHE)
            return restore_tokens(translated, replacements)
        except Exception as exc:  # noqa: BLE001 - retry network translation failures.
            last_error = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Translation failed for {target_lang}: {text[:80]}") from last_error


def translate_table_line(line: str, target_lang: str) -> str:
    leading = "|" if line.lstrip().startswith("|") else ""
    trailing = "|" if line.rstrip().endswith("|") else ""
    cells = line.strip().strip("|").split("|")
    translated = [translate_text(cell.strip(), target_lang) for cell in cells]
    return f"{leading} " + " | ".join(translated) + f" {trailing}"


def translate_line(line: str, target_lang: str, in_code: bool) -> tuple[str, bool]:
    stripped = line.strip()
    if stripped.startswith("```"):
        return line, not in_code
    if in_code or not stripped:
        return line, in_code
    if stripped.startswith("|") and re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
        return line, in_code
    if stripped.startswith("|"):
        return translate_table_line(line, target_lang), in_code

    patterns = [
        r"^(\s*#{1,6}\s+)(.*)$",
        r"^(\s*[-*]\s+)(.*)$",
        r"^(\s*\d+\.\s+)(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            return match.group(1) + translate_text(match.group(2), target_lang), in_code

    return translate_text(line, target_lang), in_code


def translate_markdown(markdown: str, target_lang: str) -> str:
    placeholders: list[object] = []
    segments: list[str] = []
    in_code = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            placeholders.append(line)
            in_code = not in_code
            continue
        if in_code or not stripped:
            placeholders.append(line)
            continue
        if stripped.startswith("|") and re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
            placeholders.append(line)
            continue
        if stripped.startswith("|"):
            leading = "|" if line.lstrip().startswith("|") else ""
            trailing = "|" if line.rstrip().endswith("|") else ""
            cells = line.strip().strip("|").split("|")
            segment_ids = []
            for cell in cells:
                segment_ids.append(len(segments))
                segments.append(cell.strip())
            placeholders.append(("table", leading, trailing, segment_ids))
            continue

        matched = False
        for pattern in [r"^(\s*#{1,6}\s+)(.*)$", r"^(\s*[-*]\s+)(.*)$", r"^(\s*\d+\.\s+)(.*)$"]:
            match = re.match(pattern, line)
            if match:
                placeholders.append(("prefixed", match.group(1), len(segments)))
                segments.append(match.group(2))
                matched = True
                break
        if matched:
            continue
        placeholders.append(("plain", len(segments)))
        segments.append(line)

    translated_segments = translate_many(segments, target_lang)
    output: list[str] = []
    for item in placeholders:
        if isinstance(item, str):
            output.append(item)
        elif item[0] == "prefixed":
            _, prefix, segment_id = item
            output.append(prefix + translated_segments[segment_id])
        elif item[0] == "plain":
            _, segment_id = item
            output.append(translated_segments[segment_id])
        elif item[0] == "table":
            _, leading, trailing, segment_ids = item
            output.append(f"{leading} " + " | ".join(translated_segments[idx] for idx in segment_ids) + f" {trailing}")
    return "\n".join(output).strip() + "\n"


def apply_post_replacements(markdown: str, lang: str) -> str:
    for source, replacement in POST_REPLACEMENTS.get(lang, {}).items():
        markdown = markdown.replace(source, replacement)
    return markdown


def translate_sources() -> None:
    for lang, cfg in LANGS.items():
        target_dir = SOURCE_DIR / cfg["folder"]
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in pdfgen.DOC_ORDER:
            source = SOURCE_DIR / name
            translated = translate_markdown(source.read_text(encoding="utf-8"), cfg["tl"])
            translated = apply_post_replacements(translated, lang)
            (target_dir / name).write_text(translated, encoding="utf-8")
            print(f"translated {lang}/{name}", flush=True)
    save_cache(CACHE)


def build_pdfs() -> None:
    for lang, cfg in LANGS.items():
        source_dir = SOURCE_DIR / cfg["folder"]
        output_dir = pdfgen.OUTPUT_ROOT / cfg["folder"]
        output_dir.mkdir(parents=True, exist_ok=True)
        sources = [source_dir / name for name in pdfgen.DOC_ORDER]
        for source in sources:
            pdfgen.build_pdf(
                source,
                output_dir / source.with_suffix(".pdf").name,
                cfg["header_left"],
                cfg.get("page_label", "Page"),
            )
        pdfgen.build_combined(sources, output_dir / cfg["combined_filename"], cfg)
        for pdf in sorted(output_dir.glob("*.pdf")):
            print(f"{lang}/{pdf.name}: {pdfgen.count_pages(pdf)} pages")


def main() -> None:
    translate_sources()
    build_pdfs()


if __name__ == "__main__":
    main()
