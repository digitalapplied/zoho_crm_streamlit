#!/usr/bin/env python3
"""
zoho_bulk.py  ·  v3 Final
Shared helper for Zoho CRM bulk operations and metadata fetching.
Includes: full-page CV fetch, credential override, field fetch, bulk update logic.
"""

import json, logging, math, os, time, re
from typing import List, Dict, Optional, Iterable, Union

import requests
from dotenv import load_dotenv

# ── config ────────────────────────────────────────────────────────────────────
load_dotenv()

DEFAULT_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
DEFAULT_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
DEFAULT_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")

DEFAULT_API_DOMAIN    = os.getenv("ZOHO_API_DOMAIN",   "https://www.zohoapis.com")
DEFAULT_ACCOUNTS_URL  = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com/oauth/v2/token")

MODULE_API_NAME = "Leads"
FIELD_TO_UPDATE = "Lead_Status"

PER_PAGE        = 200          # Max records per fetch page
CHUNK_SIZE      = 100          # Max records per update call
MAX_RETRIES     = 3
BACKOFF_SEC     = 2
TIMEOUT_SEC     = 60

VALID_STATUSES = [
    "Not Contacted",
    "Self Storage Questions Sent",
    "Move Questionnaire Sent",
    "Move Questionnaire Follow Up",
    "Move Questionnaire Completed",
    "Onsite Survey Booked",
    "On Hold",
    "Duplicate Lead",
    "Closed Lost",
    "Junk Lead",
    "Not Qualified",
]

# ── logger ────────────────────────────────────────────────────────────────────
# Compile regex patterns for secrets (handle None values)
_SECRET_PATTERNS = []
if DEFAULT_CLIENT_ID: _SECRET_PATTERNS.append(re.escape(DEFAULT_CLIENT_ID))
if DEFAULT_CLIENT_SECRET: _SECRET_PATTERNS.append(re.escape(DEFAULT_CLIENT_SECRET))
if DEFAULT_REFRESH_TOKEN: _SECRET_PATTERNS.append(re.escape(DEFAULT_REFRESH_TOKEN))
# Add patterns for secrets potentially passed from UI (these might be different)
# We'll update this dynamically if UI overrides are used
_dynamic_secret_patterns = []

_log_scrubber = None
if _SECRET_PATTERNS:
    _log_scrubber = re.compile("|".join(_SECRET_PATTERNS))

class _RedactingFilter(logging.Filter):
    """Scrubs configured secrets from log messages."""
    def filter(self, record):
        msg = str(record.msg)
        # Combine static and dynamic patterns
        all_patterns = _SECRET_PATTERNS + _dynamic_secret_patterns
        if all_patterns:
            try:
                # Compile might be slightly more efficient if secrets change often,
                # but pre-compiling should be fine for session-based overrides.
                scrubber = re.compile("|".join(all_patterns))
                record.msg = scrubber.sub("********", msg)
                # Also ensure args are redacted if they contain secrets
                if isinstance(record.args, tuple):
                    record.args = tuple(scrubber.sub("********", str(arg)) if isinstance(arg, str) else arg for arg in record.args)
                elif isinstance(record.args, dict): # Handle dict args if used with % style formatting
                    record.args = {k: scrubber.sub("********", str(v)) if isinstance(v, str) else v for k, v in record.args.items()}

            except re.error as e:
                 # Handle potential regex compilation errors (e.g., special chars in secrets)
                 # Fallback to basic redaction or log the error
                 print(f"Warning: Regex error during log redaction: {e}. Secrets might appear in logs.")
                 # Fallback: simple replace might be safer if regex fails
                 record.msg = msg.replace(DEFAULT_CLIENT_ID or "UNUSED", "********") # Example fallback
                 # Add similar replaces for other secrets if needed
        return True

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    log_formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    # File Handler
    log_filename = "zoho_bulk.log"
    try:
        file_handler = logging.FileHandler(log_filename, encoding="utf-8")
        file_handler.setFormatter(log_formatter)
        file_handler.addFilter(_RedactingFilter()) # Add the redacting filter
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not configure file logging to {log_filename}: {e}")

    # Console Handler (optional, Streamlit might handle this)
    # stream_handler = logging.StreamHandler(sys.stdout)
    # stream_handler.setFormatter(log_formatter)
    # stream_handler.addFilter(_RedactingFilter())
    # logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)

# ── helpers ───────────────────────────────────────────────────────────────────
def chunked(seq: Iterable, n: int) -> Iterable[List]:
    """Yield successive n-sized chunks from seq."""
    it = list(seq)
    for i in range(0, len(it), n):
        yield it[i : i + n]

