param([string]$Name,[string]$Root,[string]$Mode,[string]$Python)
$ErrorActionPreference='Stop'
$mutex=[Threading.Mutex]::new($false,$Name)
$null=$mutex.WaitOne(0)
$event=[Threading.EventWaitHandle]::new($false,'AutoReset',"$Name.Exit")
$info=[Diagnostics.ProcessStartInfo]::new($Python,'-c "import time; time.sleep(30)"')
$info.UseShellExecute=$false;$info.CreateNoWindow=$true
$child=[Diagnostics.Process]::Start($info);$null=$child.Handle
$foreign=[Diagnostics.Process]::Start($info);$null=$foreign.Handle
Set-Content -LiteralPath (Join-Path $Root 'foreign') -Value $foreign.Id
Set-Content -LiteralPath (Join-Path $Root 'ready') -Value $child.Id
if($event.WaitOne(10000)){
    Set-Content -LiteralPath (Join-Path $Root 'signalled') -Value 'once'
    if($Mode -eq 'graceful'){
        $child.Kill();$null=$child.WaitForExit(1000)
        $mutex.ReleaseMutex()
        $log=Join-Path $Root ('logs\'+(Get-Date -Format 'yyyy-MM-dd')+'\launcher.log')
        Add-Content -LiteralPath $log -Encoding UTF8 -Value ('{0} [INFO] Launcher stopped.' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
        exit 0
    }
}
Start-Sleep -Seconds 30
