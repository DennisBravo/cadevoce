#requires -Version 5.1
<#
.SYNOPSIS
  Agente Cade Voce - posicao: (1) GPS USB serial NMEA se CADEVOCE_GPS_COM estiver definido;
  (2) GeoHelper.exe (Windows Location); (3) IP publico.

.NOTES
  Obrigatorias: CADEVOCE_API_URL, CADEVOCE_API_KEY (ou padrao local).
  Opcional: CADEVOCE_GEOHELPER_EXE - caminho do GeoHelper.exe (padrao: .\GeoHelper\publish\GeoHelper.exe).
  GPS USB (mais preciso em notebook): CADEVOCE_GPS_COM=COM3, CADEVOCE_GPS_BAUD=9600 (ou 4800/115200),
  CADEVOCE_GPS_TIMEOUT=25 (segundos para obter fix NMEA).
  GeoHelper: dotnet publish agent\GeoHelper (Release, win-x64, self-contained -> ./publish).
  Agendamento sugerido: 10 min, oculto (Task Scheduler).
#>

param()

$ErrorActionPreference = 'Stop'
$LogFile = Join-Path $env:TEMP 'cadevoce.log'
$MaxAccuracyMeters = 5000

if (-not $env:CADEVOCE_API_URL) {
    $ApiUrl = 'http://127.0.0.1:8000'
}
else {
    $ApiUrl = $env:CADEVOCE_API_URL.TrimEnd('/')
}

if (-not $env:CADEVOCE_API_KEY) {
    $ApiKey = 'ALTERE_ESTA_CHAVE'
}
else {
    $ApiKey = $env:CADEVOCE_API_KEY
}

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = 'INFO'
    )
    $line = '{0:u} [{1}] {2}' -f (Get-Date).ToUniversalTime(), $Level, $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-PublicIp {
    (Invoke-RestMethod -Uri 'https://api.ipify.org?format=json' -TimeoutSec 20).ip
}

<#
  Converte campo NMEA ddmm.mmmm ou dddmm.mmmm + hemisferio em graus decimais.
#>
function ConvertFrom-NmeaDm {
    param(
        [string]$Dm,
        [string]$Hemisphere
    )
    if ([string]::IsNullOrWhiteSpace($Dm)) { return [double]::NaN }
    $v = 0.0
    if (-not [double]::TryParse($Dm, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$v)) {
        return [double]::NaN
    }
    $deg = [math]::Floor($v / 100.0)
    $min = $v - ($deg * 100.0)
    $dec = $deg + ($min / 60.0)
    if ($Hemisphere -eq 'S' -or $Hemisphere -eq 'W') { $dec = -$dec }
    return $dec
}

<#
  Le frases NMEA ($GPGGA/$GNGGA ou $GPRMC/$GNRMC) na porta serial ate obter fix ou timeout.
  Retorna hashtable @{ lat; lon; accuracy } ou $null.
