# Run every browser UI test (tests/*.mjs) headless with the local Playwright + headless Chromium.
# Usage:  powershell -File tests\ui\run-ui-tests.ps1 [name-filter]
param([string]$Filter = '')
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
if (-not $env:LANGPAL_PLAYWRIGHT_MODULE) {
  $env:LANGPAL_PLAYWRIGHT_MODULE = 'file:///E:/claude%20workspace/speaking-coach/node_modules/playwright-core/index.mjs'
}
if (-not $env:LANGPAL_CHROME_PATH) {
  $env:LANGPAL_CHROME_PATH = Join-Path $env:LOCALAPPDATA 'ms-playwright\chromium_headless_shell-1234\chrome-headless-shell-win64\chrome-headless-shell.exe'
}
$env:LANGPAL_SOURCE_ROOT = $repo
$env:LANGPAL_TEST_ROOT = $repo
$failed = @()
foreach ($test in Get-ChildItem (Join-Path $repo 'tests') -Filter '*.mjs' | Where-Object { $_.Name -like "*$Filter*" }) {
  $output = & node $test.FullName 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Output "PASS $($test.Name)" }
  else {
    $failed += $test.Name
    Write-Output "FAIL $($test.Name)"
    $output | Select-Object -Last 6 | ForEach-Object { Write-Output "     $_" }
  }
}
if ($failed.Count) { Write-Output "`n$($failed.Count) failed"; exit 1 } else { Write-Output "`nall passed" }
