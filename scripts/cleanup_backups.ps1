$backups = Get-ChildItem "D:\AKO_Hub\backups\reembed_20260629_*"
$keep = "reembed_20260629_163934"
Add-Type -AssemblyName Microsoft.VisualBasic
foreach ($b in $backups) {
    if ($b.Name -ne $keep) {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($b.FullName, 'OnlyErrorDialogs', 'SendToRecycleBin')
        Write-Host "Trashed: $($b.Name)"
    }
}
Write-Host "Done."
