$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$candidates = @((Join-Path $root '.venv\Scripts\python.exe'), (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { $command = Get-Command python -ErrorAction SilentlyContinue; if ($command) { $python = $command.Source } }
if (-not $python) { throw 'Instalá Python y las dependencias indicadas en LEEME.md.' }
& $python -c "import pdfplumber, pypdfium2, PIL" 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Faltan dependencias. Seguí las instrucciones de instalación en LEEME.md.' }
& $python (Join-Path $PSScriptRoot 'app.py')
exit $LASTEXITCODE
