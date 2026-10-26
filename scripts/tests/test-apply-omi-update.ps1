# Compatibility test entry: the old refusal-only policy was superseded by the
# explicitly authorized 180s cutoff. The replacement uses real private owners,
# exact retained children, foreign-child survival and production verifier doubles.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'test-apply-omi-cutoff.ps1')
