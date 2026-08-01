"""
Second-fund entry point.

Streamlit Community Cloud identifies an app by (repo, branch, main-file-path),
so two apps from the SAME repo+branch need DIFFERENT main files. This thin
wrapper runs the shared app (app.py) fresh on every rerun, so both funds share
one codebase — fix once, both update. The fund's identity (name, DB prefix,
Supabase, password) all come from THIS deployment's Streamlit secrets
(FUND_NAME / TABLE_PREFIX / SUPABASE_URL / SUPABASE_KEY / SCREENER_PASSWORD).

Deploy Fund B in Streamlit with the main file path set to `messi.py`.
"""
import os
import runpy

# run_path re-executes app.py on every Streamlit rerun (no module caching), so
# set_page_config stays the first Streamlit call and pages resolve from the repo
# root exactly as they do for the primary app.
runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"),
    run_name="__main__",
)
