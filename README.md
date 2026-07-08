# AbandonBoard

**Export your agendas before BoardDocs crashes or you cancel your contract.**

BoardDocs is the kind of product that makes you miss a filing cabinet: slow UI, undocumented APIs, hyperlinks that die when you leave, and no sensible bulk export when your district finally pulls the plug. AbandonBoard scrapes your site for meeting agendas and attachments, and packs them into PDFs that still work when `go.boarddocs.com` is just a 404 with a Diligent logo.

Exports BoardDocs meeting agendas and attachments as nested PDFs for both **public** and **logged-in (private)** access. Now you can finally cancel that useless BoardDocs subscription.

**New to the command line?** See [Getting started (Windows, step by step)](#getting-started-windows-step-by-step) below. If you already use PowerShell or a terminal, skip ahead to [Setup](#setup).

**Password / login?** See [Password and login (transparency)](#password-and-login-transparency) for exactly when a password is asked for and where it goes.

## Download

**Easiest (no Git):** On [GitHub](https://github.com/WiserWebSolutions/AbandonBoard), click **Code** → **Download ZIP**, extract the folder, then follow [Getting started (Windows, step by step)](#getting-started-windows-step-by-step).

After extracting, the folder may be named `AbandonBoard-main` — you can rename it to `AbandonBoard` or use that name when you `cd` into the project in PowerShell.

**With Git:**

```powershell
git clone https://github.com/WiserWebSolutions/AbandonBoard.git
cd AbandonBoard
```

## Getting started (Windows, step by step)

This section is for people who normally use File Explorer and a web browser, not a “black window” full of text. You only need to do the **one-time setup** once; after that, exporting is usually one command.

### What you need

1. **This project** — a folder on your PC that contains `export_boarddocs.py` (see [Download](#download); for example `AbandonBoard` in Downloads or Documents).
2. **Python** — free software that runs the exporter. If you are not sure you have it, install it from [python.org/downloads](https://www.python.org/downloads/). During setup, turn on **“Add python.exe to PATH”** (or “Add Python to environment variables”). That lets Windows find Python when you type `python`.

### Open PowerShell in the project folder

PowerShell is Windows’ built-in command window. You type a line, press **Enter**, and it runs.

1. Open **File Explorer** and go to your AbandonBoard folder.
2. Click the **address bar** at the top (where the path is shown), type `powershell`, and press **Enter**.

   A blue or black window opens. The first line should show a path ending in your folder name — that means commands will run in the right place.

**Tip:** You can copy commands from this page (click the copy icon on a gray box), click inside PowerShell, right-click to paste, then press **Enter**. On some PCs you use **Ctrl+V** to paste instead.

### One-time setup (copy and run each block)

Run these **in order**, waiting for each to finish before the next. The first run may take a few minutes while files download.

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

If you see an error about “running scripts is disabled,” run this once, then try Activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

```powershell
pip install -r requirements.txt
```

```powershell
playwright install chromium
```

If `playwright` is not recognized, use:

```powershell
.\.venv\Scripts\playwright install chromium
```

**What just happened?** You created a small isolated Python environment (`.venv`) and installed the tools AbandonBoard needs, including a browser engine used to turn agendas into PDFs.

### Tell the tool your district (config file)

1. In File Explorer, in the AbandonBoard folder, find `config.example.json`.
2. Copy it and rename the copy to **`config.json`** (same folder).
3. Open `config.json` with **Notepad** (right-click → Open with → Notepad).
4. Change at least:
   - **`site`** — the part of your BoardDocs URL after `go.boarddocs.com/`, e.g. `pa/phoe` for `https://go.boarddocs.com/pa/phoe/...`
   - **`public_url`** — your district’s public BoardDocs page URL (open it in the browser and copy from the address bar)
   - **`login_url`** and committee IDs if you are not using the Phoenixville example — see [Configuration](#configuration) or ask whoever set up BoardDocs for your district
5. Save and close Notepad.

You do **not** put your password in this file (a `"password"` field in JSON is ignored). For private (logged-in) export, the program will ask for your password when it runs — see [Password and login (transparency)](#password-and-login-transparency).

### Run your first export (public agendas)

Open PowerShell in the project folder again (same as above). Each time you open a **new** PowerShell window, activate the environment first:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start with a **small test** (2 meetings per committee) so you can see that it works:

```powershell
python export_boarddocs.py --limit 2
```

You will see lines scroll by — that is normal. When it finishes, open the **`output`** folder in File Explorer. Inside you should see folders for your site, then **Public**, then committee names, then PDF files named like `2026-05-18-Agenda.pdf`.

To export more (or everything), run again with a higher limit or without `--limit`:

```powershell
python export_boarddocs.py
```

Re-running is safe: meetings that already have a PDF are skipped.

### Private (login) export

If you need agendas only visible after logging into BoardDocs:

```powershell
python export_boarddocs.py --private-only --username YOUR_BOARDDOCS_USERNAME
```

Replace `YOUR_BOARDDOCS_USERNAME` with your login name, or put `"username": "..."` in `config.json`. PowerShell will ask for your **password** when it runs (nothing appears as you type — that is normal). Press **Enter** when done. That password is only used to log in to BoardDocs; see [Password and login (transparency)](#password-and-login-transparency).

### If something goes wrong

| Problem | What to try |
|--------|-------------|
| `'python' is not recognized` | Reinstall Python with **Add to PATH** checked, or try `py -m venv .venv` instead of `python -m venv .venv` |
| `Activate.ps1` blocked | Run the `Set-ExecutionPolicy` line in [One-time setup](#one-time-setup-copy-and-run-each-block) |
| Errors about Chromium or Playwright | Run `playwright install chromium` again (with `.venv` activated) |
| `AssertionError` while saving PDFs | Run: `python export_boarddocs.py --pdf-engine playwright --limit 2` |
| Empty `output` folder | Check `site` and `public_url` in `config.json`; add `-v` to see more detail: `python export_boarddocs.py --limit 2 -v` |

For more options (date ranges, one committee, cookies file, etc.), see [Usage](#usage). Technical setup details are in [Setup](#setup).

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

### Searching the archive without opening every PDF

Every export run also writes `output/index.jsonl` — one JSON line per meeting PDF:

```json
{"path": "pa-phoe/Public/Board of School Directors/2024-01-08-Agenda.pdf",
 "district": "pa-phoe", "visibility": "Public", "committee": "Board of School Directors",
 "date": "2024-01-08", "page_count": 46,
 "agenda_text": "...full text of the agenda summary pages...",
 "attachments": [{"title": "08_14_23_Personnel_Report.pdf", "page": 10}, ...]}
```

`agenda_text` covers only the agenda summary pages (before the first attachment), not the attachments themselves, so the index stays small — a few hundred meetings and hundreds of attachments compress to a handful of MB instead of gigabytes of PDFs. Search it directly instead of opening PDFs one at a time:

```powershell
findstr /i "budget" output\index.jsonl
```

Each match already tells you the file and the page number to jump to, so you (or an LLM assistant) only need to open the one relevant page range instead of scanning every PDF's full text.

Rebuild the index for PDFs already on disk, with no BoardDocs credentials or network access needed:

```powershell
python export_boarddocs.py --build-index --output output
```

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

`config.json` is gitignored so you can store your **username** there without committing it. **Passwords are never read from the config file** — they are prompted at runtime when needed (see [Password and login (transparency)](#password-and-login-transparency)). Command-line flags always override the config file.

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
| `username` | `--username` | `null` | BoardDocs username; triggers password prompt when private login runs ([details](#password-and-login-transparency)) |
| `cookies_file` | `--cookies-file` | `null` | Browser cookies JSON instead of login (no password prompt) |
| `headed_login` | `--headed-login` | `false` | Show browser during login (password still only sent to BoardDocs) |
| `pdf_engine` | `--pdf-engine` | `auto` | Agenda HTML → PDF: `auto`, `story`, or `playwright` |
| `request_delay` | `--request-delay` | `0.25` | Seconds between API calls (`0` disables) |
| `verbose` | `-v` | `false` | Debug logging |
| `survey_content` | `--survey-content` | `false` | Content discovery mode (writes JSON under `output/discovery/`) |
| `build_index` | `--build-index` | `false` | Rebuild `output/index.jsonl` from existing PDFs and exit (no network access) |

Example run with config only:

```powershell
python export_boarddocs.py
```

Override one setting:

```powershell
python export_boarddocs.py --limit 2 -v
```

## Password and login (transparency)

AbandonBoard only needs your BoardDocs **password** when it must act as a logged-in user. Public export never uses it.

### When your password is **not** used

| Situation | Password |
|-----------|----------|
| `python export_boarddocs.py` with no `username` or `cookies_file` | Not asked — exports **public** agendas only (same as `--public-only`) |
| `--public-only` (any other flags) | Not asked |
| `--cookies-file` … | Not asked — see [Using a cookies file instead](#using-a-cookies-file-instead) |

Agenda PDFs under `output/.../Public/` are built from the public BoardDocs site only.

### When your password **is** used (if you provide a username)

A password is requested only if **all** of the following are true:

1. You did **not** pass `--public-only`, and  
2. You did **not** pass `--cookies-file`, and  
3. You set a username (`--username` or `"username"` in `config.json`).

Without a username or cookies file, the exporter skips private export automatically; use `--private-only` with credentials when you intend to export only logged-in content.

That covers these common commands:

| Command / mode | Password prompted? |
|----------------|-------------------|
| `--private-only --username …` | **Yes** |
| Export **both** public and private: `--username …` (without `--public-only`) | **Yes** (once, before private work) |
| `--survey-content` with `--username …` (and not `--public-only`) | **Yes** |
| `--public-only` even with `--username` | **No** (username ignored for login) |

There is **no** `--password` flag. The program uses Python’s hidden prompt (`getpass`); characters are not shown as you type.

### What happens to the password after you enter it

1. **In memory only** — The password exists briefly in RAM. It is **not** written to `config.json`, export logs, or PDFs under `output/`. If you add a `"password"` key to `config.json`, it is **ignored** (only `username` is loaded for login).
2. **BoardDocs login page** — Chromium (Playwright) opens your district’s private login URL (`login_url`, or derived from `public_url`). It fills the username and password fields the same way you would in a browser, then submits the form to **BoardDocs** (`go.boarddocs.com` over HTTPS).
3. **Session cookies only** — After login, AbandonBoard copies **browser cookies** into an in-memory HTTP session and closes the browser. Further downloads use those cookies to call BoardDocs APIs (`BD-GetMeetingsList`, `BD-GetAgenda`, `BD-GetFiles`, etc.). The password itself is not sent again on those API calls.
4. **Optional visible browser** — With `--headed-login`, the Chromium window stays visible so you can see the login form being filled (useful for troubleshooting). The password still goes only to BoardDocs’ login page in that window.

AbandonBoard does not implement its own user accounts or cloud storage; credentials go to your district’s BoardDocs site under the same rules as logging in manually.

### Using a cookies file instead

If you pass `--cookies-file` (for example `cookies.json`, gitignored), AbandonBoard **does not prompt for a password**. It loads cookies you exported from a browser where you already logged in. You are responsible for keeping that file private — it can grant the same access as your session.

### Quick reference in the docs

- [Private export (login)](#private-export-login) — password or cookies  
- [Both public and private](#both-public-and-private) — password once if `username` is set  
- [Discover Public / Administrative / Executive content](#discover-public--administrative--executive-content) — password if `username` is set  
- [Getting started: Private (login) export](#private-login-export) — beginner-facing summary  

## Tests

Unit tests cover parsing, URL/link remapping, committee merging, and minimal PDF assembly. (They were created with AI):

```powershell
pip install -r requirements-dev.txt
pytest
```

Verbose: `pytest -v`

## Usage

### Public export (Phoenixville default)

**Does not use your password** (no `username` / not logging in). Running without credentials exports public agendas only; add `--public-only` if you want to be explicit.

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

**Uses your password** when you pass `--username` (same login flow as private export; omit `--public-only`). See [Password and login (transparency)](#password-and-login-transparency).

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

**Uses your password** if you pass `--username` (prompted at runtime). **Does not use your password** if you use `--cookies-file` instead. Details: [Password and login (transparency)](#password-and-login-transparency).

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

**Uses your password once** at the start (prompted) to open the private session; public agendas are still fetched without your password. See [Password and login (transparency)](#password-and-login-transparency).

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
- **Password handling** — summarized in [Password and login (transparency)](#password-and-login-transparency). Passwords are not stored in config or output files; optional `cookies.json` is equivalent to a saved browser session.
- Private documents may require district credentials. Logged-in agendas may include **Public Content**, **Administrative Content**, and **Executive Content** sections; use `--survey-content` to see which APIs serve each section on your site.
- Per-item fetch merges `BD-GetFiles` and `BD-GetPublicFiles` when both respond; print-agenda HTML remains the main source for weekly-packet style meetings.

## Why AbandonBoard?

Because “sunsetting BoardDocs” is vendor-speak for “your links rot.” This tool exists so school boards keep readable, searchable, offline archives of public business—without paying Diligent to hold your own minutes hostage.
