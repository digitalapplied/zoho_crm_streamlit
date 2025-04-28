#!/usr/bin/env python3
"""
zoho_bulk.py
Shared helper used by both CLI and Streamlit UI.
"""

import json, logging, math, os, time
from typing import List, Dict

import requests
from dotenv import load_dotenv

# ---- config -----------------------------------------------------------------
load_dotenv()                               # pick up .env in cwd

CLIENT_ID       = os.getenv("ZOHO_CLIENT_ID")
CLIENT_SECRET   = os.getenv("ZOHO_CLIENT_SECRET")
REFRESH_TOKEN   = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN",   "https://www.zohoapis.com")
ZOHO_ACCOUNTS   = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com/oauth/v2/token")

MODULE_API_NAME = "Leads"
FIELD_TO_UPDATE = "Lead_Status"
CHUNK_SIZE      = 100
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

# ---- logging ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

# -----------------------------------------------------------------------------
def get_access_token() -> str:
    if not all((CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)):
        raise RuntimeError("Missing Zoho creds – set them in .env")
    r = requests.post(
        ZOHO_ACCOUNTS,
        data={
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT_SEC,
    )
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"Token refresh failed: {r.text}")
    return token


def _update_chunk(
    token: str, ids: List[str], new_value: str
) -> List[Dict]:
    url = f"{ZOHO_API_DOMAIN}/crm/v8/{MODULE_API_NAME}"
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    payload = {"data": [{"id": _id, FIELD_TO_UPDATE: new_value} for _id in ids]}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.put(url, headers=headers, json=payload, timeout=TIMEOUT_SEC)

            if r.status_code == 429 or r.status_code >= 500:
                wait = BACKOFF_SEC * 2 ** (attempt - 1)
                logging.warning(
                    "API %s on chunk attempt %s/%s – backing off %.1fs",
                    r.status_code, attempt, MAX_RETRIES, wait
                )
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.json().get("data", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed on attempt {attempt}: {e}")
            if attempt == MAX_RETRIES:
                # Return error status for all IDs in the chunk if max retries are exceeded after a request exception
                 return [
                    {
                        "id": _id,
                        "status": "error",
                        "code": "REQUEST_FAILED",
                        "message": f"Request failed after {MAX_RETRIES} attempts: {e}",
                    }
                    for _id in ids
                ]
            wait = BACKOFF_SEC * 2 ** (attempt - 1)
            logging.warning(f"Backing off {wait:.1f}s due to request failure.")
            time.sleep(wait)

    # ran out of retries (should only happen if all attempts resulted in 429/5xx)
    return [
        {
            "id": _id,
            "status": "error",
            "code": "FAILED_RETRIES",
            "message": f"Gave up after {MAX_RETRIES} retries (last status code: {r.status_code if 'r' in locals() else 'N/A'})",
        }
        for _id in ids
    ]


def bulk_update(ids: List[str], new_status: str) -> List[Dict]:
    """Return list of result dicts – one per ID."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"{new_status!r} not in VALID_STATUSES")

    token = get_access_token()
    all_results: List[Dict] = []

    num_chunks = math.ceil(len(ids) / CHUNK_SIZE)
    logging.info(f"Processing {len(ids)} IDs in {num_chunks} chunks of {CHUNK_SIZE}...")

    for i, n in enumerate(range(0, len(ids), CHUNK_SIZE)):
        chunk = ids[n : n + CHUNK_SIZE]
        logging.info(f"Updating chunk {i+1}/{num_chunks} ({len(chunk)} IDs)...")
        all_results.extend(_update_chunk(token, chunk, new_status))

    logging.info("Bulk update process complete.")
    return all_results
