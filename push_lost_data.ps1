# push_lost_data.ps1
# Pushes index.html (dashboard) + analytics.js to tumsbux/lost-Product repo.
# NOTE (2026-07-15): lost_product_data.json is intentionally NOT touched here anymore.
# Per Decisions.md ADR [2026-07-11] "single-owner fix", tumsbux/lost-Product's OWN
# daily-update.yml is the sole builder/pusher of lost_product_data.json (avoids the
# dual-pipeline git-conflict race). Pushing the stale local copy from this folder would
# silently regress live data. If you need to rebuild the JSON, do it from F:\lost-Product\.
# Tolerant of git's normal stderr output (PowerShell treats it as error under Stop policy).

$FOLDER = "F:\co work dashboard"
Set-Location $FOLDER

$htmlPath = Join-Path $FOLDER "index_for_lost_product.html"
if (-not (Test-Path $htmlPath)) {
    Write-Host "ERROR: index_for_lost_product.html not found." -ForegroundColor Red
    exit 1
}

$tok = (Get-Content (Join-Path $FOLDER "db_config.json") -Raw | ConvertFrom-Json).github_token
$tmp = Join-Path $env:TEMP ("lostdata_" + (Get-Random))
$repoUrl = "https://" + $tok + "@github.com/tumsbux/lost-Product.git"

function Invoke-Cmd($exe, [string[]]$cmdArgs) {
    & cmd /c ($exe + ' ' + ($cmdArgs -join ' ') + ' 2>&1') | Write-Host
    return $LASTEXITCODE
}

Write-Host "Cloning tumsbux/lost-Product ..." -ForegroundColor Cyan
$cloneRc = Invoke-Cmd 'git' @('-c','core.autocrlf=false','clone','--depth=1',$repoUrl,"`"$tmp`"")
if ($cloneRc -ne 0) {
    Write-Host "FAIL clone (exit code $cloneRc). If repo is empty, create README on web UI first." -ForegroundColor Red
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    exit 1
}

Copy-Item -Force $htmlPath (Join-Path $tmp "index.html")
Copy-Item -Force (Join-Path $FOLDER "analytics.js") (Join-Path $tmp "analytics.js")
Invoke-Cmd 'git' @('-C',"`"$tmp`"",'add','index.html','analytics.js') | Out-Null

$staged = & cmd /c "git -C `"$tmp`" diff --cached --stat 2>&1"
if (-not $staged) {
    Write-Host "No changes vs remote - dashboard byte-identical to last push" -ForegroundColor Yellow
    Remove-Item $tmp -Recurse -Force
    exit 0
}
Write-Host $staged -ForegroundColor DarkGray

$today = Get-Date -Format "yyyy-MM-dd"
$msg = "dashboard update " + $today
Invoke-Cmd 'git' @('-C',"`"$tmp`"",'-c','user.email=bot@dashboard','-c','user.name=Dashboard-Bot','commit','-m',"`"$msg`"") | Out-Null

Write-Host "Pushing ..." -ForegroundColor Cyan
$pushRc = Invoke-Cmd 'git' @('-C',"`"$tmp`"",'push','origin','main')
if ($pushRc -eq 0) {
    Write-Host "OK pushed to https://tumsbux.github.io/lost-Product/" -ForegroundColor Green
} else {
    Write-Host "FAIL push (exit code $pushRc)" -ForegroundColor Red
}

Remove-Item $tmp -Recurse -Force
