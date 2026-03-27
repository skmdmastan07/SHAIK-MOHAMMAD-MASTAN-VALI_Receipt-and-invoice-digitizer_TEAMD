from googletrans import Translator
import json

translator = Translator()

with open("static/i18n/en.json", "r", encoding="utf-8") as f:
    base = json.load(f)

languages = {
    "hi": "hi",
    "te": "te",
    "ml": "ml",
    "kn": "kn",
    "ta": "ta",
    "ur": "ur"
}

for lang in languages:
    translated = {}
    for k, v in base.items():
        translated[k] = translator.translate(v, dest=lang).text

    with open(f"static/i18n/{lang}.json", "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