#>
function Get-NmeaFixFromSerial {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PortName,
        [int]$BaudRate = 9600,
        [int]$TimeoutSec = 25
    )
    $sp = New-Object System.IO.Ports.SerialPort
    $sp.PortName = $PortName
    $sp.BaudRate = $BaudRate
    $sp.Parity = [System.IO.Ports.Parity]::None
    $sp.DataBits = 8
    $sp.StopBits = [System.IO.Ports.StopBits]::One
    $sp.ReadTimeout = 800
    $sp.NewLine = "`r`n"
    $sp.Encoding = [System.Text.Encoding]::ASCII
    $sp.DtrEnable = $true
    try {
        $sp.Open()
    }
    catch {
        Write-Log -Message ('Serial {0}: nao abriu ({1})' -f $PortName, $_.Exception.Message) -Level 'WARN'
        return $null
    }
    try {
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        while ((Get-Date) -lt $deadline) {
            $line = $null
            try {
                $line = $sp.ReadLine()
            }
            catch [System.TimeoutException] {
                continue
            }
            catch {
                continue
            }
            if ($null -eq $line) { continue }
            $line = $line.Trim()
            if ($line.Length -lt 10) { continue }

            if ($line -match '^\$G[PN]GGA,') {
                $p = $line -split ','
                if ($p.Count -lt 10) { continue }
                $fixQ = -1
                if ($p[6] -match '^[0-9]+$') { $fixQ = [int]$p[6] }
                if ($fixQ -le 0) { continue }
                if ([string]::IsNullOrWhiteSpace($p[2]) -or [string]::IsNullOrWhiteSpace($p[4])) { continue }
                $la = ConvertFrom-NmeaDm -Dm $p[2] -Hemisphere $p[3]
                $lo = ConvertFrom-NmeaDm -Dm $p[4] -Hemisphere $p[5]
                if ([double]::IsNaN($la) -or [double]::IsNaN($lo)) { continue }
                $hdop = 0.0
                if (-not [string]::IsNullOrWhiteSpace($p[8])) {
                    $null = [double]::TryParse($p[8], [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$hdop)
                }
                # Estimativa grosseira: HDOP * ~5 m (tipico receptor barato); teto 80 m.
                $acc = if ($hdop -gt 0) { [math]::Max(3.0, [math]::Min($hdop * 5.0, 80.0)) } else { 18.0 }
                return @{ lat = $la; lon = $lo; accuracy = $acc }
            }

            if ($line -match '^\$G[PN]RMC,') {
                $p = $line -split ','
                if ($p.Count -lt 8) { continue }
                if ($p[2] -ne 'A') { continue }
                if ([string]::IsNullOrWhiteSpace($p[3]) -or [string]::IsNullOrWhiteSpace($p[5])) { continue }
                $la = ConvertFrom-NmeaDm -Dm $p[3] -Hemisphere $p[4]
                $lo = ConvertFrom-NmeaDm -Dm $p[5] -Hemisphere $p[6]
                if ([double]::IsNaN($la) -or [double]::IsNaN($lo)) { continue }
                return @{ lat = $la; lon = $lo; accuracy = 25.0 }
            }
        }
    }
    finally {
        if ($sp.IsOpen) { $sp.Close() }
        $sp.Dispose()
    }
    Write-Log -Message ('Serial {0}: timeout sem sentenca GGA/RMC valida' -f $PortName) -Level 'WARN'
    return $null
}

function Get-GeoHelperJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GeoExePath
    )

    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    try {
        $null = Start-Process -FilePath $GeoExePath -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
        $raw = [System.IO.File]::ReadAllText($tmpOut, [System.Text.Encoding]::UTF8).Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $null
        }
        return ($raw | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        Remove-Item -LiteralPath $tmpOut -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmpErr -ErrorAction SilentlyContinue
    }
}

