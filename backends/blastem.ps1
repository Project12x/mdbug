param(
    [Parameter(Mandatory=$true)][ValidateSet("sample","screenshot")][string]$Action,
    [Parameter(Mandatory=$true)][string]$Rom,
    [string]$Elf,
    [string]$EmuPath,                 # null/empty -> install_blastem.ps1
    [string]$Gdb,
    [int]$Port = 1234,
    [string]$Symbol, [int]$Count = 21, [string]$WidthLetter = "h",
    [string]$TriggerSymbol, [string[]]$Preroll = @(), [int]$Samples = 40,
    [string]$DoneSymbol,
    [string[]]$WatchName = @(), [string[]]$WatchExpr = @(), [string[]]$WatchCast = @(),
    [string]$OutFile,                 # sample: raw dump; screenshot: dir
    [hashtable[]]$Checkpoints = @(),  # @{ name=..; atSeconds=.. }
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

if (-not $EmuPath -and -not $DryRun) {
    & (Join-Path $root "install_blastem.ps1")
    $EmuPath = (Get-Content -LiteralPath (Join-Path $root "blastem\path.txt") -Raw).Trim()
}

if ($Action -eq "sample") {
    $emuArgs = "`"$Rom`" -D"
    if ($DryRun) { Write-Output "$EmuPath $emuArgs"; return }
    $emu = Start-Process -FilePath $EmuPath -ArgumentList $emuArgs -PassThru
    try {
        # Give the emulator higher priority to reduce (but not eliminate) interference
        # from other host processes during perf sampling. Host noise still affects
        # wall-time aspects and GDB sampling jitter; use emusplatter backend for
        # the most deterministic results.
        if ($emu -and -not $emu.HasExited) {
            $emu.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High
        }
        for ($i = 0; $i -lt 100 -and -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 100 }
        & (Join-Path $root "lib\gdb_sample.ps1") -Elf $Elf -Gdb $Gdb -Port $Port -Symbol $Symbol `
            -Count $Count -WidthLetter $WidthLetter -TriggerSymbol $TriggerSymbol -Preroll $Preroll `
            -Samples $Samples -DoneSymbol $DoneSymbol -WatchName $WatchName -WatchExpr $WatchExpr `
            -WatchCast $WatchCast -OutFile $OutFile
    } finally { if (-not $emu.HasExited) { Stop-Process -Id $emu.Id -Force } }
    return $OutFile
}

# screenshot: reuse jazzmd capture mechanism (foreground + BlastEm screenshot key)
if ($DryRun) { Write-Output "$EmuPath `"$Rom`" -g  (checkpoints: $($Checkpoints.Count))"; return }
& (Join-Path $PSScriptRoot "..\lib\blastem_screenshot.ps1") -EmuPath $EmuPath -Rom $Rom -OutDir $OutFile -Checkpoints $Checkpoints
