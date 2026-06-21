param(
    [Parameter(Mandatory=$true)][string]$Elf,
    [Parameter(Mandatory=$true)][string]$Gdb,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Symbol,
    [Parameter(Mandatory=$true)][int]$Count,
    [string]$WidthLetter = "hu",     # GDB x/ unit: hu=halfword unsigned (u16)
    [string]$TriggerSymbol,          # break here each interval
    [string[]]$Preroll = @(),        # GDB cmds after connect (e.g. set var)
    [int]$Samples = 40,
    [string]$DoneSymbol,             # optional completion flag
    [string[]]$WatchName = @(),      # parallel arrays: per-interval watch trace
    [string[]]$WatchExpr = @(),      # gdb lvalue (symbol) read for WatchName[j]
    [string[]]$WatchCast = @(),      # per-watch type (u8/s8/u16/s16/u32/s32/raw)
    [string]$OutFile,                # raw dump destination
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

# Map a watch type to a C cast. Under -O3/-flto the watched globals are minimal
# symbols (address only, no DWARF type), so `printf "%d", sym` fails with
# "unknown type". Reading via `*(ctype *)&sym` (address + explicit cast) is
# type-agnostic and works regardless of debug-info stripping. "raw"/unknown ->
# no cast (caller supplied a fully-formed expression).
$WATCH_CTYPE = @{ "u8" = "unsigned char"; "s8" = "char"; "u16" = "unsigned short";
                  "s16" = "short"; "u32" = "unsigned int"; "s32" = "int" }
function _watch_arg([string]$expr, [string]$cast) {
    $ctype = $WATCH_CTYPE[$cast]
    if ($ctype) { return "*($ctype *)&$expr" }
    return $expr
}

$cmds = @("set pagination off", "set confirm off", "target remote :$Port")
$cmds += $Preroll
if ($TriggerSymbol) { $cmds += "break $TriggerSymbol" }
for ($i = 0; $i -lt $Samples; $i++) {
    if ($TriggerSymbol) { $cmds += "continue" }
    $cmds += "x/$Count$WidthLetter &$Symbol"
    # Watch trace: emit one MDBUG_WATCH line per watch after the perf dump. These
    # lines are NOT shaped like `0xADDR ... : <ints>`, so parse_gdb_dump ignores
    # them; parse_watch picks them up (k-th occurrence of a name = interval k).
    for ($j = 0; $j -lt $WatchName.Count; $j++) {
        $cast = if ($j -lt $WatchCast.Count) { $WatchCast[$j] } else { "u16" }
        $arg = _watch_arg $WatchExpr[$j] $cast
        $cmds += "printf `"MDBUG_WATCH $($WatchName[$j]) %d\n`", $arg"
    }
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
$argLine = "-q -batch -x `"$script`" `"$Elf`""
$p = Start-Process -FilePath $Gdb -ArgumentList $argLine -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
if (-not $p.WaitForExit(60000)) { Stop-Process -Id $p.Id -Force; throw "gdb sampler timed out" }
$raw = Get-Content -LiteralPath $stdout -Raw
Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stdout -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $raw -Encoding ASCII }
return $raw