try {
    $useGps = $false
    $lat = $null
    $lon = $null
    $acc = $null
    $publicIp = $null
    $gpsOrigin = $null

    $serialPort = $null
    if ($env:CADEVOCE_GPS_COM -and $env:CADEVOCE_GPS_COM.Trim()) {
        $serialPort = $env:CADEVOCE_GPS_COM.Trim()
    }
    $serialBaud = 9600
    if ($env:CADEVOCE_GPS_BAUD -and $env:CADEVOCE_GPS_BAUD.Trim()) {
        $baudParsed = 0
        if ([int]::TryParse($env:CADEVOCE_GPS_BAUD.Trim(), [ref]$baudParsed) -and $baudParsed -gt 0) {
            $serialBaud = $baudParsed
        }
    }
    $serialTimeout = 25
    if ($env:CADEVOCE_GPS_TIMEOUT -and $env:CADEVOCE_GPS_TIMEOUT.Trim()) {
        $toParsed = 0
        if ([int]::TryParse($env:CADEVOCE_GPS_TIMEOUT.Trim(), [ref]$toParsed) -and $toParsed -ge 5) {
            $serialTimeout = $toParsed
        }
    }

    if ($null -ne $serialPort) {
        $nmea = Get-NmeaFixFromSerial -PortName $serialPort -BaudRate $serialBaud -TimeoutSec $serialTimeout
        if ($null -ne $nmea) {
            $lat = [double]$nmea.lat
            $lon = [double]$nmea.lon
            $acc = [double]$nmea.accuracy
            if ($acc -lt $MaxAccuracyMeters -and $acc -gt 0) {
                $useGps = $true
                $gpsOrigin = 'serial'
                Write-Log -Message ('Fix NMEA na {0} ({1} baud) acc~{2}m' -f $serialPort, $serialBaud, [math]::Round($acc)) -Level 'INFO'
            }
        }
    }

    if (-not $useGps) {
        if ($env:CADEVOCE_GEOHELPER_EXE) {
            $geoExe = $env:CADEVOCE_GEOHELPER_EXE.Trim()
        }
        else {
            $geoExe = Join-Path -Path $PSScriptRoot -ChildPath 'GeoHelper\publish\GeoHelper.exe'
        }

        if (Test-Path -LiteralPath $geoExe) {
            try {
                $geoJson = Get-GeoHelperJson -GeoExePath $geoExe
                if ($null -ne $geoJson) {
                    if ($geoJson.error) {
                        Write-Log -Message ('GeoHelper: {0}' -f $geoJson.error) -Level 'WARN'
                    }
                    elseif (($null -ne $geoJson.lat) -and ($null -ne $geoJson.lon)) {
                        $lat = [double]$geoJson.lat
                        $lon = [double]$geoJson.lon
                        if ($null -ne $geoJson.accuracy) {
                            $acc = [double]$geoJson.accuracy
                        }
                        else {
                            $acc = [double]::NaN
                        }
                        if ($acc -ge $MaxAccuracyMeters -or [double]::IsNaN($acc) -or $acc -le 0) {
                            $msg = 'Precisao GPS fora do limite ou invalida ({0} m); usando IP' -f $acc
                            Write-Log -Message $msg -Level 'WARN'
                        }
                        else {
                            $useGps = $true
                            $gpsOrigin = 'windows'
                        }
                    }
                }
            }
            catch {
                Write-Log -Message ('GeoHelper falhou (parse/exec): {0}' -f $_.Exception.Message) -Level 'WARN'
            }
        }
        else {
            $msg = 'GeoHelper.exe nao encontrado: {0} - usando IP (compile com dotnet publish)' -f $geoExe
            Write-Log -Message $msg -Level 'WARN'
        }
    }

    if (-not $useGps) {
        $publicIp = Get-PublicIp
        if (-not $publicIp) {
            throw 'IP publico vazio'
        }
        $body = [ordered]@{
            hostname  = $env:COMPUTERNAME
            username  = $env:USERNAME
            source    = 'ip'
            latitude  = $null
            longitude = $null
            accuracy  = $null
            ip        = $publicIp
            timestamp = (Get-Date).ToUniversalTime().ToString('o')
        }
    }
    else {
        try {
            $publicIp = Get-PublicIp
        }
        catch {
            $publicIp = $null
        }
        $checkinSource = if ($gpsOrigin -eq 'serial') { 'gps_serial' } else { 'gps' }
        $body = [ordered]@{
            hostname  = $env:COMPUTERNAME
            username  = $env:USERNAME
            source    = $checkinSource
            latitude  = $lat
            longitude = $lon
            accuracy  = $acc
            ip        = $publicIp
            timestamp = (Get-Date).ToUniversalTime().ToString('o')
        }
    }

    $json = $body | ConvertTo-Json -Depth 5 -Compress

    # DEBUG temporario - teste local (remover apos validar)
    Write-Host ''
    Write-Host '=== CADEVOCE DEBUG ===' -ForegroundColor Cyan
    Write-Host ('  source (enviado):    {0}' -f $body.source)
    Write-Host ('  latitude capturada:  {0}' -f $(if ($null -ne $lat) { $lat } else { '(n/d)' }))
    Write-Host ('  longitude capturada: {0}' -f $(if ($null -ne $lon) { $lon } else { '(n/d)' }))
    Write-Host ('  accuracy (m):        {0}' -f $(if ($null -ne $acc) { $acc } else { '(n/d)' }))
    if ($gpsOrigin) {
        Write-Host ('  origem GPS:          {0}' -f $gpsOrigin) -ForegroundColor DarkCyan
    }
    Write-Host '  JSON enviado a API:'
    Write-Host ('  {0}' -f $json) -ForegroundColor DarkGray
    Write-Host '======================' -ForegroundColor Cyan
    Write-Host ''

    $headers = @{
        'Content-Type' = 'application/json'
        'X-API-Key'    = $ApiKey
    }

    $uri = '{0}/checkin' -f $ApiUrl
    Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $json -TimeoutSec 30 | Out-Null
    if ($useGps) {
        $via = if ($gpsOrigin -eq 'serial') { 'GNSS serial' } else { 'Windows Location' }
        Write-Log -Message ('Check-in OK GPS ({3}) lat={0} lon={1} acc={2}m' -f $lat, $lon, $acc, $via) -Level 'INFO'
    }
    else {
        Write-Log -Message ('Check-in OK IP ({0})' -f $publicIp) -Level 'INFO'
    }
}
catch {
    Write-Log -Message ('Falha: {0}' -f $_.Exception.Message) -Level 'ERROR'
    exit 1
}
