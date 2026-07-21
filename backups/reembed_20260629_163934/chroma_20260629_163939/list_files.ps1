$folder = "D:\AG_docs\pdfs"
if (-not (Test-Path $folder)) {
    Write-Host "Folder not found: $folder"
    exit
}
$files = Get-ChildItem $folder -File | Sort-Object Length -Descending
foreach ($f in $files) {
    $sizeMB = [math]::Round($f.Length / 1MB, 2)
    Write-Host "$sizeMB MB`t$($f.Name)"
}
Write-Host "`nTotal: $($files.Count) files"
