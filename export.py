# This program export Zendesk chat history and all others data to a file, which can be used for backup or migration purposes.
# It will export all chats, including the chat content, chat metadata, and any attachments. The exported data will be saved in a JSON format, which can be easily imported into other systems or used for analysis.
# The API call can be chuncked to avoid timeouts and ensure that all data is exported successfully. The program will also handle any errors that may occur during the export process and provide appropriate feedback to the user.
# The program should let the user specify the date range for the export, so that they can choose to export only the relevant data. The exported file will be named according to the specified date range for easy identification.
# The program should be able to export specific data i.e Chat history, user information, and other relevant data based on the user's selection. This will allow users to export only the data they need, rather than exporting everything at once.
# The program should accept variables for the API endpoint, authentication credentials, and other necessary parameters to ensure that it can be easily configured for different Zendesk accounts and environments. This will make the program more flexible and adaptable to different use cases.
# Add comment to every function and class to explain what it does and how it works. This will help other developers understand the code and make it easier to maintain and extend in the future.


"""
Zendesk Full Data Export Script
================================
Exports: Tickets, Conversations, Attachments, Ticket Custom Fields,
         User Custom Fields, Tags, Triggers, Automations, Help Center Articles

Usage:
    pip install requests python-dotenv
    python export.py                                    # Export all data as JSON
    python export.py --format csv                      # Export records as CSV
    python export.py --only tickets users --format csv # Export specific data as CSV

Configuration (via .env or environment variables):
    ZENDESK_SUBDOMAIN   — your Zendesk subdomain (e.g. "mycompany")
    ZENDESK_EMAIL       — agent email address
    ZENDESK_API_TOKEN   — API token from Admin > Apps & Integrations > APIs
    EXPORT_DIR          — output directory (default: ./zendesk_export)
    BATCH_SIZE          — records per page (default: 100, max: 100)
    DOWNLOAD_ATTACHMENTS— "true" to download attachment files (default: false)
    EXPORT_FORMAT       — export format: "json" or "csv" (default: json)
"""

# Import necessary modules for the program
import os  # For interacting with the operating system (like reading environment variables)
import sys  # For system-specific parameters and functions
import json  # For working with JSON data format
import time  # For adding delays and working with timestamps
import logging  # For recording program activity and errors
import argparse  # For handling command-line arguments
import requests  # For making HTTP requests to the Zendesk API
from pathlib import Path  # For working with file paths in a cross-platform way
from datetime import datetime, timezone  # For working with dates and times

# -- Optional .env support ---------------------------------------------------
# Try to load environment variables from a .env file if the python-dotenv package is installed
# This allows us to keep sensitive information like API keys separate from the code
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load variables from .env file into environment
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars

# -- Logging -----------------------------------------------------------------
# Set up logging to record what the program is doing
# This helps with debugging and monitoring the export process

# Ensure console can handle Unicode characters
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,  # Log informational messages and above (INFO, WARNING, ERROR)
    format="%(asctime)s [%(levelname)s] %(message)s",  # Format: timestamp [level] message
    handlers=[
        logging.StreamHandler(sys.stdout),  # Also print logs to the console
        logging.FileHandler("zendesk_export.log", encoding='utf-8'),  # Save logs to a file with UTF-8 encoding
    ],
)
log = logging.getLogger("zendesk_export")  # Create a logger specifically for this program


# ============================================================================
# Config
# ============================================================================

# This class holds all the configuration settings for the Zendesk export
# It reads values from environment variables (which can come from .env file)
class Config:
    # These are the basic settings needed to connect to Zendesk
    subdomain: str = os.getenv("ZENDESK_SUBDOMAIN", "")  # Your Zendesk subdomain (the part before .zendesk.com)
    email: str     = os.getenv("ZENDESK_EMAIL", "")      # Your Zendesk account email
    api_token: str = os.getenv("ZENDESK_API_TOKEN", "")  # API token for authentication
    
    # These control how the export works
    export_dir: str = os.getenv("EXPORT_DIR", "./zendesk_export")  # Where to save exported files
    batch_size: int = int(os.getenv("BATCH_SIZE", "100"))          # How many records to get at once
    download_attachments: bool = os.getenv("DOWNLOAD_ATTACHMENTS", "false").lower() == "true"  # Whether to download file attachments
    export_format: str = os.getenv("EXPORT_FORMAT", "json").lower()  # Export format: "json" or "csv"

    # Properties that build URLs automatically
    @property
    def base_url(self) -> str:
        # Creates the base API URL using the subdomain
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    @property
    def hc_base_url(self) -> str:
        # Creates the Help Center API URL (different endpoint)
        return f"https://{self.subdomain}.zendesk.com/api/v2/help_center"

    def validate(self):
        # Checks that all required settings are provided
        missing = [k for k in ("subdomain", "email", "api_token") if not getattr(self, k)]
        if missing:
            log.error("Missing required config: %s", ", ".join(missing))
            log.error("Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN env vars.")
            sys.exit(1)  # Stop the program if required settings are missing


