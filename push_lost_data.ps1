# push_lost_data.ps1
# Pushes lost_product_data.json to the separate tumsbux/lost-Product- repo
# (kept separate to avoid bloating tumsbux/daily-report main repo)
#
# Usage:
#   cd "F:\co work dashboard"
#   .\push_lost_data.ps1

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

Write-Host "Cloning tumsbux/lost-Product- ..." -ForegroundColor Cyan
$cloneUrl = "https://" + $tok + "@github.com/tumsbux/lost-Product-.git"
git -c core.autocrlf=false clone --depth=1 $cloneUrl $tmp
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL clone" -ForegroundColor Red; exit 1 }

Copy-Item -Force $jsonPath (Join-Path $tmp "lost_product_data.json")
git -C $tmp add lost_product_data.json

$staged = git -C $tmp diff --cached --stat
if (-not $staged) {
    Write-Host "No changes vs remote - JSON byte-identical to last push" -ForegroundColor Yellow
    Remove-Item $tmp -Recurse -Force
    exit 0
}
Write-Host $staged -ForegroundColor DarkGray

$today = Get-Date -Format "yyyy-MM-dd"
$msg = "data: lost_product_data.json " + $today
git -C $tmp -c user.email=bot@dashboard -c user.name="Dashboard Bot" commit -m $msg

Write-Host "Pushing ..." -ForegroundColor Cyan
git -C $tmp push origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "OK pushed to https://tumsbux.github.io/lost-Product-/lost_product_data.json" -ForegroundColor Green
} else {
    Write-Host "FAIL push" -For