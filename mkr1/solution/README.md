# Photo Tagger

Локальна vision-модель (Ollama) описує фото українською та ставить теги. Потім фото можна шукати текстом («собака пляж»). Все працює офлайн і безкоштовно.

## Встановлення

1. Встанови Ollama: https://ollama.com/download
2. Завантаж модель:
   ```bash
   ollama pull gemma3:4b
   ```
3. Python 3.9+ та залежності:
   ```bash
   cd solution
   pip install -r requirements.txt
   ```

## Запуск

Запускати з папки `solution/` (так логи потрапляють у `../evidence/`).

```bash
python photo_gui.py     # те саме у вікні
python photo_tagger.py describe ~/Pictures/trip          # описати фото
python photo_tagger.py search "собака пляж"              # пошук
python photo_tagger.py stats                             # статистика для звіту
```

Результат лежить у `index.json`, лог кожного прогону в `../evidence/runs.csv`. Вже оброблені фото пропускаються (за хешем файлу), тож можна запускати повторно.