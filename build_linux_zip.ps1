# Creates dist/murmur-linux-<version>.zip using linux_runtime_files.txt for
# project runtime modules and explicit support/UI/server file lists below.
# Upload the zip and murmur-install.sh to murmurlabs.dev/downloads/ via FileZilla.
#
# Usage: .\build_linux_zip.ps1
$ErrorActionPreference = "Stop"

# Copy a text file with CRLF → LF conversion so bash on Linux can read it
function Copy-LF($From, $To) {
    $text = [System.IO.File]::ReadAllText($From) -replace "`r`n", "`n" -replace "`r", "`n"
    [System.IO.File]::WriteAllText($To, $text, [System.Text.UTF8Encoding]::new($false))
}

$version  = "v1.2.1"
$src      = $PSScriptRoot
$tempRoot = Join-Path $src "dist\_linux_tmp"
$tempDir  = Join-Path $tempRoot "murmur"
$zipOut   = Join-Path $src "dist\murmur-linux-$version.zip"

# ── Clean temp ──────────────────────────────────────────────────────────────
if (Test-Path $tempRoot) { Remove-Item $tempRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tempDir       | Out-Null
New-Item -ItemType Directory -Force -Path "$tempDir\ui"  | Out-Null
New-Item -ItemType Directory -Force -Path "$tempDir\server" | Out-Null
New-Item -ItemType Directory -Force -Path "$tempDir\themes" | Out-Null

# ── Python source ───────────────────────────────────────────────────────────
$pyFiles = Get-Content "$src\linux_runtime_files.txt" | Where-Object { $_.Trim() }
foreach ($f in $pyFiles) { Copy-LF "$src\$f" "$tempDir\$f" }

# ── Root support files ──────────────────────────────────────────────────────
Copy-LF  "$src\requirements.txt"     "$tempDir\requirements.txt"
Copy-LF  "$src\requirements-linux.lock" "$tempDir\requirements-linux.lock"
Copy-LF  "$src\README.md"            "$tempDir\README.md"
Copy-LF  "$src\setup_linux.sh"       "$tempDir\setup_linux.sh"
Copy-LF  "$src\linux_bootstrap.py"   "$tempDir\linux_bootstrap.py"
Copy-LF  "$src\linux_runtime_files.txt" "$tempDir\linux_runtime_files.txt"
Copy-LF  "$src\.env.example"         "$tempDir\.env.example"
Copy-LF  "$src\murmur.svg"           "$tempDir\murmur.svg"
Copy-LF  "$src\murmur-light.svg"     "$tempDir\murmur-light.svg"
Copy-LF  "$src\murmur-warm-dark.svg" "$tempDir\murmur-warm-dark.svg"
Copy-Item "$src\murmur.ico"          "$tempDir\murmur.ico"  # binary

# ── UI ──────────────────────────────────────────────────────────────────────
foreach ($f in @('settings.html', 'log.html', 'server.html', 'splash.html')) {
    Copy-LF "$src\ui\$f" "$tempDir\ui\$f"
}

# ── Server ──────────────────────────────────────────────────────────────────
foreach ($f in @('faster_whisper_server.py', 'requirements.txt', '.env.example', 'murmur-whisper.service', 'README.md')) {
    Copy-LF "$src\server\$f" "$tempDir\server\$f"
}

# ── Themes ──────────────────────────────────────────────────────────────────
Copy-LF "$src\themes\omarchy_palettes.json" "$tempDir\themes\omarchy_palettes.json"

# ── Zip ─────────────────────────────────────────────────────────────────────
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
Compress-Archive -Path $tempDir -DestinationPath $zipOut

# ── Cleanup ─────────────────────────────────────────────────────────────────
Remove-Item $tempRoot -Recurse -Force

$bytes = (Get-Item $zipOut).Length
$size  = if ($bytes -ge 1MB) { "$([math]::Round($bytes/1MB,1)) MB" } else { "$([math]::Round($bytes/1KB,0)) KB" }
Write-Host "Built: $zipOut ($size)"
Write-Host ""
Write-Host "Next: upload both files to murmurlabs.dev/downloads/ via FileZilla:"
Write-Host "  dist\murmur-linux-$version.zip"
Write-Host "  murmur-install.sh"
