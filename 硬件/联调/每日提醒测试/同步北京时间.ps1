param([string]$Port = 'COM7')

# Run after every power cycle; the computer clock must be correct.
# Close Arduino Serial Monitor before running this script.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Ports
$dailySerial = [System.IO.Ports.SerialPort]::new($Port, 115200)
$dailySerial.Encoding = [System.Text.Encoding]::ASCII
$dailySerial.DtrEnable = $false
$dailySerial.RtsEnable = $false
$dailySerial.ReadTimeout = 400
$dailySerial.WriteTimeout = 500
$dailyOutput = [System.Text.StringBuilder]::new()
try {
    $dailySerial.Open()
    Start-Sleep -Milliseconds 700
    $dailySerial.DiscardInBuffer()
    $beijingNow = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8))
    $timeText = $beijingNow.ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    $dailySerial.WriteLine('time ' + $timeText)
    $dailySerial.WriteLine('?')
    $dailyTimer = [Diagnostics.Stopwatch]::StartNew()
    while ($dailyTimer.ElapsedMilliseconds -lt 2500) {
        try {
            $dailyLine = $dailySerial.ReadLine()
            if ($dailyLine.Length -le 500) { [void]$dailyOutput.AppendLine($dailyLine.Trim()) }
            if ($dailyOutput.Length -gt 6000) { break }
        } catch [System.TimeoutException] {}
    }
    $result = $dailyOutput.ToString()
    Write-Output $result
    if (-not $result.Contains('TIME_OK')) { throw 'No TIME_OK received; confirm DailyReminderTest is running.' }
    if ($result.Contains('CHECK CLOCK') -or $result.Contains('STORAGE ERROR')) {
        throw 'Device reported a clock or storage error. Review the status above.'
    }
} finally {
    if ($dailySerial.IsOpen) { $dailySerial.Close() }
    $dailySerial.Dispose()
}
