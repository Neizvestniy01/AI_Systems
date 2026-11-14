import argparse
import difflib
import re
import sys
import time
from openai import APIConnectionError, APITimeoutError, NotFoundError, OpenAI

DEFAULT_MODEL = "qwen3-corrector"  # qwen3:1.7b (Q4_K_M) з контекстом 2048, див. Modelfile

SYSTEM = (
    "Ти коректор української мови. Користувач надсилає речення. "
    "Перевір кожне слово окремо й виправ усі орфографічні та граматичні помилки: опечатки, "
    "неправильні літери, неповні закінчення, відмінки, узгодження, пунктуацію. "
    "Не змінюй стиль, тон, порядок слів і правильні слова; не переписуй речення. "
    "Якщо помилок немає, поверни речення без змін. "
    "Відповідай лише виправленим реченням, без пояснень і лапок."
)
EXAMPLES = [
    ("Ми купили чотири хлібів.", "Ми купили чотири хліби."),
    ("Прошу ви надіслати мені документи.", "Прошу вас надіслати мені документи."),
    ("Вона вчора прийшла дадому пізно.", "Вона вчора прийшла додому пізно."),
    ("Ця книга була написан у 1990 році.", "Ця книга була написана у 1990 році."),
    ("Мені подобається цей фільм, він дуже цікавий.", "Мені подобається цей фільм, він дуже цікавий."),
]

def build_messages(text):
    messages = [{"role": "system", "content": SYSTEM}]
    for wrong, right in EXAMPLES:
        messages += [{"role": "user", "content": wrong}, {"role": "assistant", "content": right}]
    return messages + [{"role": "user", "content": text}]

def clean(answer):
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
    return answer.strip("«»\"'").strip()

def changes(original, corrected):
    a, b = original.split(), corrected.split()
    result = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        old, new = " ".join(a[i1:i2]) or "∅", " ".join(b[j1:j2]) or "∅"
        if old.strip(".,!?;:…") == new.strip(".,!?;:…"):
            new += "   (лише розділовий знак)"
        result.append((old, new))
    return result

def correct(client, args, text, on_token=lambda piece: None):
    start, first, answer = time.perf_counter(), None, ""
    stream = client.chat.completions.create(
        model=args.model, messages=build_messages(text), stream=True,
        temperature=args.temperature, max_tokens=args.max_tokens, seed=1,
        extra_body={"reasoning_effort": "none"},
    )
    for chunk in stream:
        piece = chunk.choices[0].delta.content if chunk.choices else None
        if piece:
            if first is None:
                first = time.perf_counter()
            answer += piece
            on_token(piece)
    return clean(answer), (first or start) - start, time.perf_counter() - start

def check_sentence(client, args, text):
    print("Перевіряю", end="", flush=True)
    corrected, ttft, total = None, 0, 0
    try:
        first_piece = []
        def on_token(piece):
            if not first_piece:
                first_piece.append(1)
                print("\r→ ", end="", flush=True)
            print(piece, end="", flush=True)
        corrected, ttft, total = correct(client, args, text, on_token)
        print()
    except APIConnectionError:
        sys.exit("\nСервер недоступний. Запустіть Ollama (`ollama serve`) і перевірте --base-url.")
    except APITimeoutError:
        sys.exit(f"\nТаймаут {args.timeout:.0f} с. Збільште --timeout або оберіть меншу модель.")
    except NotFoundError:
        hint = ("ollama pull qwen3:1.7b && ollama create qwen3-corrector -f Modelfile"
                if args.model == DEFAULT_MODEL else f"ollama pull {args.model}")
        sys.exit(f"\nМодель «{args.model}» не знайдено. Створіть її: {hint}")
    except Exception as error:
        sys.exit(f"\nПомилка запиту: {error}")
    if not corrected:
        print("Модель повернула порожню відповідь. Спробуйте ще раз або збільште --max-tokens.")
        return
    ratio = difflib.SequenceMatcher(None, text, corrected).ratio()
    if "\n" in corrected or len(corrected) > 3 * len(text) + 20 or ratio < 0.6:
        print("Відповідь схожа на переписане речення або пояснення, а не виправлення. Перевірте результат.")
    diff = changes(text, corrected)
    if not diff:
        print("Помилок не знайдено.")
    else:
        print("Зміни:")
        for old, new in diff:
            print(f"  {old}  →  {new}")
    print(f"({ttft:.1f} с до першого слова, {total:.1f} с загалом)\n")

def main():
    p = argparse.ArgumentParser(description="Перевірка правопису й граматики українських речень.")
    p.add_argument("text", nargs="?", help="речення для перевірки (без аргументу — інтерактивний режим)")
    p.add_argument("--file", help="файл із реченнями, по одному на рядок")
    p.add_argument("--base-url", default="http://localhost:11434/v1")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--temperature", type=float, default=0.0)  # коректура детермінована, творчість не потрібна
    p.add_argument("--max-tokens", type=int, default=256)     # речення + запас; обриває зациклення за ≈16 с
    p.add_argument("--timeout", type=float, default=60)
    args = p.parse_args()
    client = OpenAI(base_url=args.base_url, api_key="local", timeout=args.timeout)
    if args.file:
        try:
            lines = [l.strip() for l in open(args.file, encoding="utf-8") if l.strip()]
        except OSError as error:
            sys.exit(f"Не вдалося відкрити файл: {error}")
        for line in lines:
            print(f"Речення: {line}")
            check_sentence(client, args, line)
    elif args.text:
        check_sentence(client, args, args.text)
    else:
        print("Введіть речення (порожній рядок або Ctrl+C — вихід).")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            check_sentence(client, args, line)

if __name__ == "__main__":
    main()