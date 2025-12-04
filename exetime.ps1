$times = @()  
for ($i = 1; $i -le 10; $i++) {  
    $elapsed = (Measure-Command { az --help }).TotalSeconds  
    $times += $elapsed  
}  
$average = ($times | Measure-Object -Average).Average  
Write-Host "Average execution time: $average seconds" 