# ── auth ─────────────────────────────────────────────────────────────────────
def get_access_token(
    client_id:     Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
    accounts_url:  Optional[str] = None,
) -> str:
    """Exchange refresh token for short-lived access token. Prioritizes args over env vars."""
    cid = client_id     or DEFAULT_CLIENT_ID
    csec= client_secret or DEFAULT_CLIENT_SECRET
    rtok= refresh_token or DEFAULT_REFRESH_TOKEN
    aurl= accounts_url  or DEFAULT_ACCOUNTS_URL

    # Dynamically add secrets to the scrubber if they are passed and different
    global _dynamic_secret_patterns
    _dynamic_secret_patterns = [] # Reset dynamic patterns each time token is fetched
    if cid and cid != DEFAULT_CLIENT_ID: _dynamic_secret_patterns.append(re.escape(cid))
    if csec and csec != DEFAULT_CLIENT_SECRET: _dynamic_secret_patterns.append(re.escape(csec))
    if rtok and rtok != DEFAULT_REFRESH_TOKEN: _dynamic_secret_patterns.append(re.escape(rtok))

    if not all((cid, csec, rtok)):
        raise ValueError("Zoho credentials missing – provide via UI or set in .env")

    payload = {"refresh_token": rtok, "client_id": cid,
               "client_secret": csec, "grant_type": "refresh_token"}
    logger.info("Refreshing Zoho access token using %s...", aurl)
    try:
        r = requests.post(aurl, data=payload, timeout=TIMEOUT_SEC)
        r.raise_for_status()
        token_data = r.json()
        token = token_data.get("access_token")
        if not token:
            logged_text = json.dumps(token_data) # Log the JSON response
            logger.error("Token refresh failed: %s", logged_text)
            raise RuntimeError(f"Token refresh failed. Check logs for details. Response: {logged_text[:200]}...") # Show truncated error
        logger.info("Access token obtained successfully.")
        return token
    except requests.exceptions.RequestException as e:
        logger.error("Token request failed: %s", e)
        if hasattr(e, 'response') and e.response is not None:
            logger.error("Response Status: %s, Body: %s", e.response.status_code, e.response.text)
        raise
    except Exception as e:
         logger.exception("Unexpected error during token refresh.")
         raise

def _call(method: str, url: str, token: str, **kw) -> requests.Response:
    """Helper for making Zoho API calls with retry logic."""
    kw.setdefault("timeout", TIMEOUT_SEC)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug("API Call: %s %s Params: %s", method.upper(), url, kw.get('params', {}))
            if 'json' in kw:
                 logger.debug("API Call Body (first 500 chars): %s...", str(kw['json'])[:500])

            resp = requests.request(method, url, headers=headers, **kw)

            # Retry on rate limit or server error
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_SEC * 2**(attempt-1)
                logger.warning("API %s on %s %s attempt %s/%s – backing off %.1fs",
                               resp.status_code, method.upper(), url, attempt, MAX_RETRIES, wait)
                last_exception = requests.exceptions.HTTPError(response=resp) # Store last error
                time.sleep(wait)
                continue # Retry

            resp.raise_for_status() # Raise for other 4xx client errors immediately
            return resp # Success

        except requests.exceptions.RequestException as e:
            logger.error("%s request to %s failed on attempt %s: %s", method.upper(), url, attempt, e)
            last_exception = e
            if attempt == MAX_RETRIES:
                logger.error("Max retries reached for request failure.")
                raise last_exception # Re-raise the last exception after logging
            wait = BACKOFF_SEC * 2 ** (attempt - 1)
            logger.warning("Backing off %.1f seconds due to request failure.", wait)
            time.sleep(wait)
        except Exception as e:
            logger.exception("Unexpected error during API call %s %s", method.upper(), url)
            raise # Re-raise unexpected errors immediately

    # This should only be reached if all retries resulted in 429/5xx without requests raising RequestException
    logger.error(f"API call {method.upper()} {url} failed after {MAX_RETRIES} retries.")
    if last_exception:
        raise last_exception # Raise the last stored HTTPError
    else:
        # Fallback if somehow no exception was stored (shouldn't happen often)
        raise RuntimeError(f"API call failed after {MAX_RETRIES} retries (no specific exception captured).")


