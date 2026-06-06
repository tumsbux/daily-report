# push_lost_data.ps1
# Pushes lost_product_data.json to tumsbux/lost-Product- repo.
# Handles empty-repo case (first-ever push) by initializing a local git repo
# and force-pushing main branch.

$ErrorActionPreference = "Stop"
$FOLDER = "F:\co work dashboard"
Set-Location $FOLDER

$jsonPath = Join-Path $FOLDER "lost_product_data.json"
if (-not (Test-Path $jsonPath)) {
    Write-Host "ERROR: lost_product_data.json not found. Run 'py build_lost_product_data.py' first." -ForegroundColor Red
    exit 1
}

$sz = [math]::Round((Get-Item $jsonPath).Length / 1MB, 1)
Write-Host "lost_product_data.json size: $sz MB" -ForegroundColor Cyan
if ($sz -gt 99) {
    Write-Host "WARN: file is over 99 MB - GitHub hard limit is 100 MB. Raise MIN_QTY in build_lost_product_data.py." -ForegroundColor Yellow
}

$tok = (Get-Content (Join-Path $FOLDER "db_config.json") -Raw | ConvertFrom-Json).github_token
$tmp = Join-Path $env:TEMP ("lostdata_" + (Get-Random))
$repoUrl = "https://" + $tok + "@github.com/tumsbux/lost-Product-.git"

# Try clone first
Write-Host "Trying clone of tumsbux/lost-Product- ..." -ForegroundColor Cyan
git -c core.autocrlf=false clone --depth=1 $repoUrl $tmp 2>$null

if ($LASTEXITCODE -ne 0) {
    # Empty repo - init from scratch
    Write-Host "Clone failed (likely empty repo). Initializing fresh ..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $tmp | Out-Null
    git -C $tmp init -b main
    git -C $tmp remote add origin $repoUrl

    # Add a README so the repo isn't just one data file
    @"
# lost-Product-

Generated data for [tumsbux/daily-report](https://github.com/tumsbux/daily-report) Lost Product Analysis dashboard.

This repo contains only ``lost_product_data.json`` (regenerated daily from MyPOS).
Separated from the main repo because the file can exceed 50 MB.

**Dashboard:** https://tumsbux.github.io/daily-report/lost_product_dashboard.html
**Data URL:**  https://tumsbux.github.io/lost-Product-/lost_product_data.json
"@ | Out-File -Encoding utf8 (Join-Path $tmp "README.md")
}

Copy-Item -Force $jsonPat