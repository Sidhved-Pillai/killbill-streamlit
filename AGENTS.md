# KillBill contributor instructions

These rules apply to every change made locally or through Codex Cloud.

## Safety and scope

- Preserve the existing freight lookup, dated freight revision, customer-code matching, short-address replacement, duplicate detection, case/jar classification, billing statement, and Excel export behavior unless the user explicitly requests a change to that rule.
- Never print, commit, copy, or replace `GOOGLE_API_KEY`, Streamlit secrets, credentials, invoice images, or customer data.
- Do not make live Gemini API calls unless the user explicitly requests a live test. Automated tests must mock Gemini so API credits are not consumed.
- Do not alter or regenerate the customer/freight master data unless the task explicitly requires it.
- Keep invoice extraction requests independent even when they run concurrently.
- Do not push directly to `main` from a cloud task unless the user explicitly asks. Prefer a branch and pull request so changes can be reviewed from the phone before deployment.

## Required validation

Before handing off any code change, run:

```bash
python -m pytest -q
python -m py_compile app.py
```

For changes that affect Streamlit UI or startup, also run:

```bash
python - <<'PY'
from streamlit.testing.v1 import AppTest
app = AppTest.from_file("app.py", default_timeout=20).run()
assert not app.exception, app.exception
print("Streamlit startup passed")
PY
```

Report the commands run and their outcomes. Do not claim completion when tests fail.

## Cloud environment setup

Use Python 3.11 or newer. Install the application and test dependencies with:

```bash
python -m pip install -r requirements.txt pytest
```

The test suite does not require a Gemini key. Only the deployed Streamlit app needs `GOOGLE_API_KEY` in Streamlit secrets.

