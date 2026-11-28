import argparse
import csv
import hashlib
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import ollama
from PIL import Image, ImageOps

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MODEL = "gemma3:4b"
INDEX_FILE = Path("index.json")
RUNS_LOG = Path("../evidence/runs.csv")
MAX_SIDE = 1024

PROMPT = """Ти допомагаєш робити пошук по особистому фотоархіву.
Подивись на фото і поверни ТІЛЬКИ JSON такого вигляду:
{
  "description": "1-2 речення українською: що на фото",
  "tags": ["5-8 коротких тегів українською, іменники в називному відмінку"],
  "category": "одне з: люди, тварини, природа, їжа, місто, документ, скріншот, транспорт, інше",
  "has_text": true або false
}
Описуй лише те, що реально видно. Нічого не вигадуй."""

def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {}

def save_index(index: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def prepare_image(path: Path) -> bytes:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

def describe_image(path: Path) -> dict:
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT, "images": [prepare_image(path)]}],
        format="json",
        options={"temperature": 0.2},
    )
    data = json.loads(response["message"]["content"])
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    return {
        "description": str(data.get("description", "")).strip(),
        "tags": [str(t).strip().lower() for t in tags if str(t).strip()],
        "category": str(data.get("category", "інше")).strip().lower(),
        "has_text": bool(data.get("has_text", False)),
    }

def log_run(name: str, seconds: float, ok: bool) -> None:
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not RUNS_LOG.exists()
    with open(RUNS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "file", "seconds", "ok", "model"])
        w.writerow(
            [datetime.now().isoformat(timespec="seconds"), name, f"{seconds:.1f}", ok, MODEL]
        )

def cmd_describe(args) -> None:
    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"Папку не знайдено: {folder}")
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTS)
    if not files:
        sys.exit("У папці немає підтримуваних зображень (jpg, png, webp, bmp).")
    index = load_index()
    done = failed = skipped = 0
    t_all = time.time()
    for i, path in enumerate(files, 1):
        key = file_hash(path)
        if key in index and not args.force:
            skipped += 1
            continue
        t0 = time.time()
        try:
            info = describe_image(path)
            info["path"] = str(path)
            index[key] = info
            save_index(index)
            log_run(path.name, time.time() - t0, True)
            done += 1
            print(f"[{i}/{len(files)}] {path.name}: {info['description']}")
            print(f"           теги: {', '.join(info['tags'])}")
        except Exception as e:
            failed += 1
            log_run(path.name, time.time() - t0, False)
            print(f"[{i}/{len(files)}] {path.name}: ПОМИЛКА ({e})")
    print(
        f"\nГотово за {time.time() - t_all:.0f} с: "
        f"нових {done}, пропущено {skipped}, помилок {failed}."
    )

def stem(word: str) -> str:
    return word[:5]

def cmd_search(args) -> None:
    index = load_index()
    if not index:
        sys.exit("Індекс порожній. Спочатку запусти: describe <папка>")
    query = {stem(w): w for w in args.query.lower().split()}
    results = []
    for info in index.values():
        text = " ".join(
            [info["description"], " ".join(info["tags"]), info["category"]]
        ).lower()
        words = {stem(w) for w in text.replace(",", " ").replace(".", " ").split()}
        matched = [w for s, w in query.items() if s in words]
        if matched and (not args.all or len(matched) == len(query)):
            results.append((len(matched), matched, info))
    results.sort(key=lambda x: -x[0])
    if not results:
        print("Нічого не знайдено.")
        return
    print(f"Знайдено фото: {len(results)}\n")
    for score, matched, info in results[: args.top]:
        print(f"{info['path']}")
        print(f"   збіги: {', '.join(matched)} ({score} з {len(query)})")
        print(f"   {info['description']}")

def cmd_stats(_args) -> None:
    index = load_index()
    print(f"Фото в індексі: {len(index)}")
    if RUNS_LOG.exists():
        with open(RUNS_LOG, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        ok = [float(r["seconds"]) for r in rows if r["ok"] == "True"]
        bad = len(rows) - len(ok)
        if ok:
            print(f"Успішних прогонів: {len(ok)}, помилок: {bad}")
            print(f"Середній час на фото: {sum(ok) / len(ok):.1f} с")
            print(f"Загальний час: {sum(ok) / 60:.1f} хв")
    cats: dict = {}
    for info in index.values():
        cats[info["category"]] = cats.get(info["category"], 0) + 1
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")

def main() -> None:
    p = argparse.ArgumentParser(description="Опис і теги для фото через Ollama")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("describe", help="описати фото з папки")
    d.add_argument("folder")
    d.add_argument("--force", action="store_true", help="переописати вже оброблені")
    d.set_defaults(func=cmd_describe)
    s = sub.add_parser("search", help="пошук фото за текстом")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--all", action="store_true", help="потрібні всі слова запиту")
    s.set_defaults(func=cmd_search)
    st = sub.add_parser("stats", help="статистика для звіту")
    st.set_defaults(func=cmd_stats)
    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()