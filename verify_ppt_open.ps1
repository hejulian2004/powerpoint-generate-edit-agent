param([string]$FilePath)

$ppt = $null
try {
    $ppt = New-Object -ComObject PowerPoint.Application
    $pres = $ppt.Presentations.Open($FilePath, [Microsoft.Office.Core.MsoTriState]::msoFalse, [Microsoft.Office.Core.MsoTriState]::msoFalse, [Microsoft.Office.Core.MsoTriState]::msoFalse)
    Write-Host "OPEN_SUCCESS: $($pres.Slides.Count)"
    $pres.Close()
} catch {
    Write-Host "OPEN_FAILED: $($_.Exception.Message)"
} finally {
    if ($ppt) {
        $ppt.Quit()
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
    }
}
