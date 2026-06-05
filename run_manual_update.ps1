# run_manual_update.ps1
# Manual dashboard update - runs all 3 steps in order
# Usage:
#   & "F:\co work dashboard\run_manual_update.ps1"
#   & "F:\co work dashboard\run_manual_update.ps1" -Day 30

param([int]$Day = 0)

$FOLDER = "F:\co work dashboard"
$START  = Get-Date

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  Dashboard Manual Update  $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow

# STEP 1: Fraud rebuild
Write-Host ""
Write-Host "[1/3] Fraud Analysis rebuild (no-push)" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
py "$FOLDER\rebuild_fraud_analysis.py" --no-push
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK  fraud_data.json built" -ForegroundColor Green
} else {
    Write-Host "  WARN: fraud rebuild failed (non-fatal, continuing)" -ForegroundColor Yellow
}

# STEP 2: Product data
Write-Host ""
Write-Host "[2/3] Product Data build (no-push)" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
if ($Day -gt 0) {
    py "$FOLDER\build_product_data_mysql.py" --no-push --day $Day
} else {
    py "$FOLDER\build_product_data_mysql.py" --no-push
}
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK  product_data.json built" -ForegroundColor Green
} else {
    Write-Host "  FAIL product data build failed" -ForegroundColor Red
}

# STEP 3a: Lost product data (yearly history, only changes monthly so cheap)
Write-Host ""
Write-Host "[3a/4] Lost Product build (no-push)" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
py "$FOLDER\build_lost_product_data.py"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK  lost_product_data.json built" -ForegroundColor Green
} else {
    Write-Host "  WARN: lost product build failed (non-fatal)" -ForegroundColor Yellow
}

# STEP 3: Sales dashboard + push
Write-Host ""
Write-Host "[4/4] Sales Dashboard update + push to GitHub" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
if ($Day -gt 0) {
    py "$FOLDER\update_dashboard.py" --day $Day
} else {
    py "$FOLDER\update_dashboard.py"
}
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK  Dashboard pushed to GitHub Pages" -ForegroundColor Green
} else {
    Write-Host "  FAIL update_dashboard.py failed" -ForegroundColor Red
}

# Summary
$ELAPSED = [math]::Round(((Get-Date) - $START).TotalSeconds)
Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  Done in ${ELAPSED}s" -ForegroundColor Yellow
Write-Host "  https://tumsbux.github.io/daily-report/" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
