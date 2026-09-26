# Example reports (synthetic data)

These PDFs were produced by the real CLI against `tests/fake_wikimedia.py`, **not real Wikipedia
traffic**, to show the layout. The development sandbox had no network access to Wikimedia.

| File | Command |
|---|---|
| `fasting-pl-cs-uk.pdf` | `analyze --topic "intermittent fasting" --langs pl,cs --lang uk`, then `report ... --summary ... --recommendation ...` |
| `learning-english-audiences-uk.pdf` | `analyze --basket "English language" "English as a second or foreign language" name="Вивчення англійської" --langs de,pl,uk,es,tr,fr --lang uk`, then `report` |
| `astronomy-uk-en.pdf` | `analyze --topic Astronomy --langs uk --pdf` |
