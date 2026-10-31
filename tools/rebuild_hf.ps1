param([switch]$Batch, [switch]$SkipPacks)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$env:PYTHONIOENCODING = 'utf-8'
function Invoke-Astralogue([string[]]$Arguments) {
    & $taskPython -m astralogue @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Astralogue failed: $Arguments" }
}
$taskSource = 'data/raw/hsr-mainline'
$taskControl = 'data/packs/hsr-mainline-m59.storypack'
$alignArgs = @('hf','align',$taskSource,$taskControl)
if ($Batch) { $alignArgs += '--batch' }
Invoke-Astralogue $alignArgs
if (-not $SkipPacks) {
    $taskFiles = Get-ChildItem -LiteralPath 'data/external/hf-trailblaze/missions' -Filter '*.json' | Where-Object { $_.Name -match '^(001|002)_' } | Sort-Object Name -Descending
    foreach ($taskFile in $taskFiles) {
        $stem = $taskFile.BaseName
        $prefix = $stem.Substring(0,3)
        Invoke-Astralogue @('hf','build',"data/staging/hf-aligned/$stem.json",$taskSource,$taskControl,
            '--output',"data/packs/hf-$prefix.storypack",'--baseline-reader','data/packs/hsr-mainline-reader.storypack',
            '--baseline-reader','data/packs/hsr-reader.storypack','--force')
    }
}
& $taskPython tools/verify_hf.py
if ($LASTEXITCODE -ne 0) { throw 'HF Runtime verification failed' }
$archiveArgs = @('archive','build',$taskSource,'--output','data/archive-hf.sqlite','--force',
    '--pack',$taskControl,'--pack','data/packs/hsr-reader.storypack','--pack','data/packs/hsr-mainline-reader.storypack',
    '--pack','data/packs/hf-002.storypack','--pack','data/packs/hf-001.storypack')
foreach ($item in Get-ChildItem -LiteralPath 'data/staging/hf-aligned' -Filter '*.json') {
    if ($item.Name -eq 'batch-report.json' -or $item.Name.EndsWith('.failed.json')) { continue }
    if (-not $Batch -and $item.Name -notmatch '^(001|002)_') { continue }
    $archiveArgs += @('--alignment',$item.FullName)
}
Invoke-Astralogue $archiveArgs
& $taskPython tools/review_hf_sample.py
if ($LASTEXITCODE -ne 0) { throw 'Source review failed' }
& $taskPython tools/report_hf.py
if ($LASTEXITCODE -ne 0) { throw 'HF report failed' }
Write-Output 'Offline HF rebuild and verification completed. No fetch command was invoked.'
