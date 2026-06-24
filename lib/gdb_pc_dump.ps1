param(
    [Parameter(Mandatory=$true)][string]$Elf,
    [Parameter(Mandatory=$true)][string]$Gdb,
    [Parameter(Mandatory=$true)][int]$Port,
    [string]$RingSymbol = "g_pc_samples",  # the in-RAM PC-sample ring (u32[])
    [int]$RingMax = 1024,                   # PC_SAMPLE_MAX -> the x/<MAX>xw count
    [string]$TriggerSymbol = "dbg_perf_tick", # break here once per frame to fill the ring
    [int]$Continues = 82,                   # break-continues before the ring is full
    [string]$OutFile,                       # raw dump destination
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

# Fill the PC-sample ring during a deterministic run, then dump it -- the proven
# procedure documented in PROFILING.md. Break the per-frame trigger, continue N
# times until g_pc_samples is full, then x/<MAX>xw the ring as hex words. The
# output is a flat hex word list; analyzer/profile.py (clock-agnostic) parses the
# PCs out of it. Mirrors lib/gdb_sample.ps1's launch/script/dump shape, but dumps
# the PC ring instead of the perf block.
$cmds = @("set pagination off", "set confirm off", "target remote :$Port")
if ($TriggerSymbol) {
    $cmds += "break $TriggerSymbol"
    for ($i = 0; $i -lt $Continues; $i++) { $cmds += "continue" }
}
$cmds += ("x/{0}xw &{1}" -f $RingMax, $RingSymbol)
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
$argLine = "-q -batch -x `"$script`" `"$Elf`""
$p = Start-Process -FilePath $Gdb -ArgumentList $argLine -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
# A set breakpoint slows BlastEm substantially; budget generously on a weak host.
if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force; throw "gdb pc-dump timed out" }
$raw = Get-Content -LiteralPath $stdout -Raw
Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stdout -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $raw -Encoding ASCII }
return $raw
