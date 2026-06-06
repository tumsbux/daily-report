# push_lost_data.ps1
# Pushes lost_product_data.json to tumsbux/lost-Product repo.
# Tolerant of git's normal stderr output (PowerShell treats it as error under Stop policy).

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
$repoUrl = "https://" + $tok + "@github.com/tumsbux/lost-Product.git"

# Helper: run a command and don't let PowerShell freak out about stderr text
function Invoke-Cmd($exe, [string[]]$cmdArgs) {
    & cmd /c ($exe + ' ' + ($cmdArgs -join ' ') + ' 2>&1') | Write-Host
    return $LASTEXITCODE
}

Write-Host "Trying clone of tumsbux/lost-Product ..." -ForegroundColor Cyan
$cloneRc = Invoke-Cmd 'git' @('-c','core.autocrlf=false','clone','--depth=1',$repoUrl,"`"$tmp`"")

if ($cloneRc -ne 0) {
    Write-Host "Clone failed (likely empty repo). Initializing fresh ..." -ForegroundColor Yellow
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Path $tmp | Out-Null
    Invoke-Cmd 'git' @('-C',"`"$tmp`"",'init','-b','main') | Out-Null
    Invoke-Cmd 'git' @('-C',"`"$tmp`"",'remote','add','origin',$repoUrl) | Out-Null
    @"
# lost-Product

Generated data for [tumsbux/daily-report](https://github.com/tumsbux/daily-report) Lost Product Analysis dashboard.

Contains ``lost_product_data.json`` only (regenerated daily from MyPOS).
Separated from main repo because the file can exceed 50 MB.

- Dashboard: https://tumsb