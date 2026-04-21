# Sold Item Finder

Local macOS desktop app for searching sold-item evidence inside a Google Drive for Desktop synced folder.

## Features

- Image indexing into SQLite
- Text search via SQLite FTS5 (filename/path/metadata/raw JSON-CSV text)
- Optional OpenAI semantic search (embeddings + vision description)
- Email connector (IMAP over SSL) that uses email subject as search query
- Automatic `.docx` report generation for processed emails
- Responsive PySide6 UI with background workers

## Requirements

- Python 3.11+
- macOS
- Google Drive for Desktop installed and synced locally

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m sold_item_finder.app
```

## Web UI (Docker)

The project also includes a lightweight web UI powered by FastAPI.

### Run locally (without Docker)

```bash
uvicorn webapp.main:app --reload --port 8000
```

Open: `http://localhost:8000`

### Run with Docker Compose

Set your Google Drive synced root path before starting:

```bash
export GOOGLE_DRIVE_SYNC_PATH="$HOME/Library/CloudStorage"
docker compose up --build
```

Open: `http://localhost:8000`

Notes:

- Container persists index DB in `./data/index.db`
- In container, mounted Google Drive root is available at `/mnt/google-drive`
- For OpenAI features in web mode, export `OPENAI_API_KEY` before `docker compose up`
- Web UI supports folder selection via:
  - quick path shortcuts
  - **Browse Folders** button (lists subfolders, click to select)

### Receipt Parser UI (OpenAI + PostgreSQL + Alembic)

New web page: `http://localhost:8001/receipts`

Flow:

- Upload a `.pdf` receipt from the UI
- Extract receipt fields via OpenAI
- Insert extracted item rows into `receipt_items` table
- View the receipt table with the same column order as the XLSX export
- See the imported thumbnail image as the first column in the UI
- Download `.xlsx` export with:
  - a `receipt_items` sheet using the same 14-column layout as the GUI
  - an `item_images` sheet containing the embedded image thumbnails

Receipt column order:

1. `Item No`
2. `SKU`
3. `Marketplace`
4. `Type`
5. `Video`
6. `Bought at`
7. `Sell at`
8. `Size`
9. `Count`
10. `Item name`
11. `Link`
12. `item_trader`
13. `payment_method`
14. `Order ID`

Required env vars for receipt parsing:

- `OPENAI_API_KEY` (for LLM extraction)
- `RECEIPT_DATABASE_URL` (PostgreSQL SQLAlchemy URL, e.g. `postgresql+psycopg://searchtool:searchtool@localhost:5433/searchtool`)

Apply DB migrations:

```bash
alembic upgrade head
```

## Google Drive Folder

In the **Image Search** tab, set the root folder to your local synced Google Drive folder. Common path example:

`~/Library/CloudStorage/GoogleDrive-<account>/My Drive`

Then run indexing. Index data is stored in:

`~/Library/Application Support/SoldItemFinder/index.db`

## Text Search

Use the **Text Search** tab to query:

- Filenames and paths
- Metadata fields (`title`, `sku`, `listing_id`, `notes`, `platform`)
- Flattened JSON/CSV text

## Image Query Search

Use the **Image Search** tab for two actions:

- **Index Folder**: index all images in your configured Google Drive synced folder
- **Search by Image**: choose a query image and find closest indexed images by visual hash similarity
- **Crop Query Image**: crop a selected region in-app, then run search on the crop
- **Use AI semantic match**: optional reranking with OpenAI description + embeddings
- **Strict exact match (SHA only)**: return results only when query file bytes exactly match an indexed image

Results show title/platform/path and can be opened in Finder.
The Image Search UI also displays currently used AI models and matching pipeline.
Visual-only ranking now includes a second-stage pixel similarity rerank on top hash candidates for better precision.

Note: after matcher algorithm updates, run **Index Folder** again to refresh stored hashes for best ranking quality.

## OpenAI setup

Option 1: put your key in a local `.env` file (recommended):

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY
```

Option 2: set your API key in shell before launching:

```bash
export OPENAI_API_KEY="your-key-here"
```

Models used:

- `gpt-4o` for query image description (UI explainability)
- `text-embedding-3-small` for indexing embeddings
- `text-embedding-3-small` for query-time semantic matching (same model as index for compatibility)
- `vision-local-rgbgray-v1` for image rerank cosine similarity

Runtime control:

- Use the **Settings** tab to explicitly enable/disable OpenAI embedding generation during indexing.
- Use **Test OpenAI Connection** in Settings to verify key + SDK + API access from the app.
- This toggle is saved locally and applied at next app launch.

When the key is missing, the app still works with fallback behavior:

- image search uses SHA-256 + pHash
- text search can continue with keyword FTS mode
- image rerank still uses local vision embeddings; only AI description text is disabled

## Email Conn (IMAP)

Use the **Email Conn** tab:

- Configure IMAP host/port/username
- Set the monitored target address (for example `taskin.baba@gmail.com`)
- Save password with **Save Password** (stored in system keychain via `keyring`)
- Test connection, fetch emails, process selected/all
- Optional debug screen: enable **Enable debug screen** to inspect fetch/process diagnostics live
- Email fetch now routes through a local MCP email server tool (subject/body and supported attachment parsing)
- Email details screen now shows attachment list and extracted text for PDF, DOCX, CSV, XLSX files

### MCP email server tools

- Tool schemas: `docs/mcp_email_tools.json`
- Minimal server layout: `docs/mcp_email_server_structure.md`
- Migration checklist: `docs/mcp_email_migration_checklist.md`

Run MCP server manually (stdio mode) if needed:

```bash
python -m mcp_email_server.server --stdio
```

### Gmail notes

- In Gmail settings, IMAP must be enabled.
- For password auth, use a Google App Password (not your normal Gmail password).
- Use IMAP host `imap.gmail.com`, port `993`, SSL enabled.

## Reports

For each processed email, a report is created at:

`~/Documents/SoldItemFinder/Reports/YYYY-MM-DD/<sanitized_subject>_<message_id>.docx`

The report includes:

- Email details
- Query text
- Top matches with metadata/path/score
- Up to 2 embedded images per result when available

## Tests

```bash
pytest -q
```
