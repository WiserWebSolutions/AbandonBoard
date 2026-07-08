# AGENTS.md

## Searching exported agendas

`output/index.jsonl` is a JSON Lines search index over every exported agenda PDF
under `output/`. It exists so an assistant (or a person) can find something
without opening PDFs, which are large (many 50-100MB+, some 4GB+ total).

Each line is one meeting:

```json
{"path": "pa-phoe/Public/Board of School Directors/2024-01-08-Agenda.pdf",
 "district": "pa-phoe", "visibility": "Public", "committee": "Board of School Directors",
 "date": "2024-01-08", "page_count": 46,
 "agenda_text": "...text of the agenda summary pages only...",
 "attachments": [{"title": "08_14_23_Personnel_Report.pdf", "page": 10}, ...]}
```

**Before grepping or opening PDFs under `output/` to find something, search
`output/index.jsonl` first** (its `agenda_text` and `attachments[].title`
fields) to locate the matching meeting, then open only that one PDF at the
matching `page` — not the whole file, and not other candidate PDFs.

`agenda_text` only covers the agenda summary pages (before the first
attachment bookmark), not attachment contents, so a hit there means "this
meeting's agenda mentions it," while an `attachments` hit points at a specific
attachment and page.

If `output/index.jsonl` is missing or looks stale relative to the PDFs on
disk, regenerate it (no BoardDocs credentials or network access needed):

```
python export_boarddocs.py --build-index --output output
```
