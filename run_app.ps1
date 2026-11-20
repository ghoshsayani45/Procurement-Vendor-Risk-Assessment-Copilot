# Run the complete Vendor Risk Copilot app on Windows.
#   powershell -ExecutionPolicy Bypass -File run_app.ps1            # UI on http://localhost:8501 (API in-process)
#   powershell -ExecutionPolicy Bypass -File run_app.ps1 -Mode both # API on :8000 (docs at /docs) + UI on :8501
#   powershell -ExecutionPolicy Bypass -File run_app.ps1 -Mode api  # API only
#   powershell -ExecutionPolicy Bypass -File run_app.ps1 -Mode test # full offline test suite
param([ValidateSet("ui", "both", "api", "test")][string]$Mode = "ui")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
$py = ".\.venv\Scripts\python.exe"
Write-Host "Installing app dependencies (first run takes a few minutes) ..."
& $py -m pip install --disable-pip-version-check -q -r docker\requirements-app.txt pytest
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example (no keys needed for the offline demo)." }

Write-Host "Preparing the local database (data\processed\copilot.sqlite) ..."
& $py -m scripts.load_db

switch ($Mode) {
    "test" { & $py -m pytest -q; break }
    "api"  { & $py -m uvicorn app.api.main:app --port 8000; break }
    "both" {
        Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "app.api.main:app", "--port", "8000"
        Start-Sleep -Seconds 4
        $env:API_URL = "http://localhost:8000"
        & $py -m streamlit run app\ui\streamlit_app.py --server.port 8501
        break
    }
    default { & $py -m streamlit run app\ui\streamlit_app.py --server.port 8501 }
}
