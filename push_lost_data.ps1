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

Copy-Item -Force $jsonPath (Join-Path $tmp "lost_product_data.json")
Invoke-Cmd 'git' @('-C',"`"$tmp`"",'add','lost_product_data.json') | Out-Null

$staged = & cmd /c "git -C `"$tmp`" diff --cached --stat 2>&1"
if (-not $staged) {
    Write-Host "No changes vs remote - JSON byte-identical to last push" -ForegroundColor Yellow
    Remove-Item $tmp -Recurse -Force
    exit 0
}
Write-Host $staged -ForegroundColor DarkGray

$today = Get-Date -Format "yyyy-MM-dd"
$msg = "data: lost_product_data.json " + $today
Invoke-Cmd 'git' @('-C',"`"$tmp`"",'-c','user.em