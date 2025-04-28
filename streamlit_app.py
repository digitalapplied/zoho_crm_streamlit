#!/usr/bin/env python3
"""
streamlit_app.py  ·  v3 Final
Streamlit UI for Zoho Lead-Status Bulk Updater.
Includes: credential override, CV fetch (all pages), mixed-status CSV upload,
          field list display/download, progress bar, better state handling.
"""

import logging, textwrap, io, math
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Try importing zoho_bulk, handle potential ImportError
try:
    from zoho_bulk import (
        VALID_STATUSES, bulk_update, fetch_leads_by_cvid, get_module_fields,
        get_access_token, CHUNK_SIZE, # Need access token func directly now
        DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_REFRESH_TOKEN,
        DEFAULT_API_DOMAIN, DEFAULT_ACCOUNTS_URL, MODULE_API_NAME,
        FIELD_TO_UPDATE # <-- Add import here
    )
except ImportError as import_err:
    st.error(f"""
        **Fatal Error:** Could not import the `zoho_bulk.py` helper file.

        Please ensure `zoho_bulk.py` exists in the same directory as this script (`streamlit_app.py`).

        *Details: {import_err}*
        """)
    st.stop() # Stop execution if the core logic module is missing

# ----- page config -----------------------------------------------------------
st.set_page_config(page_title="Zoho Lead Updater", page_icon="🛠️", layout="wide")
load_dotenv()

# ----- Initialize Session State ---------------------------------------------
# Use more descriptive keys and provide defaults from zoho_bulk
default_creds = {
    'client_id': DEFAULT_CLIENT_ID, 'client_secret': DEFAULT_CLIENT_SECRET,
    'refresh_token': DEFAULT_REFRESH_TOKEN, 'api_domain': DEFAULT_API_DOMAIN,
    'accounts_url': DEFAULT_ACCOUNTS_URL
}
for key, default in default_creds.items():
    st.session_state.setdefault(f'cred_{key}', default or "") # Store even if None from env

st.session_state.setdefault('ids_text_area', "")
st.session_state.setdefault('lead_fields_df', None)
st.session_state.setdefault('mixed_status_data', []) # To store data from 2-column CSV

# ----- helpers ---------------------------------------------------------------
def parse_ids(text: str) -> list[str]:
    """Extracts unique, numeric-only IDs from a string block."""
    parsed = []
    ignored_count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            parsed.append(stripped)
        elif stripped:
            ignored_count += 1
            logging.warning(f"Ignoring non-numeric line: {stripped!r}")
    if ignored_count > 0:
         st.toast(f"Ignored {ignored_count} non-numeric/blank lines.", icon="⚠️")

    unique_ids = sorted(list(set(parsed)))
    if len(parsed) > len(unique_ids):
        logging.info(f"Removed {len(parsed) - len(unique_ids)} duplicate IDs.")
        st.toast(f"Removed {len(parsed) - len(unique_ids)} duplicate IDs.", icon="ℹ️")
    return unique_ids

def style_summary(ok: int, bad: int):
    color_ok = "#28a745" # Green
    color_bad = "#dc3545" # Red
    style = "font-size: 1.2rem; font-weight: bold; margin-bottom: 1rem; padding: 8px; border-radius: 5px;"
    summary_html = f"""
    <div style="{style}">
        <span style='color:{color_ok};'>✅ {ok} Succeeded</span>   |  
        <span style='color:{color_bad};'>❌ {bad} Failed</span>
    </div>
    """
    return summary_html

def get_effective_credentials():
    """Returns credentials dict, prioritizing sidebar inputs over .env defaults."""
    creds = {
        "client_id": st.session_state.cred_client_id or DEFAULT_CLIENT_ID,
        "client_secret": st.session_state.cred_client_secret or DEFAULT_CLIENT_SECRET,
        "refresh_token": st.session_state.cred_refresh_token or DEFAULT_REFRESH_TOKEN,
        "accounts_url": st.session_state.cred_accounts_url or DEFAULT_ACCOUNTS_URL,
        "api_domain": st.session_state.cred_api_domain or DEFAULT_API_DOMAIN
    }
    # Perform basic check
    if not all([creds['client_id'], creds['client_secret'], creds['refresh_token']]):
        st.error("Missing required Zoho Credentials. Please check the sidebar override or your `.env` file.")
        return None
    return creds

