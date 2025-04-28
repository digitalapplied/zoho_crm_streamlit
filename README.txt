Zoho CRM Lead-Status Bulk Updater
=================================

This project provides a Streamlit-based web UI and helper scripts for bulk updating lead statuses in Zoho CRM via the Zoho API. It is intended for users who need to efficiently update the status of multiple leads at once, using their Zoho OAuth credentials.

---

Features
--------
- **Bulk Update:** Update the status of multiple Zoho CRM leads in one go.
- **Streamlit UI:** Simple web interface for uploading lists of lead IDs and selecting the target status.
- **Secure Credentials:** Uses `.env` file for storing Zoho OAuth credentials locally (template provided).
- **Logging and Feedback:** Displays update results and logs non-numeric or duplicate IDs.
- **Supports Multiple Regions:** Optional environment variables allow for EU or other Zoho domains.

---

Files
-----
- `streamlit_app.py` — Main Streamlit web app. Run with `streamlit run streamlit_app.py`.
- `zoho_bulk.py` — Core logic for authenticating with Zoho and performing bulk updates.
- `.env.template` — Example environment file. Copy to `.env` and fill in your Zoho credentials.
- `requirements.txt` — Python dependencies for this project.
- `.gitignore` — Recommended ignores for Python and environment files.

---

Setup
-----
1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
2. **Configure environment:**
   - Copy `.env.template` to `.env` and fill in your Zoho credentials:
     - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`
   - (Optional) Adjust `ZOHO_API_DOMAIN` and `ZOHO_ACCOUNTS_URL` for your Zoho region.
3. **Run the app:**
   ```sh
   streamlit run streamlit_app.py
   ```

---

Usage
-----
- Use the sidebar to select the new lead status.
- Paste or upload a list of numeric Zoho Lead IDs.
- Click the button to perform the bulk update.
- Results and errors will be displayed in the app.

---

Security
--------
- **Do not commit your `.env` file** containing secrets to version control. The `.gitignore` file is set up to help prevent this.

---

Support
-------
For questions or issues, please open an issue or contact the project maintainer.
