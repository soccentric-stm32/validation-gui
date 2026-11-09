$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = $env:PYTHON
if (-not $Python) {
    if (Test-Path ".venv\Scripts\python.exe") {
        $Python = ".venv\Scripts\python.exe"
    } else {
        $Python = "python"
    }
}
$env:HWVAL_STUDIO_GIT_COMMIT = (git rev-parse --short HEAD 2>$null)
$env:HWVAL_STUDIO_BUILD_DATE = (Get-Date -Format "yyyy-MM-dd")
& $Python scripts/make_icons.py
& $Python -m PyInstaller packaging/hwval-studio.spec --noconfirm --clean
$version = & $Python -c "import hwval_studio; print(hwval_studio.__version__)"
if (Get-Command wix -ErrorAction SilentlyContinue) {
    wix build packaging/windows/Product.wxs -arch x64 -bindpath "payload=dist\hwval-studio" -d Version=$version -o "dist/HWVAL_Studio-$version.msi"
    Write-Host "MSI written to dist/HWVAL_Studio-$version.msi"
} else {
    Write-Host "WiX not found; the one-folder build is in dist/hwval-studio"
}