# ----- sidebar: Settings & Credentials ---------------------------------------
with st.sidebar:
    # Placeholder for logo - replace URL if needed
    st.image("https://digitalapplied.com/wp-content/uploads/2023/11/DigitalApplied-Logo-Stacked-White-Orange-e1701103297549.png", width=150)
    st.title("⚙️ Settings")

    with st.expander("Zoho API Credentials (Optional Override)", expanded=False):
        st.caption("Leave blank to use `.env` file values.")
        # Use text_input for client_id as it's not typically secret
        st.text_input("Client ID", key="cred_client_id", placeholder=f"Using .env value..." if DEFAULT_CLIENT_ID else "Enter Client ID")
        # Use password type for secret and token
        st.text_input("Client Secret", type="password", key="cred_client_secret", placeholder="Enter Client Secret to override")
        st.text_input("Refresh Token", type="password", key="cred_refresh_token", placeholder="Enter Refresh Token to override")
        st.text_input("API Domain", key="cred_api_domain", help="e.g., https://www.zohoapis.eu")
        st.text_input("Accounts URL", key="cred_accounts_url", help="e.g., https://accounts.zoho.eu/oauth/v2/token")
        st.caption("Overrides apply to this session only.")

    st.divider()
    st.header("🎯 1. Select Target Status")
    st.caption("*(Only used if IDs are pasted/uploaded without a 'status' column)*")
    target_status_default = st.selectbox(
        "Default Lead Status:",
        VALID_STATUSES,
        index=VALID_STATUSES.index("Junk Lead") if "Junk Lead" in VALID_STATUSES else 0,
        key='target_status_selectbox'
    )

    st.divider()
    st.header("📋 2. Load Lead IDs")
    upload_col, fetch_col = st.columns(2)

    with upload_col:
        uploaded_file = st.file_uploader(
            "Upload File",
            type=["txt", "csv"],
            accept_multiple_files=False,
            help="Upload `.txt` (one ID per line) or `.csv`. CSV can have `id` column, or `id` and `status` columns."
        )

    with fetch_col:
        cvid_input = st.text_input("Custom View ID", placeholder="e.g., 164...", help="Numeric ID from Zoho CRM URL.")
        fetch_all_pages = st.checkbox("Fetch all pages", value=True, help="Check this if your Custom View has > 200 records.")
        fetch_btn = st.button("Fetch IDs from CV", disabled=not cvid_input.strip().isdigit())

    # --- Logic to handle ID loading and potential mixed-status input ---
    ids_loaded_source = None
    mixed_status_mode = False

    # Process file upload immediately if available
    if uploaded_file is not None:
        ids_loaded_source = f"file '{uploaded_file.name}'"
        try:
            content_bytes = uploaded_file.read()
            content_str = content_bytes.decode("utf-8")

            if uploaded_file.name.lower().endswith(".csv"):
                try:
                    csv_data = io.StringIO(content_str)
                    df_in = pd.read_csv(csv_data)
                    df_in.columns = [col.strip().lower() for col in df_in.columns]

                    if {"id", "status"} <= set(df_in.columns):
                        df_in['id'] = df_in['id'].astype(str).str.strip()
                        df_in = df_in[df_in['id'].str.isdigit()]
                        df_in['status'] = df_in['status'].astype(str).str.strip()

                        invalid_statuses_df = df_in[~df_in['status'].isin(VALID_STATUSES)]
                        if not invalid_statuses_df.empty:
                            invalid_list = invalid_statuses_df['status'].unique().tolist()
                            st.error(f"Invalid statuses in CSV (rows ignored): {', '.join(invalid_list)}")
                            df_in = df_in[df_in['status'].isin(VALID_STATUSES)]

                        if not df_in.empty:
                            st.session_state['mixed_status_data'] = df_in[['id', 'status']].to_dict('records')
                            st.session_state['ids_text_area'] = "" # Clear text area
                            mixed_status_mode = True
                            st.success(f"Loaded {len(st.session_state['mixed_status_data'])} valid rows from CSV for mixed-status update.")
                        else:
                            st.warning("No valid rows found in the CSV after validation.")
                            st.session_state['mixed_status_data'] = []
                            st.session_state['ids_text_area'] = content_str # Show original content if parse failed badly
                    else:
                        st.warning("CSV found, but 'id' and 'status' columns not detected. Treating as a list of IDs.")
                        st.session_state['ids_text_area'] = content_str
                        st.session_state['mixed_status_data'] = []
                        st.success(f"Loaded IDs from '{uploaded_file.name}'. Edit below.")
                except pd.errors.EmptyDataError:
                    st.warning("Uploaded CSV file is empty.")
                    st.session_state['ids_text_area'] = ""
                    st.session_state['mixed_status_data'] = []
                except Exception as e:
                    st.error(f"Error parsing CSV file: {e}. Treating as single-column ID list.")
                    logging.exception("Error parsing uploaded CSV")
                    st.session_state['ids_text_area'] = content_str # Fallback
                    st.session_state['mixed_status_data'] = []
            else:
                # Treat as single-column TXT
                st.session_state['ids_text_area'] = content_str
                st.session_state['mixed_status_data'] = []
                st.success(f"Loaded IDs from '{uploaded_file.name}'. Edit below.")

        except Exception as e:
            st.error(f"Error reading uploaded file: {e}")
            logging.exception("Error reading uploaded file")
            st.session_state['ids_text_area'] = ""
            st.session_state['mixed_status_data'] = []
        # Reset file uploader state to allow re-uploading the same file
        # This often requires using the 'key' argument and manually resetting, which can be tricky.
        # For simplicity, we let the text area be the source of truth after an upload.

    # Handle fetch button AFTER potentially processing an upload in the same run
    if fetch_btn:
        if cvid_input and cvid_input.strip().isdigit():
            ids_loaded_source = f"Custom View ID {cvid_input}"
            try:
                effective_creds = get_effective_credentials()
                if not effective_creds: st.stop()

                with st.spinner(f"Fetching leads from CV {cvid_input} (All pages: {fetch_all_pages})..."):
                    # Filter creds for token fetch
                    token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                    token = get_access_token(**token_creds)
                    fetched_leads = fetch_leads_by_cvid(
                        token, cvid_input.strip(),
                        api_domain=effective_creds['api_domain'],
                        fetch_all=fetch_all_pages
                    )

                if fetched_leads:
                    fetched_ids = [str(lead['id']) for lead in fetched_leads if 'id' in lead and str(lead['id']).isdigit()]
                    valid_fetched_ids = sorted(list(set(fetched_ids))) # Ensure unique and sorted
                    st.session_state['ids_text_area'] = "\n".join(valid_fetched_ids)
                    st.session_state['mixed_status_data'] = [] # Clear mixed mode
                    st.success(f"Fetched {len(valid_fetched_ids)} valid Lead IDs. Loaded into text area.")
                    st.rerun() # Force UI update for text area
                else:
                    st.warning("No leads found in that Custom View or no valid IDs extracted.")
            except Exception as e:
                st.error(f"Error fetching from Custom View: {e}")
                logging.exception("Error fetching leads by CV ID")
        else:
             st.error("Invalid Custom View ID entered.")