# Create a global config object that will be used throughout the program
cfg = Config()


# ============================================================================
# HTTP client with rate-limit handling
# ============================================================================

# This class handles all communication with the Zendesk API
# It automatically handles rate limiting (when the API says "slow down")
class ZendeskClient:
    """Thin wrapper around requests with automatic retry on 429."""

    def __init__(self):
        # Set up a session for making HTTP requests
        self.session = requests.Session()
        # Set up authentication using email and API token
        self.session.auth = (f"{cfg.email}/token", cfg.api_token)
        # Tell the API we want JSON responses
        self.session.headers.update({"Content-Type": "application/json"})

    def get(self, url: str, params: dict = None) -> dict:
        """Make a GET request and return the JSON response as a dict."""
        max_retries = 3  # Maximum number of retries for server errors
        retry_count = 0
        
        while True:  # Keep trying until successful
            try:
                # Make the HTTP request
                resp = self.session.get(url, params=params, timeout=30)
                
                # Check if we hit the rate limit (HTTP status 429)
                if resp.status_code == 429:
                    # Get how long to wait from the response header
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    log.warning("Rate limited. Sleeping %ds …", retry_after)
                    time.sleep(retry_after)  # Wait before trying again
                    continue
                
                # Check for server errors (5xx) that should be retried
                if resp.status_code >= 500 and retry_count < max_retries:
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count)  # Exponential backoff, max 30 seconds
                    log.warning("Server error %d. Retrying in %ds (attempt %d/%d) …", 
                              resp.status_code, wait_time, retry_count, max_retries)
                    time.sleep(wait_time)
                    continue
                
                # If we get here, the request was successful or we exhausted retries
                resp.raise_for_status()  # Raise an error for bad HTTP status codes
                return resp.json()  # Convert JSON response to Python dictionary
                
            except requests.RequestException as e:
                # Handle network errors (timeouts, connection errors, etc.)
                if retry_count < max_retries:
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count)
                    log.warning("Request failed: %s. Retrying in %ds (attempt %d/%d) …", 
                              str(e), wait_time, retry_count, max_retries)
                    time.sleep(wait_time)
                    continue
                else:
                    # Re-raise the exception if we've exhausted retries
                    raise

    def get_bytes(self, url: str) -> bytes:
        """Download binary content (like attachment files)."""
        max_retries = 3  # Maximum number of retries for server errors
        retry_count = 0
        
        while True:  # Keep trying until successful
            try:
                resp = self.session.get(url, timeout=60)
                
                # Check if we hit the rate limit (HTTP status 429)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    log.warning("Rate limited. Sleeping %ds …", retry_after)
                    time.sleep(retry_after)
                    continue
                
                # Check for server errors (5xx) that should be retried
                if resp.status_code >= 500 and retry_count < max_retries:
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count)  # Exponential backoff, max 30 seconds
                    log.warning("Server error %d. Retrying in %ds (attempt %d/%d) …", 
                              resp.status_code, wait_time, retry_count, max_retries)
                    time.sleep(wait_time)
                    continue
                
                # If we get here, the request was successful or we exhausted retries
                resp.raise_for_status()
                return resp.content  # Return raw bytes for file downloads
                
            except requests.RequestException as e:
                # Handle network errors (timeouts, connection errors, etc.)
                if retry_count < max_retries:
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count)
                    log.warning("Request failed: %s. Retrying in %ds (attempt %d/%d) …", 
                              str(e), wait_time, retry_count, max_retries)
                    time.sleep(wait_time)
                    continue
                else:
                    # Re-raise the exception if we've exhausted retries
                    raise


# Create a global client object for making API calls
client = ZendeskClient()


# ============================================================================
# Helpers
# ============================================================================

def save_json(data, path: Path):
    """Save data as a JSON file. Creates directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)  # Create parent directories
    with open(path, "w", encoding="utf-8") as f:
        # Save data as nicely formatted JSON
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def save_jsonl(records: list, path: Path):
    """Save records to a JSON Lines (JSONL) file (append mode). Creates directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")



def save_csv(records: list, path: Path, fieldnames: list = None, mode: str = "w"):
    """Save data as a CSV file. Creates directories if needed."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        return

    # Flatten all records first so header columns include every nested field.
    flat_records = [flatten_dict(record) for record in records]
    if not fieldnames:
        fieldnames = []
        for record in flat_records:
            for key in record.keys():
                if key not in fieldnames:
                    fieldnames.append(key)

    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":  # Only write header for new files
            writer.writeheader()
        for record in flat_records:
            writer.writerow({k: record.get(k, "") for k in fieldnames})


def load_json_data(path: Path):
    """Load JSON or JSONL data from disk."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    decoder = json.JSONDecoder()
    position = 0
    results = []
    length = len(text)

    while position < length:
        # Skip whitespace and separators between records
        while position < length and text[position] in " \t\r\n,":
            position += 1
        if position >= length:
            break

        try:
            obj, next_position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            # If JSONL contains embedded newlines, fall back to line-by-line parsing
            if path.suffix.lower() == ".jsonl":
                results = []
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        log.warning("  Skipping malformed JSONL line in %s: %s", path.name, e)
                return results
            raise

        results.append(obj)
        position = next_position

    if len(results) == 1 and isinstance(results[0], list):
        return results[0]
    return results


