Zoho CRM Lead-Status Bulk Updater v3.1
=====================================

This project provides a Streamlit-based web UI and helper scripts for bulk updating lead statuses in Zoho CRM via the Zoho API. It is intended for users who need to efficiently update the status of multiple leads at once, using their Zoho OAuth credentials.

---

Features
--------
- **Bulk Update:** Update the status of multiple Zoho CRM leads in one go.
- **Flexible ID Input:**
    - Paste IDs directly.
    - Upload `.txt` file (one ID per line).
    - Upload `.csv` file (single `id` column OR `id` and `status` columns for **mixed-status updates**).
    - **Fetch IDs directly** from a Zoho Custom View (CV) ID, including multi-page views.
- **Streamlit UI:** Simple web interface for loading lead IDs, selecting target status (or using CSV status), and executing updates.
- **Credential Management:**
    - Uses `.env` file for storing Zoho OAuth credentials locally (template provided).
    - Allows **temporary override** of credentials via the UI sidebar for the current session.
- **Progress & Results:** Displays update progress and detailed results (success/failure) with downloadable failure logs.
- **Field Metadata:** Option to view and download the available API field names for the Leads module.
- **Logging:** Records operations and potential issues to `zoho_bulk.log`.
- **Supports Multiple Regions:** Optional environment variables allow for EU or other Zoho domains.

---

Files
-----
- `streamlit_app.py` — Main Streamlit web app. Run with `streamlit run streamlit_app.py`.
- `zoho_bulk.py` — Core logic for authentication, API calls (bulk update, CV fetch, field metadata), and helper functions.
- `.env.template` — Example environment file. Copy to `.env` and fill in your Zoho credentials.
- `requirements.txt` — Python dependencies for this project.
- `README.txt` — This file.
- `.gitignore` — Recommended ignores for Python and environment files.

---

Setup
-----
1. **Clone/Download:** Get the project files.
2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
3. **Configure environment:**
   - Copy `.env.template` to `.env`.
   - Fill in your Zoho credentials in `.env`:
     - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`
   - (Optional) Adjust `ZOHO_API_DOMAIN` and `ZOHO_ACCOUNTS_URL` in `.env` for your Zoho region.
4. **Run the app:**
   ```sh
   streamlit run streamlit_app.py
   ```

---

Usage
-----
1.  **(Optional) Override Credentials:** Use the sidebar expander if you need to use different API keys than those in your `.env` for this session only.
2.  **Select Default Status:** Choose the target status in the sidebar. This is used *only* if you paste IDs or upload a single-column file.
3.  **Load Lead IDs:** Use *one* of the methods in the sidebar:
    *   **Upload File:** Select a `.txt` or `.csv` file.
        *   A `.txt` file or single-column `.csv` uses the default status selected above.
        *   A 2-column `.csv` with headers `id` and `status` will perform a **mixed-status update**, ignoring the default selection.
    *   **Fetch IDs from CV:** Enter a numeric Custom View ID from Zoho and click fetch.
    *   **(Manual) Paste IDs:** Paste IDs directly into the main text area.
4.  **Review:** Check the IDs/rows listed in the main text area. *Editing the text area manually will disable mixed-status mode if it was active from a CSV upload.*
5.  **Execute:** Click the **Update Records** button, review the confirmation prompt, and click **Confirm & Proceed**.
6.  **View Results:** Check the summary counts and the detailed table. Download any failed rows using the provided button.
7.  **(Optional) View Fields:** Click the button at the bottom to fetch and display/download the API names for fields in the Leads module.

---

Security
--------
- **Do not commit your `.env` file** containing secrets to version control. The `.gitignore` file is set up to help prevent this.
- Use Streamlit's built-in security features if deploying publicly.
- Sidebar credential overrides are *not* saved and only last for the browser session.

---

Support
-------
For questions or issues, please open an issue on the project repository or contact the maintainer.
