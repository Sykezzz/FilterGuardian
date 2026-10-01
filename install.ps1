$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'FilterGuardian local installation'
Write-Host 'Requires Python 3.10+ and Windows Chrome for optional browser monitoring.'
Write-Host 'This creates .venv here and downloads Python packages from PyPI.'
if ((Read-Host 'Create the local environment and install dependencies? [y/N]') -ne 'y') { exit }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed. Install Python 3.10+ first.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; rerun this installer to retry.' }
if ((Read-Host 'Download Playwright Chromium for optional URL analysis? [y/N]') -eq 'y') {
    & .\.venv\Scripts\python.exe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed; retry with python -m playwright install chromium.' }
}
Write-Host 'No system proxy, certificates, or existing browser profiles were changed.'
if ((Read-Host 'Open the first-run setup menu now? [y/N]') -eq 'y') {
    & .\.venv\Scripts\python.exe main.py
}
