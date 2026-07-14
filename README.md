# KillBill Streamlit App

A Streamlit app for uploading Bisleri invoices, extracting logistics billing rows, and exporting cleaned CSV data.

## Local setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your Google API key:
   - macOS/Linux:
     ```bash
     export GOOGLE_API_KEY="your_api_key_here"
     ```
   - Or use Streamlit secrets with `.streamlit/secrets.toml`:
     ```toml
     GOOGLE_API_KEY = "your_api_key_here"
     ```
4. Run the app:
   ```bash
   streamlit run app.py --server.port 8502
   ```

## Deployment

The app is ready for deployment to public hosting platforms such as Streamlit Cloud, Render, or any service that can run Python apps.

### Streamlit Cloud

1. Push this repo to GitHub.
2. Create a new Streamlit Cloud app and connect it to the GitHub repo.
3. Add `GOOGLE_API_KEY` as a secret in the app settings.
4. Deploy and share the generated public URL.

### Render

1. Push this repo to GitHub.
2. Create a new Web Service on Render.
3. Use `pip install -r requirements.txt` as the build command.
4. Use `streamlit run app.py --server.port $PORT` as the start command.
5. Add `GOOGLE_API_KEY` as an environment variable.

## Notes

- The app now reads `GOOGLE_API_KEY` from the environment or Streamlit secrets.
- Do not commit your real API key to source control.
