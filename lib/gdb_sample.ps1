param(
    [Parameter(Mandatory=$true)][string]$Elf,
    [Parameter(Mandatory=$true)][string]$Gdb,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Symbol,
    [Parameter(Mandatory=$true)][int]$Count,
    [string]$WidthLetter = "h",      # GDB x/ unit: h=halfword (u16)
    [string]$TriggerSymbol,          # break here each interval
    [string[]]$Preroll = @(),        # GDB cmds after connect (e.g. set var)
    [int]$Samples = 40,
    [string]$DoneSymbol,             # optional completion flag
    [string]$OutFile,                # raw dump destination
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

$cmds = @("set pagination off", "set confirm off", "target remote :$Port")
$cmds += $Preroll
if ($TriggerSymbol) { $cmds += "break $TriggerSymbol" }
for ($i = 0; $i -lt $Samples; $i++) {
    if ($TriggerSymbol) { $cmds += "continue" }
    $cmds += "x/$Count$WidthLetter &$Symbol"
}
if ($DoneSymbol) { $cmds += "x/1$WidthLetter &$DoneSymbol" }
$cmds += @("disconnect", "quit")

$script = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString() + ".gdb")
Set-Content -LiteralPath $script -Value $cmds -Encoding ASCII

if ($DryRun) {
    Get-Content -LiteralPath $script
    Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
    return
}

$stdout = [System.IO.Path]::GetTempFileName()
$stderr = [System.IO.Path]::GetTempFileName()
$p = Start-Process -FilePath $Gdb -ArgumentList @("-q", "-batch", "-x", $script, $Elf) `
    -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
if (-not $p.WaitForExit(60000)) { Stop-Process -Id $p.Id -Force; throw "gdb sampler timed out" }
$raw = Get-Content -LiteralPath $stdout -Raw
Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stdout -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $raw -Encoding ASCII }
return $raw
