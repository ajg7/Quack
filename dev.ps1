$root = $PSScriptRoot

$backend = "Set-Location '$root'; & '.\.venv\Scripts\Activate.ps1'; uvicorn quack.api:app --reload --port 8000"
$frontend = "Set-Location '$root\ui'; npm run dev"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontend

Write-Host "Backend: http://localhost:8000"
Write-Host "Frontend: http://localhost:5173"
