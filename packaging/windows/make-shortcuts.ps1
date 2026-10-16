# Creates "Utility Tracker" shortcuts on the Desktop and in the Start menu.
param([Parameter(Mandatory = $true)][string]$Dest)
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $link = $shell.CreateShortcut((Join-Path $folder 'Utility Tracker.lnk'))
    $link.TargetPath = Join-Path $Dest 'python\pythonw.exe'
    $link.Arguments = '"' + (Join-Path $Dest 'app\serve.py') + '"'
    $link.WorkingDirectory = Join-Path $Dest 'app'
    $link.Description = 'Open Utility Tracker'
    $link.Save()
}
