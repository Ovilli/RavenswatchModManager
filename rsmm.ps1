param([Parameter(ValueFromRemainingArguments=$true)] $RemainingArgs)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pyCmd = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { $null }
if (-not $pyCmd) {
  Write-Error "Python 3 not found. Install Python 3 or use the py launcher."
  exit 1
}
$script = Join-Path $scriptDir 'rsmm'
& $pyCmd -3 $script $RemainingArgs
exit $LASTEXITCODE