# ----- main Area: Review & Execute ------------------------------------------
st.header("📄 3. Review IDs & Execute")

# Determine final list and mode based on state AFTER potential loads/fetches
if st.session_state.get('mixed_status_data'):
    rows_to_process = st.session_state['mixed_status_data']
    processing_mode_message = f"{len(rows_to_process)} rows from CSV (using per-row status)"
    st.info(f"Processing **{len(rows_to_process)}** rows from the uploaded **mixed-status CSV**. Sidebar status selection is ignored.")
    # Display the mixed data for review
    st.dataframe(pd.DataFrame(rows_to_process), height=300, use_container_width=True)
else:
    # Use the text area as the source of truth if not in mixed mode
    ids_text_display = st.text_area(
        "Lead IDs to Update (one per line):",
        value=st.session_state.get('ids_text_area', ""),
        height=300,
        placeholder="Paste IDs here OR IDs from file/fetch will appear here...",
        key='ids_text_area_widget_main', # Unique key
        help="Review/edit the final list of IDs. Blank/non-numeric lines are ignored."
    )
    # Update state if manually edited
    if ids_text_display != st.session_state.get('ids_text_area', ""):
        st.session_state['ids_text_area'] = ids_text_display
        st.session_state['mixed_status_data'] = [] # Ensure mixed mode is off
        st.rerun() # Rerun to update counts based on edit

    ids_final = parse_ids(st.session_state['ids_text_area'])
    rows_to_process = [{"id": i, "status": target_status_default} for i in ids_final]
    processing_mode_message = f"{len(ids_final)} IDs from text area (target status: '{target_status_default}')"