def load_export_state(out_dir: Path) -> dict:
    """Load export state containing last sync timestamps."""
    state_path = out_dir / "export_state.json"
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("  Failed to load export state: %s. Starting from scratch.", e)
    return {}


def save_export_state(out_dir: Path, state: dict):
    """Save export state containing last sync timestamps."""
    state_path = out_dir / "export_state.json"
    save_json(state, state_path)


def convert_existing_exports(out_dir: Path):
    """Convert existing JSON/JSONL exports in the output folder to CSV."""
    log.info("-- Converting local exported files to CSV ----------------")

    conversions = [
        ("tickets.jsonl", "tickets.csv"),
        ("ticket_conversations.jsonl", "ticket_conversations.csv"),
        ("attachments_metadata.jsonl", "attachments_metadata.csv"),
        ("help_center_articles.jsonl", "help_center_articles.csv"),
        ("help_center_translations.jsonl", "help_center_translations.csv"),
        ("users.jsonl", "users.csv"),
        ("organizations.jsonl", "organizations.csv"),
        ("ticket_custom_fields.json", "ticket_custom_fields.csv"),
        ("user_custom_fields.json", "user_custom_fields.csv"),
        ("tags.json", "tags.csv"),
        ("triggers.json", "triggers.csv"),
        ("automations.json", "automations.csv"),
    ]

    for src_name, dst_name in conversions:
        src_path = out_dir / src_name
        if not src_path.exists():
            continue

        try:
            data = load_json_data(src_path)
        except json.JSONDecodeError as e:
            log.warning("  Skipping %s: invalid JSON (%s)", src_name, e)
            continue

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            log.warning("  Skipping %s: unsupported JSON structure", src_name)
            continue

        if not data:
            log.info("  Skipping %s: no records found", src_name)
            continue

        dst_path = out_dir / dst_name
        save_csv(data, dst_path)
        log.info("  Converted %s -> %s (%d rows)", src_name, dst_name, len(data))

    log.info("[OK] Local conversion complete.")


def flatten_dict(d, prefix=""):
    """Flatten a nested dictionary for CSV export."""
    flattened = {}
    for key, value in d.items():
        new_key = f"{prefix}{key}" if prefix else key
        
        if isinstance(value, dict):
            flattened.update(flatten_dict(value, f"{new_key}_"))
        elif isinstance(value, list):
            # Convert lists to comma-separated strings
            flattened[new_key] = ", ".join(str(item) for item in value)
        else:
            flattened[new_key] = value
    return flattened


def merge_records(existing: list, new_records: list, key: str = "id") -> list:
    """Merge new records into existing ones, de-duplicating by a key field."""
    merged = {r[key]: r for r in existing if key in r}
    for r in new_records:
        if key in r:
            merged[r[key]] = r
    return list(merged.values())


def paginate_cursor(endpoint: str, key: str, params: dict = None) -> list:
    """
    Generic cursor-based paginator (Zendesk Cursor Pagination).
    Returns all records from the endpoint.
    
    Cursor pagination is like turning pages in a book - each page gives you
    a "cursor" (pointer) to the next page, rather than page numbers.
    """
    url = f"{cfg.base_url}/{endpoint}"  # Build the full API URL
    all_records = []  # Will collect all records from all pages
    page_num = 1
    params = {**(params or {}), "page[size]": cfg.batch_size}  # Add page size to params

    while url:  # Keep going until no more pages
        log.info("  -> fetching page %d from %s", page_num, endpoint)
        # Get one page of data
        data = client.get(url, params=params if page_num == 1 else None)
        records = data.get(key, [])  # Extract records from the response
        all_records.extend(records)  # Add to our collection
        log.info("    fetched %d records (total so far: %d)", len(records), len(all_records))

        # Check if there's another page
        meta = data.get("meta", {})
        if meta.get("has_more"):
            url = data.get("links", {}).get("next")  # Get URL for next page
        else:
            url = None  # No more pages
        page_num += 1
        time.sleep(0.2)  # Small delay to be nice to the API

    return all_records


