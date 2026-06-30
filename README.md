# Zendesk Migrator 🚀

A robust, production-ready Python command-line tool designed to perform full or targeted exports of your Zendesk support data. Whether you are backing up your workspace, running support operations audits, or migrating to a new customer service platform, this tool provides a resilient, automated, and lightweight solution.

---

## 🌟 Key Features

* 📦 **Full-Schema Coverage:** Exports Tickets, Conversations (chat history), Tags, Triggers, Automations, Help Center Articles, and Custom Fields (for both tickets and users).
* ⚙️ **Smart Rate-Limit Handling:** Automatically respects Zendesk's API rate limits (HTTP 429) by checking `Retry-After` headers and pausing execution gracefully.
* 🛡️ **Network & Server Resilience:** Gracefully handles network hiccups and temporary server errors (HTTP 5xx) with automatic retries (up to 3 times).
* 📄 **Flexible Output Formats:** Save your data in structured **JSON/JSONL** (ideal for database migrations and analysis) or tabular **CSV** format (perfect for spreadsheet reporting).
* 🎯 **Granular Targeting:** Use the `--only` CLI argument to export only specific resources, saving API bandwidth and execution time.
* 📎 **Attachment Downloader:** Optionally download and archive all physical ticket attachment files locally.
* 🔄 **Offline Post-Processing:** Use the `--local-only` mode to convert previously exported JSON data to CSV files locally without making any external API calls to Zendesk.
* 🔒 **Secure Configuration:** Keeps your API credentials safe using `.env` environment variables.

---

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/segunolatoye/Zendesk-Migrator.git
cd Zendesk-Migrator
```

### 2. Install Dependencies
Ensure you have Python 3.8+ installed, then install the required libraries:
```bash
pip install requests python-dotenv
```

---

## ⚙️ Configuration

Copy the sample environment file to create your own local configuration:

```bash
cp .env.sample.txt .env
```

Open `.env` and fill in your Zendesk credentials:

```ini
# Zendesk Connection Info
ZENDESK_SUBDOMAIN=your-subdomain   # Example: 'mycompany' (do not include '.zendesk.com')
ZENDESK_EMAIL=admin@example.com    # Your Zendesk agent email address
ZENDESK_API_TOKEN=your_api_token   # Token generated from Admin > Apps & Integrations > APIs

# Optional Export Settings
EXPORT_DIR=./zendesk_export        # Target directory for exported data
BATCH_SIZE=100                     # Page size for API endpoints (max 100)
DOWNLOAD_ATTACHMENTS=false         # Set to "true" to download actual binary attachment files
EXPORT_FORMAT=json                 # Default format: "json" or "csv"
```

---

## 🚀 Usage Guide

Run the script from your terminal using Python.

### 1. Full Export (Default Settings)
Exports all available resources into JSON files:
```bash
python export.py
```

### 2. Export in CSV Format
Exports all resources directly as CSV files:
```bash
python export.py --format csv
```

### 3. Targeted Resource Export
Export only specific resources (e.g., tickets and users) in CSV:
```bash
python export.py --only tickets users --format csv
```
**Supported resources for `--only`:**
`tickets`, `conversations`, `attachments`, `ticket_fields`, `user_fields`, `tags`, `triggers`, `automations`, `articles`, `users`, `organizations`, `settings`

### 4. Offline CSV Conversion
Convert previously downloaded JSON/JSONL data to CSV offline without querying the Zendesk API:
```bash
python export.py --local-only
```

---

## 📁 Export Directory Structure

When an export completes, your output directory will look like this:

```text
zendesk_export/
├── manifest.json                  # Details about the run (timestamp, settings, counts, files)
├── tickets.jsonl                  # Main ticket data (or tickets.csv)
├── ticket_conversations.jsonl     # Complete conversational messages
├── users.jsonl                    # Zendesk users and agents database
├── articles.jsonl                 # Help Center KB Articles
├── attachments/                   # [Optional] Downloaded physical attachment files
└── zendesk_export.log             # Detailed execution log
```

---

## 🛡️ License

This project is licensed under the MIT License. Feel free to use, modify, and distribute it as needed.