col1_main, col2_main = st.columns([3, 1])
with col1_main:
     if not st.session_state.get('mixed_status_data'): # Only show caption if not in mixed mode
        st.caption(f"Ready to process: **{processing_mode_message}**")
with col2_main:
    run_update_btn = st.button(
        f"🚀 Update {len(rows_to_process)} Records",
        disabled=not rows_to_process,
        type="primary",
        use_container_width=True,
        key="run_update_main_btn"
    )

# Confirmation dialog simulation using session state
if run_update_btn:
    if not rows_to_process:
         st.warning("No valid IDs or rows to process.")
    else:
        st.session_state['confirm_pending'] = True
        st.rerun() # Rerun to show confirmation buttons

if st.session_state.get('confirm_pending', False):
    st.warning(f"You are about to update **{len(rows_to_process)}** records. This action cannot be undone easily.", icon="⚠️")
    confirm_col1, confirm_col2, _ = st.columns([1, 1, 3]) # Add spacer column
    if confirm_col1.button("Confirm & Proceed", type="primary", key="confirm_yes"):
        st.session_state['confirm_pending'] = False
        st.session_state['execute_update'] = True
        st.rerun()
    if confirm_col2.button("Cancel", key="confirm_no"):
        st.session_state['confirm_pending'] = False
        st.info("Update cancelled.")
        st.rerun()

# ----- Execution Block (runs after confirmation) -----------------------------
if st.session_state.get('execute_update', False):
    # Reset the flag immediately to prevent re-execution on rerun
    st.session_state['execute_update'] = False

    st.header("📊 Update Results")
    st.info(f"Processing {len(rows_to_process)} records...")
    prog_container = st.empty() # Placeholder for progress bar + text
    prog_container.progress(0, text="Initiating update...")
    start_time = datetime.now()

    # Define progress hook using a mutable dictionary
    progress_state = {'processed_chunks': 0}
    total_chunks = math.ceil(len(rows_to_process) / CHUNK_SIZE) or 1

    def progress_hook(chunk_num):
         progress_state['processed_chunks'] = chunk_num
         progress = min(1.0, progress_state['processed_chunks'] / total_chunks) # Ensure progress doesn't exceed 1.0
         prog_container.progress(progress, text=f"Processing chunk {progress_state['processed_chunks']}/{total_chunks}...")

    try:
        effective_creds = get_effective_credentials()
        if not effective_creds: st.stop()

        # Filter creds for token fetch - needed if bulk_update doesn't handle it
        # Although bulk_update calls get_access_token itself, passing only necessary args is safer
        token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
        # Note: The current bulk_update function re-fetches the token internally.
        # This filtering might be redundant if bulk_update is robust, but belt-and-suspenders approach.

        results = bulk_update(rows_to_process, progress_hook=progress_hook, **effective_creds)
        prog_container.progress(1.0, text="Update process complete!")
    except Exception as exc:
        st.error(f"Critical Failure during bulk update initiation or processing: {exc}")
        logging.exception("Bulk update process failed critically")
        prog_container.empty()
        st.stop()

    end_time = datetime.now()
    duration = end_time - start_time
    st.caption(f"Total processing time: {duration}")

    # Results processing
    if results:
        df = pd.DataFrame(results)
        required_cols = ["id", "status", "code", "message", "details"]
        for col in required_cols:
            if col not in df.columns: df[col] = None

        # Attempt to extract ID from details if primary 'id' is missing (for error reporting)
        def get_id_from_row(row):
            primary_id = row.get('id')
            if pd.notna(primary_id) and primary_id != 'UNKNOWN_ID_IN_CHUNK': return str(primary_id)
            details_dict = row.get('details')
            if isinstance(details_dict, dict): return str(details_dict.get('id', 'UNKNOWN'))
            return 'UNKNOWN'

        df['display_id'] = df.apply(get_id_from_row, axis=1)
        # Reorder for display, keeping original 'id' if needed for debugging
        display_cols = ['display_id', 'status', 'code', 'message', 'details']
        df_display = df[display_cols]


        ok_df = df[df["status"] == "success"]
        bad_df = df[df["status"] != "success"]
        ok_count, bad_count = len(ok_df), len(bad_df)

        st.markdown(style_summary(ok_count, bad_count), unsafe_allow_html=True)
        st.dataframe(df_display, use_container_width=True, height=300) # Display user-friendly table

        if not bad_df.empty:
            try:
                # Include details in the failure CSV
                csv_fail = bad_df.to_csv(index=False).encode('utf-8')
                ts_fail  = datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")
                st.download_button(
                    label=f"Download {bad_count} failed rows as CSV",
                    data=csv_fail,
                    file_name=f"failed_zoho_updates_{ts_fail}.csv",
                    mime="text/csv",
                    key="download_fail_btn"
                )
            except Exception as e:
                st.error(f"Could not generate failure download file: {e}")
        elif ok_count > 0:
            st.success("All submitted records processed successfully!")
        else:
            st.warning("No records succeeded. Check results table/logs.")
    else:
        st.warning("No results returned from the update process. Check logs.")

