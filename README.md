# 🏛️ Sobranie Bot

Automated crawler and parser for Macedonian Parliament stenographic notes.

## Features

- 🕷️ Crawls the Parliament website for finished sessions
- 📥 Downloads stenographic notes (PDF/DOC)
- 📄 Parses PDFs into structured JSONL format
- 🤖 Runs automatically every Friday via GitHub Actions

## Automated Updates

This repository is automatically updated every **Friday at 18:00 UTC** via GitHub Actions.

[![Weekly Parliament Scraper](https://github.com/ditoelrey/sobranie-stenografi/tree/master/data)

## Manual Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run once
python main.py --once

# Run with verbose logging
python main.py --once --verbose
```

## Data Structure

- `data/raw/` - Downloaded PDF files
- `data/processed/` - Parsed JSONL files
- `data/history.json` - Processing history

## JSONL Output Format

```json
{"speaker": "Име Презиме", "raw_text": "Говорот на пратеникот...", "source_page": 1}
```
