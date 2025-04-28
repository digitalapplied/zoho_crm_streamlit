#!/usr/bin/env python3
"""
Streamlit UI for Zoho Lead-Status Bulk Updater
Run with:
    streamlit run streamlit_app.py
"""

import io, textwrap, logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Try importing zoho_bulk, handle potential ImportError
try:
    from zoho_bulk import VALID_STATUSES, bulk_update
except ImportError:
    st.error("Could not import `zoho_bulk.py`. Make sure it's in the same folder as `streamlit_app.py`.")
    st.stop() # Stop execution if module not found

# ----- page config -----------------------------------------------------------
st.set_page_config(page_title="Zoho Lead-Status Updater", page_icon="🛠️", layout="centered")
load_dotenv()                    # allow .env in same folder even when deployed

# ----- helpers ---------------------------------------------------------------
def parse_ids(text: str) -> list[str]:
    """Extracts unique, numeric-only IDs from a string block."""
    parsed = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            parsed.append(stripped)
        elif stripped: # Log non-numeric lines if they are not empty
            logging.warning(f"Ignoring non-numeric line: {stripped!r}")
    return sorted(list(set(parsed))) # Ensure uniqueness and sort

def style_summary(ok: int, bad: int):
    return f"""
    <div style="font-size:1.2rem; margin-bottom: 1rem;">
        ✅ <b>{ok}</b> succeeded &nbsp;&nbsp;|&nbsp;&nbsp; ❌ <b>{bad}</b> failed
    </div>
    """

# ----- sidebar ---------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Settings")
    target_status = st.selectbox("Select new Lead Status", VALID_STATUSES)
    st.markdown("---")
    uploaded_file = st.file_uploader(
        "Upload a .txt / .csv with one ID per line (optional)",
        type=["txt", "csv"],
        accept_multiple_files=False,
        help="File should contain one numeric Zoho Lead ID per line. Header rows or non-numeric lines will be ignored."
    )
    st.markdown("or paste IDs below ⬇️")

# ----- main ------------------------------------------------------------------
st.title("🛠️ Zoho Lead-Status Bulk Updater")

# State management for IDs
if 'ids_list' not in st.session_state:
    st.session_state['ids_list'] = []
if 'ids_text_area' not in st.session_state:
    st.session_state['ids_text_area'] = ""

# Handle file upload
if uploaded_file is not None:
    # Read file content
    try:
        content_bytes = uploaded_file.read()
        content_str = content_bytes.decode("utf-8")
        # Use the text area to display file content and allow editing
        st.session_state['ids_text_area'] = content_str
        # Important: Reset uploader to allow re-uploading the same file after modification
        # This requires a unique key based on the file, but Streamlit's file_uploader doesn't easily support this.
        # A simpler approach for now is just letting the text area be the source of truth after upload.
        st.success(f"Loaded {len(parse_ids(content_str))} IDs from '{uploaded_file.name}'. You can edit them below.")
    except Exception as e:
        st.error(f"Error reading file: {e}")

# Multi-line text input for pasted/edited IDs
ids_text = st.text_area(
    "Lead IDs (one per line):",
    value=st.session_state['ids_text_area'],
    height=200,
    placeholder="1649349000123456789\n1649349000987654321",
    key='ids_text_area', # Use the key to manage state
    help="Paste numeric Zoho Lead IDs here, one per line. Blank lines or non-numeric lines are ignored."
)

# Parse IDs from the text area (which might contain pasted or file content)
ids = parse_ids(ids_text)

st.caption(f"Detected {len(ids)} unique numeric IDs.")

run_btn = st.button(
    f"Update {len(ids)} leads to “{target_status}”",
    disabled=len(ids) == 0,
    type="primary",
)

# ----- execution & results ---------------------------------------------------
if run_btn:
    st.info(f"Starting update for {len(ids)} leads to status '{target_status}'...")
    progress_bar = st.progress(0, text="Initiating update...")
    start_time = datetime.now()

    try:
        # Note: bulk_update handles chunking and retries internally.
        # We don't need progress updates within the loop here unless zoho_bulk is modified
        # to yield progress.
        results = bulk_update(ids, target_status)
        progress_bar.progress(1.0, text="Update complete!")
    except Exception as exc:
        st.error(f"Critical Failure during bulk update: {exc}")
        logging.exception("Bulk update failed") # Log the full traceback
        st.stop()

    end_time = datetime.now()
    duration = end_time - start_time
    st.caption(f"Total processing time: {duration}")

    # Results dataframe processing
    if results:
        df = pd.DataFrame(results)
        # Ensure essential columns exist, even if API returns unexpected data
        for col in ["id", "status", "code", "message"]:
             if col not in df.columns:
                 df[col] = "N/A"
        df = df[["id", "status", "code", "message"]] # Reorder/select columns

        ok = df[df.status == "success"]
        bad = df[df.status != "success"]

        st.markdown(style_summary(len(ok), len(bad)), unsafe_allow_html=True)

        st.dataframe(df, use_container_width=True)

        # download failures
        if not bad.empty:
            try:
                csv = bad.to_csv(index=False).encode('utf-8')
                ts  = datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")
                st.download_button(
                    label=f"Download {len(bad)} failed IDs as CSV",
                    data=csv,
                    file_name=f"failed_zoho_updates_{target_status.replace(' ', '_')}_{ts}.csv",
                    mime="text/csv",
                )
            except Exception as e:
                st.error(f"Could not generate download file: {e}")
        elif len(ok) > 0:
             st.success("All records updated successfully!")
        else:
            st.warning("No records were processed or all failed. Check results table.")

    else:
        st.warning("No results returned from the update process.")


# ----- footer ----------------------------------------------------------------
with st.expander("ℹ️  How this works"):
    st.markdown(
        textwrap.dedent(
            """
            *   Uses your Zoho OAuth refresh-token (stored in a local **.env** file or Streamlit **Secrets** when deployed) to obtain a short-lived access token for API calls.
            *   Sends updates to the Zoho CRM API in chunks (default 100 IDs per request) for efficiency.
            *   Includes automatic retries with exponential back-off for common transient API issues (like rate limits - 429 errors, or server errors - 5xx).
            *   Displays a detailed table showing the outcome for each Lead ID submitted.
            *   Allows downloading a CSV file containing only the IDs that failed, making it easy to retry them later.
            *   The core API interaction logic is in `zoho_bulk.py`, which could potentially be reused in other scripts or tools.
            """
        )
    )

# Add a clear instruction about the .env file
st.sidebar.markdown("--- ")
st.sidebar.info("**Important:** Ensure your Zoho API credentials are correctly set in the `.env` file in the same directory as this app, or in Streamlit Cloud Secrets if deployed.")
