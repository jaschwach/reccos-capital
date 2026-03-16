"""Run on first boot to initialize the database, then hand off to gunicorn."""
import subprocess
import sys

from main_app import init_db
init_db()
print("Database initialized.")

port = 8080
subprocess.run([
    sys.executable, "-m", "gunicorn",
    "main_app:app",
    "--bind", f"0.0.0.0:{port}",
    "--workers", "2",
    "--timeout", "60",
    "--access-logfile", "-",
], check=True)