def paginate_offset(endpoint: str, key: str, params: dict = None, base: str = None) -> list:
    """Offset/page-number paginator for APIs that don't support cursor pagination."""
    base_url = base or cfg.base_url
    url = f"{base_url}/{endpoint}"
    all_records = []
    page_num = 1
    params = {**(params or {}), "per_page": cfg.batch_size}

    while url:
        log.info("  -> fetching page %d from %s", page_num, endpoint)
        data = client.get(url, params=params if page_num == 1 else None)
        records = data.get(key, [])
        all_records.extend(records)
        log.info("    fetched %d records (total so far: %d)", len(records), len(all_records))
        url = data.get("next_page")  # API provides direct URL for next page
        page_num += 1
        time.sleep(0.2)

    return all_records


def incremental_export(resource: str, start_time: int = 0) -> tuple:
    """
    Use Zendesk's Incremental Export (time-based) to get records.
    Starts from start_time to get newer/updated records.
    """
    url = f"{cfg.base_url}/incremental/{resource}.json"
    all_records = []
    current_start = start_time
    page_num = 1

    while True:
        log.info("  -> incremental export page %d (start_time=%d)", page_num, current_start)
        # Ask for records changed after current_start
        data = client.get(url, params={"start_time": current_start})
        records = data.get(resource, [])
        all_records.extend(records)
        log.info("    fetched %d records (total so far: %d)", len(records), len(all_records))

        # Check if we've reached the end
        if data.get("end_of_stream"):
            log.info("  [OK] Reached end of stream.")
            current_start = data.get("end_time", current_start)
            break

        # Get the time to start from for the next batch
        next_start = data.get("end_time")
        if not next_start or next_start == current_start:
            break
        current_start = next_start
        page_num += 1
        time.sleep(0.5)  # Incremental API has stricter rate limits

    return all_records, current_start


# ============================================================================
# Export functions
# ============================================================================

def export_tickets(out_dir: Path) -> tuple:
    """Export tickets via Incremental API, merging with existing records."""
    log.info("-- Exporting Tickets ----------------------------------")
    
    # Load state
    state = load_export_state(out_dir)
    start_time = state.get("tickets_last_timestamp", 0)
    
    # Load existing tickets
    jsonl_path = out_dir / "tickets.jsonl"
    existing_tickets = []
    if jsonl_path.exists():
        try:
            existing_tickets = load_json_data(jsonl_path)
            log.info("  Loaded %d existing tickets from disk.", len(existing_tickets))
        except Exception as e:
            log.warning("  Failed to load existing tickets from disk: %s", e)
            
    # Fetch new/updated tickets
    new_tickets, end_time = incremental_export("tickets", start_time=start_time)
    
    # Filter out deleted tickets from the new batch
    deleted_ids = {t["id"] for t in new_tickets if t.get("status") == "deleted"}
    active_new_tickets = [t for t in new_tickets if t.get("status") != "deleted"]
    
    # Merge and de-duplicate
    merged_tickets = merge_records(existing_tickets, active_new_tickets)
    merged_tickets = [t for t in merged_tickets if t.get("id") not in deleted_ids]
    
    # Save JSONL (source of truth)
    jsonl_path.unlink(missing_ok=True)
    save_jsonl(merged_tickets, jsonl_path)
    
    # Save CSV if configured
    if cfg.export_format == "csv":
        csv_path = out_dir / "tickets.csv"
        save_csv(merged_tickets, csv_path)
        
    # Update state
    state["tickets_last_timestamp"] = end_time
    save_export_state(out_dir, state)
    
    log.info("[OK] Exported %d tickets (fetched %d new/updated, total: %d) -> %s",
             len(merged_tickets), len(new_tickets), len(merged_tickets), jsonl_path)
             
    return merged_tickets, active_new_tickets