# ── CV fetch ─────────────────────────────────────────────────────────────────
def fetch_leads_by_cvid(
    token: str,
    cvid: str,
    *,
    api_domain: str = DEFAULT_API_DOMAIN,
    fetch_all: bool = False,
    module: str = MODULE_API_NAME,
    fields: Optional[List[str]] = None
) -> List[Dict]:
    """Fetch records (ID and optionally other fields) from a Custom View, with pagination."""
    url = f"{api_domain}/crm/v8/{module}"
    all_records: List[Dict] = []
    page = 1
    logger.info(f"Fetching leads from CV ID {cvid} (Module: {module}, Fetch all pages: {fetch_all})...")

    while True:
        params = {"cvid": cvid, "per_page": PER_PAGE, "page": page}
        if fields:
            params["fields"] = ",".join(fields)

        logger.info(f"Fetching page {page}...")
        try:
            response = _call("GET", url, token, params=params)
            response_data = response.json()
            page_data = response_data.get("data", [])
            if not isinstance(page_data, list): # Handle unexpected non-list data
                 logger.warning(f"Received non-list data for page {page}: {response_data}")
                 page_data = []

            all_records.extend(page_data)

            # Check if we need to continue fetching
            more_records = response_data.get("info", {}).get("more_records", False)
            if not fetch_all or not more_records or not page_data:
                logger.info(f"Finished fetching. Total records retrieved: {len(all_records)}")
                break

            page += 1
            logger.info(f"More records exist, fetching next page ({page})...")
            time.sleep(0.5) # Small delay between pages

        except Exception as e:
            # Log error but allow returning partial results if fetch_all=False
            logger.exception(f"Error fetching page {page} for CV ID {cvid}.")
            if fetch_all: # If fetching all, failure on one page is critical
                 raise
            else: # If fetching only first page, return what we have
                 logger.warning("Returning potentially incomplete results due to error.")
                 break

    return all_records

# ── metadata ─────────────────────────────────────────────────────────────────
def get_module_fields(
    token: str, *, module: str = MODULE_API_NAME, api_domain: str = DEFAULT_API_DOMAIN
) -> List[Dict]:
    """Fetch field metadata for a given module."""
    url = f"{api_domain}/crm/v8/settings/fields"
    params = {"module": module}
    logger.info(f"Fetching fields for module: {module}...")
    response = _call("GET", url, token, params=params)
    logger.info(f"Field fetch successful (Status: {response.status_code}).")
    return response.json().get("fields", [])

# ── bulk update ──────────────────────────────────────────────────────────────
def _update_chunk(
    token: str,
    payload_chunk: List[Dict], # Each dict MUST have 'id' and the field to update
    *,
    api_domain: str
) -> List[Dict]:
    """Sends one PUT request for a chunk of records, processes response."""
    url = f"{api_domain}/crm/v8/{MODULE_API_NAME}"
    body = {"data": payload_chunk}
    ids_in_chunk = [item.get('id', 'UNKNOWN_ID_IN_CHUNK') for item in payload_chunk]
    logger.info(f"Sending update chunk for {len(ids_in_chunk)} IDs (e.g., {ids_in_chunk[0]})...")

    try:
        response = _call("PUT", url, token, json=body)
        response_data = response.json()
        # Zoho might return 200/202 but contain individual errors in 'data'
        chunk_results = response_data.get("data", [])
        if not isinstance(chunk_results, list):
             logger.warning(f"Unexpected 'data' format in chunk response: {response_data}")
             return [ # Create error entries for the whole chunk
                 {"id": _id, "status": "error", "code": "INVALID_CHUNK_RESPONSE",
                  "message": "Unexpected format in API response data.", "details": {}}
                 for _id in ids_in_chunk
             ]
        logger.info(f"Chunk response received (Status: {response.status_code}). Processing {len(chunk_results)} results.")
        return chunk_results

    except requests.exceptions.HTTPError as e:
         logger.error(f"HTTP Error updating chunk: {e}")
         if hasattr(e, 'response') and e.response is not None:
             logger.error(f"Response Status: {e.response.status_code}, Body: {e.response.text}")
             # Attempt to parse detailed errors if available
             error_details = {}
             try:
                 error_json = e.response.json()
                 if 'data' in error_json and isinstance(error_json['data'], list):
                      # If Zoho returns individual errors even on HTTP error status
                      return error_json['data']
                 # Otherwise, capture the top-level error info
                 error_details = {
                     "status": error_json.get("status", "error"),
                     "code": error_json.get("code", f"HTTP_{e.response.status_code}"),
                     "message": error_json.get("message", f"HTTP {e.response.status_code}"),
                     "details": error_json.get("details", {"raw_response": e.response.text[:500]})
                 }
             except json.JSONDecodeError:
                 error_details = {"raw_response": e.response.text[:500]}

             # Return generic error status for all IDs in the failed chunk
             return [
                 {"id": _id, **error_details} for _id in ids_in_chunk
             ]
         else: # If no response object available
            return [
                {"id": _id, "status": "error", "code": "REQUEST_FAILED_NO_RESPONSE",
                 "message": f"HTTP request failed without response: {e}", "details": {}}
                for _id in ids_in_chunk
            ]

    except Exception as e:
         logger.exception(f"Unexpected error updating chunk for IDs starting with {ids_in_chunk[0]}.")
         return [
            {"id": _id, "status": "error", "code": "CHUNK_PROCESSING_ERROR",
             "message": f"Unexpected error during chunk update: {e}", "details": {}}
            for _id in ids_in_chunk
         ]