st.divider()
# ----- Fetch Fields Section --------------------------------------------------
st.header("📚 View Lead Field Names (Optional)")
fetch_fields_btn = st.button("Show Available Lead Fields", key="fetch_fields")

if fetch_fields_btn:
     if st.session_state.get('lead_fields_df') is not None:
          st.caption("Using cached field data.")
          st.dataframe(st.session_state['lead_fields_df'], use_container_width=True, height=500)
          st.download_button("Download Fields as CSV",
                           st.session_state['lead_fields_df'].to_csv(index=False).encode('utf-8'),
                           f"{MODULE_API_NAME}_fields.csv", "text/csv", key="dl_fields_cached")
     else:
        try:
            effective_creds = get_effective_credentials()
            if not effective_creds: st.stop()

            with st.spinner(f"Fetching fields for {MODULE_API_NAME} module..."):
                # Filter creds for token fetch
                token_creds = {k: v for k, v in effective_creds.items() if k in ['client_id', 'client_secret', 'refresh_token', 'accounts_url']}
                token = get_access_token(**token_creds)
                fields_data = get_module_fields(token, module=MODULE_API_NAME, api_domain=effective_creds['api_domain'])

            if fields_data:
                # Select and sort columns for better readability
                fields_df = pd.DataFrame(fields_data)[['api_name', 'field_label', 'data_type']].sort_values('field_label')
                st.session_state['lead_fields_df'] = fields_df # Cache it
                st.dataframe(fields_df, use_container_width=True, height=500)
                st.success(f"Fetched {len(fields_df)} fields for the {MODULE_API_NAME} module.")
                st.download_button("Download Fields as CSV",
                           fields_df.to_csv(index=False).encode('utf-8'),
                           f"{MODULE_API_NAME}_fields.csv", "text/csv", key="dl_fields_new")
            else:
                st.warning("No field data returned from Zoho API.")
        except Exception as e:
            st.error(f"Error fetching fields: {e}")
            logging.exception("Error fetching module fields")

# ----- Footer ----------------------------------------------------------------
st.divider()
with st.expander("ℹ️  Help & About"):
    st.markdown(textwrap.dedent(f"""
        **Zoho CRM Lead Status Bulk Updater v3.1**

        Updates the '{FIELD_TO_UPDATE}' field for records in the '{MODULE_API_NAME}' module.

        **How to Use:**
        1.  **(Optional) Credentials:** Use the sidebar expander to temporarily override `.env` credentials.
        2.  **Target Status:** Select default status (sidebar). Used *unless* a 2-column CSV (`id`,`status`) is uploaded.
        3.  **Load IDs:** Use *one* sidebar method: Upload File, Fetch from CV, or Paste into main text area.
        4.  **Review:** Check/edit the final list in the main text area or review the mixed-status data table.
        5.  **Execute:** Click **Update**, then **Confirm Update**.
        6.  **Results:** View summary & table. Download failures if any.
        7.  **(Optional) Fields:** View/download '{MODULE_API_NAME}' fields.

        **Security:** Use `.env` or Streamlit Secrets. Sidebar overrides are temporary.
        **Logging:** Check `zoho_bulk.log`.
        """))