def export_ticket_conversations(tickets: list, out_dir: Path):
    """Export comments (conversations) for every ticket in `tickets`, merging with existing records."""
    log.info("-- Exporting Ticket Conversations ---------------------")
    out_jsonl = out_dir / "ticket_conversations.jsonl"
    
    # Load existing conversations
    existing_convs = {}
    if out_jsonl.exists():
        try:
            loaded = load_json_data(out_jsonl)
            existing_convs = {c["ticket_id"]: c for c in loaded if "ticket_id" in c}
            log.info("  Loaded %d existing conversations from disk.", len(existing_convs))
        except Exception as e:
            log.warning("  Failed to load existing conversations: %s", e)
            
    # Filter out conversations for tickets that were deleted
    tickets_path = out_dir / "tickets.jsonl"
    all_tickets = []
    if tickets_path.exists():
        try:
            all_tickets = load_json_data(tickets_path)
            active_ticket_ids = {t["id"] for t in all_tickets}
            existing_convs = {tid: c for tid, c in existing_convs.items() if tid in active_ticket_ids}
        except Exception as e:
            log.warning("  Failed to filter deleted ticket conversations: %s", e)

    # Determine tickets that need comment syncing:
    # 1. Tickets that were updated/added in this run
    # 2. Tickets that are in all_tickets but missing from existing_convs (self-healing / interrupted runs)
    tickets_to_sync = []
    for t in tickets:
        tickets_to_sync.append(t)
        
    existing_tids = set(existing_convs.keys())
    for t in all_tickets:
        tid = t["id"]
        if tid not in existing_tids:
            if not any(ts["id"] == tid for ts in tickets_to_sync):
                tickets_to_sync.append(t)

    attachment_meta = []  # Will collect info about file attachments
    total = len(tickets_to_sync)
    
    if total > 0:
        log.info("  Syncing conversations for %d tickets (includes updated and missing ones) …", total)
        for i, ticket in enumerate(tickets_to_sync, 1):
            tid = ticket["id"]
            if i % 50 == 0 or i == total:
                log.info("  comments: ticket %d/%d (id=%s)", i, total, tid)

            try:
                # Get all comments for this ticket
                data = client.get(f"{cfg.base_url}/tickets/{tid}/comments.json",
                                  params={"include": "users", "per_page": 100})
                comments = data.get("comments", [])

                # Store comments
                existing_convs[tid] = {"ticket_id": tid, "comments": comments}
                
            except Exception as e:
                log.warning("  Failed to export conversations for ticket %s: %s", tid, str(e))
                # Store error so we don't block
                existing_convs[tid] = {"ticket_id": tid, "comments": [], "error": str(e)}
                
            # Save progress incrementally to jsonl every 50 tickets to protect sync progress
            if i % 50 == 0 or i == total:
                merged_convs_list = list(existing_convs.values())
                out_jsonl.unlink(missing_ok=True)
                save_jsonl(merged_convs_list, out_jsonl)

            time.sleep(0.1)

    # Save merged conversations final state
    merged_convs_list = list(existing_convs.values())
    out_jsonl.unlink(missing_ok=True)
    save_jsonl(merged_convs_list, out_jsonl)
    
    if cfg.export_format == "csv":
        out_csv = out_dir / "ticket_conversations.csv"
        # Flatten all comments across all ticket conversations
        flat_records = []
        for conv in merged_convs_list:
            tid = conv.get("ticket_id")
            if "error" in conv:
                flat_records.append({"ticket_id": tid, "error": conv["error"]})
            else:
                for comment in conv.get("comments", []):
                    flat_records.append({"ticket_id": tid, **comment})
        
        # Save CSV
        save_csv(flat_records, out_csv)
        log.info("[OK] Conversations saved as CSV -> %s", out_csv)
    
    # Extract all attachment metadata from the final merged conversations to return
    for conv in merged_convs_list:
        tid = conv.get("ticket_id")
        for comment in conv.get("comments", []):
            for att in comment.get("attachments", []):
                att["ticket_id"] = tid
                att["comment_id"] = comment["id"]
                attachment_meta.append(att)

    log.info("[OK] Conversations sync complete. Total conversations: %d", len(merged_convs_list))
    return attachment_meta


def export_attachments(attachment_meta: list, out_dir: Path):
    """Save attachment metadata; optionally download the actual files."""
    log.info("-- Exporting Attachment Metadata ----------------------")
    meta_path = out_dir / "attachments_metadata.jsonl"
    
    # Load existing attachments
    existing_attachments = []
    if meta_path.exists():
        try:
            existing_attachments = load_json_data(meta_path)
            log.info("  Loaded %d existing attachment records from disk.", len(existing_attachments))
        except Exception as e:
            log.warning("  Failed to load existing attachments metadata: %s", e)
            
    # Merge and de-duplicate by 'id'
    merged_attachments = merge_records(existing_attachments, attachment_meta, key="id")
    
    # Save jsonl
    meta_path.unlink(missing_ok=True)
    save_jsonl(merged_attachments, meta_path)
    
    # Save CSV if configured
    if cfg.export_format == "csv":
        csv_path = out_dir / "attachments_metadata.csv"
        save_csv(merged_attachments, csv_path)
        
    log.info("[OK] %d attachment records saved -> %s", len(merged_attachments), meta_path)
    
    if cfg.download_attachments:  # Only download files if configured to do so
        log.info("-- Downloading Attachment Files ------------------------")
        files_dir = out_dir / "attachment_files"
        files_dir.mkdir(parents=True, exist_ok=True)  # Create directory for files
        for i, att in enumerate(merged_attachments, 1):
            # Create a unique filename for each attachment
            filename = f"{att['ticket_id']}_{att['comment_id']}_{att.get('file_name', att['id'])}"
            dest = files_dir / filename
            if dest.exists():  # Skip if already downloaded
                continue
            log.info("  downloading %d/%d: %s", i, len(merged_attachments), filename)
            try:
                content = client.get_bytes(att["content_url"])  # Download the file
                dest.write_bytes(content)  # Save to disk
            except Exception as e:
                log.warning("  failed to download %s: %s", filename, e)
            time.sleep(0.1)  # Small delay between downloads
        log.info("[OK] Attachment files saved -> %s", files_dir)
    else:
        log.info("  (Attachment file download skipped. Set DOWNLOAD_ATTACHMENTS=true to enable.)")