def bulk_update(
    rows: List[Dict],          # Each dict: {"id": "...", "status": "..."}
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
    accounts_url: Optional[str] = None,
    api_domain: Optional[str] = None,
    progress_hook: Optional[callable] = None # Callback for progress updates
) -> List[Dict]:
    """Main function to perform bulk update, handles token, chunking, and mixed statuses."""
    effective_api_domain = api_domain or DEFAULT_API_DOMAIN

    # Validate statuses before starting
    invalid_statuses = {r['status'] for r in rows if r.get('status') not in VALID_STATUSES}
    if invalid_statuses:
        raise ValueError(f"Invalid target statuses found: {', '.join(invalid_statuses)}. Must be one of: {VALID_STATUSES}")

    # Get token using potentially overridden credentials
    token = get_access_token(client_id, client_secret, refresh_token, accounts_url)

    all_results: List[Dict] = []
    num_chunks = math.ceil(len(rows) / CHUNK_SIZE) or 1 # Ensure at least 1 chunk for progress calc
    logger.info(f"Starting bulk update for {len(rows)} records in {num_chunks} chunks...")

    for i, row_chunk in enumerate(chunked(rows, CHUNK_SIZE), 1):
        # Prepare payload for this chunk, ensuring 'id' and the field are present
        payload_chunk = []
        chunk_ids_for_logging = [] # Keep track for error reporting if needed
        for row in row_chunk:
            row_id = row.get("id")
            row_status = row.get("status")
            if row_id and row_status:
                 payload_chunk.append({"id": row_id, FIELD_TO_UPDATE: row_status})
                 chunk_ids_for_logging.append(row_id)
            else:
                 logger.warning(f"Skipping invalid row data in chunk {i}: {row}")
                 # Add an immediate failure result for this malformed row
                 all_results.append({
                    "id": row_id or "MISSING_ID",
                    "status": "error",
                    "code": "INVALID_INPUT_ROW",
                    "message": "Row missing 'id' or 'status' key.",
                    "details": {"original_row": row}
                 })

        if not payload_chunk:
             logger.warning(f"Skipping empty payload for chunk {i}.")
             if progress_hook: progress_hook(i) # Still advance progress
             continue

        logger.info(f"Processing chunk {i}/{num_chunks} ({len(payload_chunk)} valid records)...")
        chunk_results = _update_chunk(token, payload_chunk, api_domain=effective_api_domain)

        # Ensure results have IDs associated, especially if the chunk update failed generically
        processed_ids_in_chunk = {res.get('id') for res in chunk_results if res.get('id')}
        missing_ids_in_response = set(chunk_ids_for_logging) - processed_ids_in_chunk

        if missing_ids_in_response:
             logger.warning(f"IDs submitted in chunk {i} but missing from response: {missing_ids_in_response}")
             for missing_id in missing_ids_in_response:
                  # Find the first error message from the chunk response, if any
                  first_error = next((res for res in chunk_results if res.get('status') != 'success'), None)
                  error_code = first_error.get('code', 'MISSING_IN_RESPONSE') if first_error else 'MISSING_IN_RESPONSE'
                  error_message = first_error.get('message', 'Record ID not found in API response.') if first_error else 'Record ID not found in API response.'
                  all_results.append({
                      "id": missing_id, "status": "error",
                      "code": error_code, "message": error_message,
                      "details": {"info": "ID sent but no result returned by API for this chunk."}
                  })

        # Add results that *were* returned
        all_results.extend(chunk_results)

        if progress_hook:
            try:
                progress_hook(i) # Call the progress hook with the chunk number completed
            except Exception as e:
                 logger.error(f"Error in progress_hook for chunk {i}: {e}") # Log hook errors

    logger.info("Bulk update process completed.")
    return all_results