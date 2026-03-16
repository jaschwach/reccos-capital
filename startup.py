"""Initialize the database and launch gunicorn."""
import os
import subprocess
import sys

WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Change to the workspace root so main_app.py and templates are findable
os.chdir(WORKSPACE_ROOT)

from main_app import init_db
init_db()
print("Database initialized.")

port = int(os.environ.get('PORT', 8080))
subprocess.run([
    sys.executable, "-m", "gunicorn",
    "main_app:app",
    "--bind", f"0.0.0.0:{port}",
    "--workers", "2",
    "--timeout", "60",
    "--access-logfile", "-",
    "--chdir", WORKSPACE_ROOT,
], check=True)