def export_ticket_fields(out_dir: Path):
    """Export ticket custom field definitions."""
    log.info("-- Exporting Ticket Custom Fields ---------------------")
    # Get definitions of custom fields that can be added to tickets
    data = client.get(f"{cfg.base_url}/ticket_fields.json")
    fields = data.get("ticket_fields", [])
    path = out_dir / "ticket_custom_fields.json"
    save_json(fields, path)
    log.info("[OK] Exported %d ticket field definitions -> %s", len(fields), path)


def export_user_fields(out_dir: Path):
    """Export user custom field definitions."""
    log.info("-- Exporting User Custom Fields -----------------------")
    # Get definitions of custom fields that can be added to users
    fields = paginate_offset("user_fields.json", "user_fields")
    path = out_dir / "user_custom_fields.json"
    save_json(fields, path)
    log.info("[OK] Exported %d user field definitions -> %s", len(fields), path)


def export_tags(out_dir: Path):
    """Export all tags."""
    log.info("-- Exporting Tags -------------------------------------")
    # Tags are labels that can be applied to tickets
    tags = paginate_offset("tags.json", "tags")
    path = out_dir / "tags.json"
    save_json(tags, path)
    log.info("[OK] Exported %d tags -> %s", len(tags), path)


def export_triggers(out_dir: Path):
    """Export triggers."""
    log.info("-- Exporting Triggers ---------------------------------")
    # Triggers are automated actions that happen when certain conditions are met
    triggers = paginate_cursor("triggers", "triggers")
    path = out_dir / "triggers.json"
    save_json(triggers, path)
    log.info("[OK] Exported %d triggers -> %s", len(triggers), path)


def export_automations(out_dir: Path):
    """Export automations."""
    log.info("-- Exporting Automations ------------------------------")
    # Automations are similar to triggers but run on a schedule
    automations = paginate_cursor("automations", "automations")
    path = out_dir / "automations.json"
    save_json(automations, path)
    log.info("[OK] Exported %d automations -> %s", len(automations), path)


def export_help_center_articles(out_dir: Path):
    """Export Help Center articles across all locales."""
    log.info("-- Exporting Help Center Articles ---------------------")

    # First get all locales (languages) available
    try:
        locales_data = client.get(f"{cfg.hc_base_url}/articles.json",
                                  params={"per_page": 1})
    except requests.HTTPError as e:
        if e.response.status_code in (403, 404):
            log.warning("  Help Center not enabled or no access. Skipping.")
            return
        raise

    # Get all articles from the Help Center
    articles = paginate_offset("articles.json", "articles", base=cfg.hc_base_url)
    
    if cfg.export_format == "csv":
        path = out_dir / "help_center_articles.csv"
        save_csv(articles, path)
    else:
        path = out_dir / "help_center_articles.jsonl"
        path.unlink(missing_ok=True)
        save_jsonl(articles, path)
    
    log.info("[OK] Exported %d HC articles -> %s", len(articles), path)

    # Export article translations (content in different languages)
    log.info("  Fetching article translations …")
    
    if cfg.export_format == "csv":
        trans_path = out_dir / "help_center_translations.csv"
        trans_path.unlink(missing_ok=True)
    else:
        trans_path = out_dir / "help_center_translations.jsonl"
        trans_path.unlink(missing_ok=True)

    for i, article in enumerate(articles, 1):
        if i % 20 == 0:  # Show progress every 20 articles
            log.info("  translations: article %d/%d", i, len(articles))
        try:
            # Get translations for this article
            data = client.get(
                f"{cfg.hc_base_url}/articles/{article['id']}/translations.json"
            )
            translations = data.get("translations", [])
            
            if cfg.export_format == "csv":
                # For CSV, add article_id to each translation and save
                trans_records = [{"article_id": article["id"], **trans} for trans in translations]
                mode = "a" if i > 1 else "w"
                save_csv(trans_records, trans_path, mode=mode)
            else:
                save_jsonl([{"article_id": article["id"], "translations": translations}],
                           trans_path)
                           
        except Exception as e:
            log.warning("  Failed to get translations for article %s: %s", article["id"], e)
        time.sleep(0.1)

    log.info("[OK] Article translations saved -> %s", trans_path)


