param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not $SkipInstall) {
    python -m pip install --upgrade pyinstaller
}

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "dist"
Remove-Item -Force -ErrorAction SilentlyContinue "AI-Harness.spec"

python -m PyInstaller `
    --noconsole `
    --clean `
    --name "AI Harness" `
    --add-data "config.json;." `
    desktop_app.py

$PackageDirectory = Join-Path $ProjectRoot "dist\AI Harness Desktop"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PackageDirectory
New-Item -ItemType Directory -Force $PackageDirectory | Out-Null
Copy-Item "dist\AI Harness\AI Harness.exe" $PackageDirectory
Copy-Item "README.md" $PackageDirectory
Copy-Item "config.json" $PackageDirectory

$ZipPath = Join-Path $ProjectRoot "dist\AI-Harness-Windows.zip"
Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath
Compress-Archive -Path "$PackageDirectory\*" -DestinationPath $ZipPath

Write-Host ""
Write-Host "Desktop package created:"
Write-Host "  $($PackageDirectory)\AI Harness.exe"
Write-Host "  $ZipPath"
