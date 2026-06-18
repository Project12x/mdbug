param(
    [Parameter(Mandatory=$true)][ValidateSet("sample","screenshot")][string]$Action,
    [Parameter(Mandatory=$true)][string]$Rom,
    [Parameter(Mandatory=$true)][string]$EmuPath,
    [string]$Elf, [string]$Gdb,
    [ValidateSet("export","gdb")][string]$SampleMode = "export",
    [int]$Frames = 700, [int]$Port = 9001,
    [string]$Symbol, [int]$Count = 21, [string]$WidthLetter = "h",
    [long]$Address, [string]$TriggerSymbol, [string[]]$Preroll = @(), [int]$Samples = 40,
    [string]$DoneSymbol, [string]$OutFile,
    [hashtable[]]$Checkpoints = @(),
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

if ($Action -eq "sample" -and $SampleMode -eq "export") {
    $addrHex = "0x{0:X6}" -f $Address
    $size = $Count * 2
    $emuArgs = "--rom `"$Rom`" --headless --frames $Frames --dump-workram $addrHex,$size,`"$OutFile`""
    if ($DryRun) { Write-Output "$EmuPath $emuArgs"; return }
    $p = Start-Process -FilePath $EmuPath -ArgumentList $emuArgs -NoNewWindow -PassThru
    if (-not $p.WaitForExit(120000)) { Stop-Process -Id $p.Id -Force; throw "emusplatter export timed out" }
    return $OutFile
}

if ($Action -eq "sample" -and $SampleMode -eq "gdb") {
    $emuArgs = "--rom `"$Rom`" --headless --frames $Frames --gdb-server $Port"
    if ($DryRun) { Write-Output "$EmuPath $emuArgs"; return }
    $emu = Start-Process -FilePath $EmuPath -ArgumentList $emuArgs -NoNewWindow -PassThru
    try {
        for ($i = 0; $i -lt 100 -and -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 100 }
        & (Join-Path $root "lib\gdb_sample.ps1") -Elf $Elf -Gdb $Gdb -Port $Port -Symbol $Symbol `
            -Count $Count -WidthLetter $WidthLetter -TriggerSymbol $TriggerSymbol -Preroll $Preroll `
            -Samples $Samples -DoneSymbol $DoneSymbol -OutFile $OutFile
    } finally { if (-not $emu.HasExited) { Stop-Process -Id $emu.Id -Force } }
    return $OutFile
}

# screenshot: one --screenshot run per checkpoint (frame-exact)
if ($DryRun) {
    foreach ($c in $Checkpoints) { Write-Output "$EmuPath --rom `"$Rom`" --headless --frames $($c.atFrame) --screenshot `"$OutFile\$($c.name).png`"" }
    return
}
New-Item -ItemType Directory -Path $OutFile -Force | Out-Null
foreach ($c in $Checkpoints) {
    $shot = Join-Path $OutFile "$($c.name).png"
    $p = Start-Process -FilePath $EmuPath -NoNewWindow -PassThru -ArgumentList `
        "--rom `"$Rom`" --headless --frames $($c.atFrame) --screenshot `"$shot`""
    if (-not $p.WaitForExit(120000)) { Stop-Process -Id $p.Id -Force; throw "emusplatter screenshot timed out" }
}