def export_users(out_dir: Path):
    """Export all users via Incremental API, merging with existing records."""
    log.info("-- Exporting Users ------------------------------------")
    
    # Load state
    state = load_export_state(out_dir)
    start_time = state.get("users_last_timestamp", 0)
    
    # Load existing users
    jsonl_path = out_dir / "users.jsonl"
    existing_users = []
    if jsonl_path.exists():
        try:
            existing_users = load_json_data(jsonl_path)
            log.info("  Loaded %d existing users from disk.", len(existing_users))
        except Exception as e:
            log.warning("  Failed to load existing users: %s", e)
            
    # Fallback: if state is missing, discover start_time from existing records
    if start_time == 0 and existing_users:
        timestamps = []
        for u in existing_users:
            up_at = u.get("updated_at")
            if up_at:
                try:
                    dt = datetime.fromisoformat(up_at.replace("Z", "+00:00"))
                    timestamps.append(int(dt.timestamp()))
                except Exception:
                    pass
        if timestamps:
            start_time = max(0, max(timestamps) - 60)
            log.info("  Discovered resume start_time for users: %d (%s)", start_time, datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat())

    # Fetch new/updated users
    new_users, end_time = incremental_export("users", start_time=start_time)
    
    # Filter out deleted users from the new batch
    deleted_ids = {u["id"] for u in new_users if u.get("status") == "deleted"}
    active_new_users = [u for u in new_users if u.get("status") != "deleted"]
    
    # Merge and de-duplicate
    merged_users = merge_records(existing_users, active_new_users)
    merged_users = [u for u in merged_users if u.get("id") not in deleted_ids]
    
    # Save JSONL (source of truth)
    jsonl_path.unlink(missing_ok=True)
    save_jsonl(merged_users, jsonl_path)
    
    # Save CSV if configured
    if cfg.export_format == "csv":
        csv_path = out_dir / "users.csv"
        save_csv(merged_users, csv_path)
        
    # Update state
    state["users_last_timestamp"] = end_time
    save_export_state(out_dir, state)
    
    log.info("[OK] Exported %d users (fetched %d new/updated, total: %d) -> %s",
             len(merged_users), len(new_users), len(merged_users), jsonl_path)
    return merged_users


def export_organizations(out_dir: Path):
    """Export all organizations via Incremental API, merging with existing records."""
    log.info("-- Exporting Organizations ----------------------------")
    
    # Load state
    state = load_export_state(out_dir)
    start_time = state.get("organizations_last_timestamp", 0)
    
    # Load existing organizations
    jsonl_path = out_dir / "organizations.jsonl"
    existing_orgs = []
    if jsonl_path.exists():
        try:
            existing_orgs = load_json_data(jsonl_path)
            log.info("  Loaded %d existing organizations from disk.", len(existing_orgs))
        except Exception as e:
            log.warning("  Failed to load existing organizations: %s", e)
            
    # Fallback: if state is missing, discover start_time from existing records
    if start_time == 0 and existing_orgs:
        timestamps = []
        for o in existing_orgs:
            up_at = o.get("updated_at")
            if up_at:
                try:
                    dt = datetime.fromisoformat(up_at.replace("Z", "+00:00"))
                    timestamps.append(int(dt.timestamp()))
                except Exception:
                    pass
        if timestamps:
            start_time = max(0, max(timestamps) - 60)
            log.info("  Discovered resume start_time for organizations: %d (%s)", start_time, datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat())

    # Fetch new/updated orgs
    new_orgs, end_time = incremental_export("organizations", start_time=start_time)
    
    # Merge and de-duplicate
    merged_orgs = merge_records(existing_orgs, new_orgs)
    
    # Save JSONL (source of truth)
    jsonl_path.unlink(missing_ok=True)
    save_jsonl(merged_orgs, jsonl_path)
    
    # Save CSV if configured
    if cfg.export_format == "csv":
        csv_path = out_dir / "organizations.csv"
        save_csv(merged_orgs, csv_path)
        
    # Update state
    state["organizations_last_timestamp"] = end_time
    save_export_state(out_dir, state)
    
    log.info("[OK] Exported %d organizations (fetched %d new/updated, total: %d) -> %s",
             len(merged_orgs), len(new_orgs), len(merged_orgs), jsonl_path)
    return merged_orgs


def export_account_settings(out_dir: Path):
    """Export Zendesk account settings."""
    log.info("-- Exporting Account Settings -------------------------")
    try:
        data = client.get(f"{cfg.base_url}/account/settings.json")
        settings = data.get("settings", {})
        path = out_dir / "account_settings.json"
        save_json(settings, path)
        log.info("[OK] Exported account settings -> %s", path)
    except Exception as e:
        log.warning("  Failed to export account settings: %s", e)


def write_manifest(out_dir: Path, stats: dict):
    """Write an export manifest with metadata."""
    # Create a summary file with information about the export
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),  # When export was done
        "zendesk_subdomain": cfg.subdomain,  # Which Zendesk account
        "batch_size": cfg.batch_size,  # How many records per batch
        "attachments_downloaded": cfg.download_attachments,  # Whether files were downloaded
        "files": {  # List of all exported files and their sizes
            str(p.relative_to(out_dir)): p.stat().st_size
            for p in out_dir.rglob("*") if p.is_file() and p.name != "manifest.json"
        },
        "record_counts": stats,  # How many of each type were exported
    }
    save_json(manifest, out_dir / "manifest.json")
    log.info("[OK] Manifest written -> %s/manifest.json", out_dir)


