param([Parameter(ValueFromRemainingArguments=$true)] $RemainingArgs)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script = Join-Path $scriptDir 'rsmm'
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 $script @RemainingArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  & python $script @RemainingArgs
} else {
  Write-Error "Python 3 not found. Install Python 3 or use the py launcher."
  exit 1
}
exit $LASTEXITCODE
