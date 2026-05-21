# AbandonBoard

**Export your agendas before BoardDocs crashes or you cancel your contract.**

BoardDocs is the kind of product that makes you miss a filing cabinet: slow UI, undocumented APIs, hyperlinks that die when you leave, and no sensible bulk export when your district finally pulls the plug. AbandonBoard scrapes your site for meeting agendas and attachments, and packs them into PDFs that still work when `go.boarddocs.com` is just a 404 with a Diligent logo.

Exports BoardDocs meeting agendas and attachments as nested PDFs for both **public** and **logged-in (private)** access. Now you can finally cancel that useless BoardDocs subscription.

## Output layout

```
output/
  pa-phoe/
    Public/
      Board of School Directors/
        2026-05-18-Agenda.pdf
      Curriculum Committee/
        2026-05-18-Agenda.pdf
    Private/
      Board of School Directors/
        2026-05-18-Agenda.pdf
```

Each `YYYY-MM-DD-Agenda.pdf` contains:

1. The detailed printed agenda (from `PRINT-AgendaDetailed`)
2. PDF attachments appended in order (each has a PDF bookmark / outline entry)
3. Non-PDF attachments embedded in the PDF portfolio
4. **BoardDocs hyperlinks rewritten** — links in the agenda that pointed at `go.boarddocs.com` (file downloads, `goto?open&id=…`, etc.) are converted to internal jumps to the matching attachment bookmark, so the archive works after BoardDocs is cancelled.

## Setup

```powershell
cd path\to\AbandonBoard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Install Chromium (required).** BoardDocs already runs a browser tab farm in your district office; this script just needs one Chromium for Playwright—agenda HTML → PDF (default on Windows) and optional private login. Run once after `pip install`:

```powershell
playwright install chromium
```

If the venv is active, that command uses the Playwright from your project. If it is not found, use:

```powershell
.\.venv\Scripts\playwright install chromium
```

## Configuration

Copy the example config and edit it for your district:

```powershell
copy config.example.json config.json
```

`config.json` is gitignored so you can store your **username** there without committing it. Login credentials are prompted when private export runs. Command-line flags always override the config file.

If `config.json` exists in the current directory, it is loaded automatically. Use another path with `--config path\to\settings.json`.

| Key | CLI flag | Default | Description |
|-----|----------|---------|-------------|
| `site` | `--site` | `pa/phoe` | BoardDocs path (e.g. `pa/phoe`) |
| `public_url` | `--public-url` | `https://go.boarddocs.com/pa/phoe/Board.nsf/Public` | Public landing page URL |
| `output` | `--output` | `output` | Export directory |
| `since` | `--since` | `null` | Earliest meeting date (`YYYYMMDD` or `YYYY-MM-DD`) |
| `until` | `--until` | `null` | Latest meeting date (`YYYYMMDD` or `YYYY-MM-DD`) |
| `limit` | `--limit` | `null` | Max meetings per committee (newest first; no limit when omitted) |
| `committee_ids` | `--committee-id` | `null` | List of committee IDs to export (repeatable on CLI) |
| `committees` | — | Phoenixville map in `config.example.json` | Name → ID map; IDs are used when `committee_ids` is omitted |
| `public_only` | `--public-only` | `false` | Skip private export |
| `private_only` | `--private-only` | `false` | Skip public export |
| `login_url` | `--login-url` | `https://go.boarddocs.com/pa/phoe/Board.nsf` | BoardDocs login URL (required for private export unless `cookies_file` is set) |
| `username` | `--username` | `null` | BoardDocs username (login prompted for private export) |
| `cookies_file` | `--cookies-file` | `null` | Browser cookies JSON instead of login |
| `headed_login` | `--headed-login` | `false` | Show browser during login |
| `pdf_engine` | `--pdf-engine` | `auto` | Agenda HTML → PDF: `auto`, `story`, or `playwright` |
| `request_delay` | `--request-delay` | `0.25` | Seconds between API calls (`0` disables) |
| `verbose` | `-v` | `false` | Debug logging |
| `survey_content` | `--survey-content` | `false` | Content discovery mode (writes JSON under `output/discovery/`) |

Example run with config only:

```powershell
python export_boarddocs.py
```

Override one setting:

```powershell
python export_boarddocs.py --limit 2 -v
```

## Tests

Unit tests cover parsing, URL/link remapping, committee merging, and minimal PDF assembly. (They were created with AI):

```powershell
pip install -r requirements-dev.txt
pytest
```

Verbose: `pytest -v`

## Usage

### Public export (Phoenixville default)

```powershell
python export_boarddocs.py --limit 2 -v
```

If you see `AssertionError` from PyMuPDF when saving agenda PDFs, ensure Chromium is installed (see **Setup** above), then use:

```powershell
python export_boarddocs.py --pdf-engine playwright --limit 2 -v
```

### Date range

```powershell
python export_boarddocs.py --since 2025-01-01 --until 2026-12-31
```

### Single committee

```powershell
python export_boarddocs.py --committee-id A8EFZW419B9D --limit 5
```

Committees that only appear after login are discovered from the authenticated **Private** view (use `--private-only` or combined public+private export with credentials). You can pass the committee ID even if it is not listed on the public page.

Committee IDs for Phoenixville (`pa/phoe`):

| Committee | ID |
|-----------|-----|
| Board of School Directors | `A8EFZW419B9D` |
| Board Meeting Minutes | `CWWP6G53BCB7` |
| Buildings and Grounds Committee | `CTNND25F5CC0` |
| Curriculum Committee | `CTNNFJ5FAEF1` |
| Finance / Personnel Committee | `CTNNDP5F7630` |
| Policy Committee | `CTNNDT5F7A3B` |

### Discover Public / Administrative / Executive content

Run a logged-in survey (no PDF export) to see how BoardDocs exposes each content section and which file APIs return attachments:

```powershell
python export_boarddocs.py --survey-content --committee-id CVDJPU4E320B --username YOUR_USER --login-url "https://go.boarddocs.com/pa/phoe/Board.nsf" --limit 1 -v
```

Writes `output/discovery/content-survey-{district}-{committee}-{id}.json` with:

- Category names and per-section item counts
- Sample endpoint probes (`BD-GetFiles`, `BD-GetPublicFiles`, etc.)
- Print-agenda file link counts

Private export now merges results from both `BD-GetFiles` and `BD-GetPublicFiles` (when each returns HTTP 200) and tags skipped items with their content section.

### Private export (login)

```powershell
python export_boarddocs.py --private-only --username YOUR_USER --login-url "https://go.boarddocs.com/pa/phoe/Board.nsf/Private?open&login"
```

You can also pass the shorter `Board.nsf` URL; the exporter resolves it to the private login page automatically (one of the few things that *does* redirect sensibly):

```powershell
python export_boarddocs.py --private-only --username YOUR_USER --login-url "https://go.boarddocs.com/pa/phoe/Board.nsf"
```

Or reuse browser cookies:

```powershell
python export_boarddocs.py --private-only --cookies-file cookies.json
```

### Both public and private

```powershell
python export_boarddocs.py --username YOUR_USER
```

## Options

Settings can also live in `config.json` (see **Configuration**). CLI flags win.

| Flag | Description |
|------|-------------|
| `--config` | JSON settings file (default `./config.json` when present) |
| `--site` | BoardDocs path, default `pa/phoe` |
| `--public-url` | Public page URL |
| `--output` | Output directory (default `output`) |
| `--since` / `--until` | Date filters |
| `--limit` | Max meetings per committee (newest first) |
| `--public-only` / `--private-only` | Scope |
| `--pdf-engine` | `auto`, `story`, or `playwright` (agenda HTML → PDF) |
| `--request-delay` | Seconds between API calls (default `0.25`; use `0` to disable) |
| `-v` | Verbose logging |

## Notes

- **Chromium** must be installed via `playwright install chromium` before the first export; without it, agenda PDF generation and private login will fail.
- Uses BoardDocs undocumented POST endpoints (`BD-GetMeetingsList`, `BD-GetAgenda`, `BD-GetPublicFiles`, `PRINT-AgendaDetailed`). Not affiliated with Diligent/BoardDocs.
- Pauses between API requests by default (`--request-delay 0.25`); increase if rate-limited, or pass `0` to disable.
- Skips meetings whose output PDF already exists (safe to re-run).
- **Attachments**: if an agenda item shows a file icon but BoardDocs returns no downloadable files (e.g. schedule placeholders), that item is skipped with a warning and the meeting export continues. Any file that is found must download successfully or the meeting is not written.
- Links to BoardDocs URLs in the agenda are remapped after the PDF is assembled; the log line `remapped N BoardDocs link(s)` shows how many were updated. Non-PDF attachments (embedded only) may not have a page target for links.
- Private documents may require district credentials. Logged-in agendas may include **Public Content**, **Administrative Content**, and **Executive Content** sections; use `--survey-content` to see which APIs serve each section on your site.
- Per-item fetch merges `BD-GetFiles` and `BD-GetPublicFiles` when both respond; print-agenda HTML remains the main source for weekly-packet style meetings.

## Why AbandonBoard?

Because “sunsetting BoardDocs” is vendor-speak for “your links rot.” This tool exists so school boards keep readable, searchable, offline archives of public business—without paying Diligent to hold your own minutes hostage.