# ============================================================================
# Main
# ============================================================================

def main():
    """Main function that orchestrates the entire export process."""
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Export all Zendesk data for migration.")
    parser.add_argument("--skip-attachments-download", action="store_true",
                        help="Override DOWNLOAD_ATTACHMENTS and skip binary downloads.")
    parser.add_argument("--format", choices=["json", "csv"], default=None,
                        help="Export format: json or csv (default: from config)")
    parser.add_argument("--local-only", action="store_true",
                        help="Convert local exported JSON/JSONL files to CSV without calling Zendesk.")
    parser.add_argument("--only", nargs="+",
                        choices=["tickets", "conversations", "attachments",
                                 "ticket_fields", "user_fields", "tags",
                                 "triggers", "automations", "articles",
                                 "users", "organizations", "settings"],
                        help="Export only these specific resources.")
    args = parser.parse_args()

    # Handle command-line options
    if args.skip_attachments_download:
        cfg.download_attachments = False
    if args.format:
        cfg.export_format = args.format

    if args.local_only:
        cfg.export_format = "csv"
        out_dir = Path(cfg.export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        convert_existing_exports(out_dir)
        return

    # Make sure we have all required configuration
    cfg.validate()

    # Set up output directory
    out_dir = Path(cfg.export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Print nice header information
    log.info("=======================================================")
    log.info(" Zendesk Export  |  subdomain: %s", cfg.subdomain)
    log.info(" Output dir     : %s", out_dir.resolve())
    log.info(" Batch size     : %d", cfg.batch_size)
    log.info("=======================================================")

    # Decide what to export
    run_all = not args.only  # Export everything if no --only specified
    stats = {}  # Keep track of how many items we exported

    # -- Tickets -----------------------------------------------------------------
    tickets = []
    updated_tickets = []
    if run_all or "tickets" in args.only:
        tickets, updated_tickets = export_tickets(out_dir)
        stats["tickets"] = len(tickets)
    else:
        tickets_path = out_dir / "tickets.jsonl"
        if tickets_path.exists():
            tickets = load_json_data(tickets_path)

    # -- Conversations + attachment metadata ----------------------------------
    attachment_meta = []
    if run_all or "conversations" in args.only:
        if not updated_tickets:
            # If we didn't export tickets in this run (or none were updated),
            # but user requested conversations, we run for all existing tickets.
            log.info("  No updated tickets found in this session or ticket sync skipped.")
            log.info("  Running conversations sync for all existing tickets …")
            updated_tickets = tickets
        attachment_meta = export_ticket_conversations(updated_tickets, out_dir)
        stats["ticket_conversations"] = len(tickets)
        stats["attachment_records"] = len(attachment_meta)

    # -- Attachments ----------------------------------------------------------
    if run_all or "attachments" in args.only:
        if not attachment_meta:  # Load from disk if not already available
            meta_path = out_dir / "attachments_metadata.jsonl"
            if meta_path.exists():
                attachment_meta = [json.loads(l) for l in meta_path.read_text().splitlines() if l]
        export_attachments(attachment_meta, out_dir)

    # -- Ticket custom fields -------------------------------------------------
    if run_all or "ticket_fields" in args.only:
        export_ticket_fields(out_dir)

    # -- User custom fields ---------------------------------------------------
    if run_all or "user_fields" in args.only:
        export_user_fields(out_dir)

    # -- Tags -----------------------------------------------------------------
    if run_all or "tags" in args.only:
        export_tags(out_dir)

    # -- Triggers -------------------------------------------------------------
    if run_all or "triggers" in args.only:
        export_triggers(out_dir)

    # -- Automations ----------------------------------------------------------
    if run_all or "automations" in args.only:
        export_automations(out_dir)

    # -- Help Center Articles -------------------------------------------------
    if run_all or "articles" in args.only:
        export_help_center_articles(out_dir)

    # -- Users ----------------------------------------------------------------
    if run_all or "users" in args.only:
        users = export_users(out_dir)
        stats["users"] = len(users)

    # -- Organizations --------------------------------------------------------
    if run_all or "organizations" in args.only:
        orgs = export_organizations(out_dir)
        stats["organizations"] = len(orgs)

    # -- Settings -------------------------------------------------------------
    if run_all or "settings" in args.only:
        export_account_settings(out_dir)

    # -- Manifest -------------------------------------------------------------
    write_manifest(out_dir, stats)

    # Print completion message
    log.info("=======================================================")
    log.info(" Export complete! Files saved to: %s", out_dir.resolve())
    log.info("=======================================================")


# This is the standard Python way to check if this script is being run directly
# (not imported as a module by another script)
if __name__ == "__main__":
    main()  # Call the main function to start the program