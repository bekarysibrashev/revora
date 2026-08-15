[CmdletBinding(DefaultParameterSetName = "Run")]
param(
    [Parameter(ParameterSetName = "Setup", Mandatory = $true)]
    [switch]$Setup,

    [Parameter(ParameterSetName = "Setup", Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RevoraApiUrl,

    [Parameter(ParameterSetName = "Setup")]
    [ValidateNotNullOrEmpty()]
    [string]$OneCBaseUrl = "http://localhost/Revora/odata/standard.odata",

    [Parameter(ParameterSetName = "InstallTask", Mandatory = $true)]
    [switch]$InstallTask,

    [Parameter(ParameterSetName = "Test", Mandatory = $true)]
    [switch]$TestConnection,

    [Parameter(ParameterSetName = "Metadata", Mandatory = $true)]
    [switch]$DiscoverMetadata,

    [Parameter(ParameterSetName = "Run")]
    [switch]$FullSync,

    [Parameter(ParameterSetName = "Run")]
    [switch]$AllHistory,

    [string]$ConfigPath = "$env:LOCALAPPDATA\Revora\one-c-odata.xml",

    [ValidateRange(10, 500)]
    [int]$PageSize = 200,

    [ValidateRange(1, 3650)]
    [int]$HistoryDays = 90
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ConnectorDirectory = Split-Path -Parent $ConfigPath
$InstalledScriptPath = Join-Path $ConnectorDirectory "revora-1c-odata.ps1"
$StatePath = Join-Path $ConnectorDirectory "one-c-odata-state.xml"
$LogPath = Join-Path $ConnectorDirectory "one-c-odata.log"
$TaskName = "Revora 1C OData Sync"
$IncrementalOverlapDays = 7

# Kept as UTF-8 Base64 so this file works in Windows PowerShell 5.1 even when
# it is saved without a BOM on an older Windows server.
$ApprovedEntityBase64 = @(
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0JLRi9GA0YPRh9C60LBfUmVjb3JkVHlwZQ==",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0JTQtdC90LXQttC90YvQtdCh0YDQtdC00YHRgtCy0LBfUmVjb3JkVHlwZQ==",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0JfQsNGC0YDQsNGC0YtfUmVjb3JkVHlwZQ==",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0J3QsNGA0Y/QtNCX0LDQutCw0LfRi19SZWNvcmRUeXBl",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0J/RgNC+0LTQsNC20LhfUmVjb3JkVHlwZQ==",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0J/RgNC+0LTQsNC20LjQodC10LHQtdGB0YLQvtC40LzQvtGB0YLRjF9SZWNvcmRUeXBl",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0KDQsNCx0L7Rh9C10LXQktGA0LXQvNGP0KHQvtGC0YDRg9C00L3QuNC60L7Qsl9SZWNvcmRUeXBl",
    "QWNjdW11bGF0aW9uUmVnaXN0ZXJf0KDQsNGB0YfQtdGC0YvQodCf0LXRgNGB0L7QvdCw0LvQvtC8X1JlY29yZFR5cGU="
)
$ApprovedEntities = @($ApprovedEntityBase64 | ForEach-Object {
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_))
})

function Write-ConnectorLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR")][string]$Level = "INFO"
    )

    if (-not (Test-Path -LiteralPath $ConnectorDirectory)) {
        New-Item -ItemType Directory -Path $ConnectorDirectory -Force | Out-Null
    }
    if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
        $archive = "$LogPath.1"
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        Move-Item -LiteralPath $LogPath -Destination $archive -Force
    }
    $line = "{0} [{1}] {2}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

function ConvertFrom-ProtectedString {
    param([Parameter(Mandatory = $true)][Security.SecureString]$Value)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Assert-ConnectorUrls {
    param(
        [Parameter(Mandatory = $true)][string]$ApiUrl,
        [Parameter(Mandatory = $true)][string]$ODataUrl
    )

    $apiUri = [Uri]$ApiUrl
    if ($apiUri.Scheme -ne "https" -and $apiUri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Revora API must use HTTPS."
    }

    $odataUri = [Uri]$ODataUrl
    if ($odataUri.Scheme -notin @("http", "https") -or $odataUri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "1C OData must remain on localhost."
    }
}

function Assert-LocalODataUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    $uri = [Uri]$Url
    if ($uri.Scheme -notin @("http", "https") -or $uri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Refusing to send the 1C credential outside localhost."
    }
}

function Get-BasicAuthorizationValue {
    param([Parameter(Mandatory = $true)][pscredential]$Credential)

    $password = ConvertFrom-ProtectedString -Value $Credential.Password
    try {
        $raw = "{0}:{1}" -f $Credential.UserName, $password
        return "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw))
    }
    finally {
        $password = $null
        $raw = $null
    }
}

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Operation,
        [Parameter(Mandatory = $true)][string]$Description,
        [ValidateRange(1, 5)][int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return & $Operation
        }
        catch {
            if ($attempt -eq $Attempts) { throw }
            $delay = [Math]::Pow(2, $attempt)
            Write-ConnectorLog -Level "WARN" -Message "$Description failed (attempt $attempt/$Attempts). Retry in $delay seconds."
            Start-Sleep -Seconds $delay
        }
    }
}

function Save-ConnectorConfig {
    Assert-ConnectorUrls -ApiUrl $RevoraApiUrl -ODataUrl $OneCBaseUrl

    Write-Host "Enter the dedicated read-only 1C user (Revora) and its password."
    $oneCCredential = Get-Credential
    $connectorToken = Read-Host "Paste the Revora connector token" -AsSecureString
    if ($connectorToken.Length -eq 0) { throw "Connector token is required." }

    New-Item -ItemType Directory -Path $ConnectorDirectory -Force | Out-Null
    [pscustomobject]@{
        Version = 2
        RevoraApiUrl = $RevoraApiUrl.TrimEnd("/")
        OneCBaseUrl = $OneCBaseUrl.TrimEnd("/")
        OneCUsername = $oneCCredential.UserName
        OneCPassword = $oneCCredential.Password
        ConnectorToken = $connectorToken
        Entities = $ApprovedEntities
        PageSize = $PageSize
        HistoryDays = $HistoryDays
    } | Export-Clixml -LiteralPath $ConfigPath -Force

    $currentScript = $MyInvocation.ScriptName
    if ($currentScript -and ((Resolve-Path -LiteralPath $currentScript).Path -ne $InstalledScriptPath)) {
        Copy-Item -LiteralPath $currentScript -Destination $InstalledScriptPath -Force
    }

    Write-ConnectorLog -Message "Configuration saved with Windows DPAPI at $ConfigPath."
    Write-Host "Run this test next:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$InstalledScriptPath`" -TestConnection"
}

function Load-ConnectorConfig {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "Connector is not configured. Run the script with -Setup first."
    }
    $loaded = Import-Clixml -LiteralPath $ConfigPath
    Assert-ConnectorUrls -ApiUrl $loaded.RevoraApiUrl -ODataUrl $loaded.OneCBaseUrl
    return $loaded
}

function Get-NextLink {
    param($Response)

    foreach ($name in @("odata.nextLink", "@odata.nextLink")) {
        $property = $Response.PSObject.Properties[$name]
        if ($null -ne $property -and $property.Value) { return [string]$property.Value }
    }
    $dProperty = $Response.PSObject.Properties["d"]
    if ($null -ne $dProperty -and $null -ne $dProperty.Value) {
        $dNext = $dProperty.Value.PSObject.Properties["__next"]
        if ($null -ne $dNext -and $dNext.Value) { return [string]$dNext.Value }
    }
    $legacyNext = $Response.PSObject.Properties["__next"]
    if ($null -ne $legacyNext -and $legacyNext.Value) { return [string]$legacyNext.Value }
    return $null
}

function Resolve-ODataLink {
    param(
        [Parameter(Mandatory = $true)][string]$Link,
        [Parameter(Mandatory = $true)][string]$BaseUrl
    )

    $absolute = $null
    if ([Uri]::TryCreate($Link, [UriKind]::Absolute, [ref]$absolute)) {
        return $absolute.AbsoluteUri
    }
    return ([Uri]::new([Uri]($BaseUrl.TrimEnd("/") + "/"), $Link)).AbsoluteUri
}

function Invoke-OneCGet {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][pscredential]$Credential
    )

    Assert-LocalODataUrl -Url $Url
    $authorization = Get-BasicAuthorizationValue -Credential $Credential
    return Invoke-WithRetry -Description "1C OData request" -Operation {
        Invoke-RestMethod -Method Get -Uri $Url -MaximumRedirection 0 -TimeoutSec 300 -Headers @{
            Accept = "application/json"
            Authorization = $authorization
        }
    }
}

function Get-ODataPages {
    param(
        [Parameter(Mandatory = $true)][string]$Entity,
        [Parameter(Mandatory = $true)][pscredential]$Credential,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Nullable[datetime]]$ChangedSince,
        [Parameter(Mandatory = $true)][int]$ConfiguredPageSize
    )

    $encodedEntity = [Uri]::EscapeDataString($Entity)
    $queryUrl = "$BaseUrl/$encodedEntity`?`$format=json&`$top=$ConfiguredPageSize&allowedOnly=true"
    if ($null -ne $ChangedSince) {
        $dateText = ([datetime]$ChangedSince).ToString("yyyy-MM-ddTHH:mm:ss")
        $filter = [Uri]::EscapeDataString("Period ge datetime'$dateText'")
        $queryUrl += "&`$filter=$filter"
    }

    # 1C treats $top as the total result limit and does not necessarily emit
    # odata.nextLink. Page explicitly with $skip so a register containing more
    # than one batch is always read completely.
    $skip = 0
    $pageNumber = 0
    $previousFingerprint = $null
    while ($true) {
        $url = "$queryUrl&`$skip=$skip"
        $response = Invoke-OneCGet -Url $url -Credential $Credential
        $valueProperty = $response.PSObject.Properties["value"]
        $dProperty = $response.PSObject.Properties["d"]
        if ($null -ne $valueProperty) {
            $records = @($valueProperty.Value)
        }
        elseif ($null -ne $dProperty -and $null -ne $dProperty.Value) {
            $resultsProperty = $dProperty.Value.PSObject.Properties["results"]
            if ($null -eq $resultsProperty) { throw "Unexpected OData response for $Entity." }
            $records = @($resultsProperty.Value)
        }
        else {
            throw "Unexpected OData response for $Entity."
        }

        $pageNumber += 1
        if ($records.Count -gt 0) {
            $pageJson = $records | ConvertTo-Json -Depth 30 -Compress
            $sha = [Security.Cryptography.SHA256]::Create()
            try {
                $fingerprint = [Convert]::ToBase64String(
                    $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pageJson))
                )
            }
            finally {
                $sha.Dispose()
            }
            if ($null -ne $previousFingerprint -and $fingerprint -eq $previousFingerprint) {
                throw "1C returned the same OData page twice for $Entity; paging was stopped safely."
            }
            $previousFingerprint = $fingerprint
        }
        Write-ConnectorLog -Message "${Entity}: page=$pageNumber, read=$($records.Count), offset=$skip"
        Write-Output -NoEnumerate ([pscustomobject]@{ Records = $records })
        if ($records.Count -lt $ConfiguredPageSize) { break }
        $skip += $records.Count
    }
}

function Send-RevoraBatch {
    param(
        [Parameter(Mandatory = $true)][string]$Entity,
        [Parameter(Mandatory = $true)][object[]]$Records,
        [Parameter(Mandatory = $true)][string]$ApiUrl,
        [Parameter(Mandatory = $true)][string]$Token
    )

    if ($Records.Count -eq 0) { return $null }
    $json = @{
        entity = $Entity
        records = $Records
        schema_version = "1c-odata-v3"
    } | ConvertTo-Json -Depth 30 -Compress
    $body = [Text.Encoding]::UTF8.GetBytes($json)

    return Invoke-WithRetry -Description "Revora upload" -Operation {
        Invoke-RestMethod -Method Post -Uri "$ApiUrl/integrations/1c/push" -MaximumRedirection 0 -TimeoutSec 300 `
            -Headers @{ Authorization = "Bearer $Token" } `
            -ContentType "application/json; charset=utf-8" -Body $body
    }
}

function Get-OneCMetadataInventory {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][pscredential]$Credential
    )

    $metadataUrl = "$BaseUrl/`$metadata"
    Assert-LocalODataUrl -Url $metadataUrl
    $authorization = Get-BasicAuthorizationValue -Credential $Credential
    $response = Invoke-WithRetry -Description "1C metadata discovery" -Operation {
        Invoke-WebRequest -UseBasicParsing -Method Get -Uri $metadataUrl -MaximumRedirection 0 -TimeoutSec 300 `
            -Headers @{ Authorization = $authorization; Accept = "application/xml" }
    }
    try {
        [xml]$document = $response.Content
    }
    catch {
        throw "1C returned invalid OData metadata XML."
    }

    $typeIndex = @{}
    foreach ($schema in @($document.SelectNodes("//*[local-name()='Schema']"))) {
        $namespace = [string]$schema.GetAttribute("Namespace")
        foreach ($entityType in @($schema.SelectNodes("./*[local-name()='EntityType']"))) {
            $typeName = [string]$entityType.GetAttribute("Name")
            $qualifiedName = if ($namespace) { "$namespace.$typeName" } else { $typeName }
            $typeIndex[$qualifiedName] = $entityType
        }
    }

    $entities = @()
    foreach ($entitySet in @($document.SelectNodes("//*[local-name()='EntityContainer']/*[local-name()='EntitySet']"))) {
        $name = [string]$entitySet.GetAttribute("Name")
        $entityTypeName = [string]$entitySet.GetAttribute("EntityType")
        if (-not $name -or -not $entityTypeName) { continue }
        $entityType = $typeIndex[$entityTypeName]
        $properties = @()
        $navigation = @()
        if ($null -ne $entityType) {
            foreach ($property in @($entityType.SelectNodes("./*[local-name()='Property']"))) {
                $nullableText = [string]$property.GetAttribute("Nullable")
                $nullable = $null
                if ($nullableText -in @("true", "false")) { $nullable = [bool]::Parse($nullableText) }
                $properties += [ordered]@{
                    name = [string]$property.GetAttribute("Name")
                    type = [string]$property.GetAttribute("Type")
                    nullable = $nullable
                }
            }
            foreach ($item in @($entityType.SelectNodes("./*[local-name()='NavigationProperty']"))) {
                $navigation += [ordered]@{
                    name = [string]$item.GetAttribute("Name")
                    relationship = if ($item.HasAttribute("Relationship")) { [string]$item.GetAttribute("Relationship") } else { $null }
                    target_type = if ($item.HasAttribute("Type")) { [string]$item.GetAttribute("Type") } else { $null }
                }
            }
        }
        $entities += [ordered]@{
            name = $name
            entity_type = $entityTypeName
            properties = @($properties)
            navigation_properties = @($navigation)
        }
    }
    if ($entities.Count -eq 0) {
        throw "No EntitySet definitions were found in 1C OData metadata."
    }
    return @($entities | Sort-Object { $_.name })
}

function Send-RevoraMetadata {
    param($Config)

    $credential = [pscredential]::new($Config.OneCUsername, $Config.OneCPassword)
    $entities = @(Get-OneCMetadataInventory -BaseUrl $Config.OneCBaseUrl -Credential $credential)
    $token = ConvertFrom-ProtectedString -Value $Config.ConnectorToken
    try {
        $json = @{
            schema_version = "1c-odata-metadata-v1"
            entities = $entities
        } | ConvertTo-Json -Depth 30 -Compress
        $body = [Text.Encoding]::UTF8.GetBytes($json)
        $result = Invoke-WithRetry -Description "Revora metadata upload" -Operation {
            Invoke-RestMethod -Method Post -Uri "$($Config.RevoraApiUrl)/integrations/1c/metadata" `
                -MaximumRedirection 0 -TimeoutSec 300 `
                -Headers @{ Authorization = "Bearer $token" } `
                -ContentType "application/json; charset=utf-8" -Body $body
        }
        Write-ConnectorLog -Message "OData metadata uploaded: entities=$($result.entity_count), properties=$($result.property_count), fingerprint=$($result.fingerprint)."
        return $result
    }
    finally {
        $token = $null
    }
}

function Test-Connector {
    param($Config)

    $credential = [pscredential]::new($Config.OneCUsername, $Config.OneCPassword)
    $metadataUrl = "$($Config.OneCBaseUrl)/`$metadata"
    $authorization = Get-BasicAuthorizationValue -Credential $credential
    Assert-LocalODataUrl -Url $metadataUrl
    Invoke-WithRetry -Description "1C metadata test" -Operation {
        Invoke-WebRequest -UseBasicParsing -Method Get -Uri $metadataUrl -MaximumRedirection 0 -TimeoutSec 300 `
            -Headers @{ Authorization = $authorization } | Out-Null
    }

    $entity = @($Config.Entities)[0]
    $encodedEntity = [Uri]::EscapeDataString($entity)
    $probeUrl = "$($Config.OneCBaseUrl)/$encodedEntity`?`$format=json&`$top=1&allowedOnly=true"
    $probe = Invoke-OneCGet -Url $probeUrl -Credential $credential
    if ($null -eq $probe.PSObject.Properties["value"] -and $null -eq $probe.PSObject.Properties["d"]) {
        throw "1C returned an unexpected test response."
    }
    Send-RevoraMetadata -Config $Config | Out-Null
    Write-ConnectorLog -Message "Connection test passed: OData metadata and first approved register are readable."
}

function Install-ConnectorTask {
    if (-not (Test-Path -LiteralPath $InstalledScriptPath)) {
        throw "Run -Setup first so the connector is copied to $InstalledScriptPath."
    }

    Write-Host "Enter the Windows account that must run the connector even when nobody is logged in."
    Write-Host "Use the SAME Windows account that ran -Setup, otherwise DPAPI cannot decrypt the config."
    $taskCredential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" -Message "Windows Task Scheduler account"
    $expectedUsers = @($env:USERNAME, "$env:USERDOMAIN\$env:USERNAME", "$env:COMPUTERNAME\$env:USERNAME")
    if ($taskCredential.UserName -notin $expectedUsers) {
        throw "The scheduled task account must be the same Windows user that ran -Setup."
    }

    $taskPassword = ConvertFrom-ProtectedString -Value $taskCredential.Password
    try {
        $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$InstalledScriptPath`" -ConfigPath `"$ConfigPath`""
        $action = New-ScheduledTaskAction -Execute "$PSHOME\powershell.exe" -Argument $arguments -WorkingDirectory $ConnectorDirectory
        $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
            -RepetitionInterval (New-TimeSpan -Hours 3) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
            -Description "Reads local 1C OData and uploads approved records to Revora every 3 hours." `
            -User $taskCredential.UserName -Password $taskPassword -RunLevel Highest -Force | Out-Null
    }
    finally {
        $taskPassword = $null
    }

    Write-ConnectorLog -Message "Scheduled task '$TaskName' installed for every 3 hours."
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "The first scheduled run was started. Check the log: $LogPath"
}

function Read-LastSuccessfulSync {
    if (-not (Test-Path -LiteralPath $StatePath)) { return $null }
    try {
        $state = Import-Clixml -LiteralPath $StatePath
        if ($state.LastSuccessfulUtc) { return [datetime]$state.LastSuccessfulUtc }
    }
    catch {
        Write-ConnectorLog -Level "WARN" -Message "State file could not be read; a full sync will be used."
    }
    return $null
}

function Save-LastSuccessfulSync {
    param([Parameter(Mandatory = $true)][datetime]$StartedUtc)

    $temporaryPath = "$StatePath.tmp"
    [pscustomobject]@{ LastSuccessfulUtc = $StartedUtc.ToString("o") } |
        Export-Clixml -LiteralPath $temporaryPath -Force
    Move-Item -LiteralPath $temporaryPath -Destination $StatePath -Force
}

function Invoke-ConnectorSync {
    param($Config, [switch]$ForceFull, [switch]$ForceAllHistory)

    $mutex = [Threading.Mutex]::new($false, "Local\RevoraOneCODataConnector")
    $lockTaken = $false
    try {
        $lockTaken = $mutex.WaitOne(0)
        if (-not $lockTaken) {
            Write-ConnectorLog -Level "WARN" -Message "Another connector run is still active; this run was skipped."
            return
        }

        $startedUtc = [datetime]::UtcNow
        $lastSuccessful = Read-LastSuccessfulSync
        $changedSince = $null
        $historyDaysProperty = $Config.PSObject.Properties["HistoryDays"]
        $configuredHistoryDays = if ($null -ne $historyDaysProperty -and $historyDaysProperty.Value) {
            [int]$historyDaysProperty.Value
        }
        else {
            $HistoryDays
        }

        if ($ForceAllHistory) {
            Write-ConnectorLog -Message "All-history sync started by explicit request."
        }
        elseif ($ForceFull -or $null -eq $lastSuccessful) {
            $changedSince = [datetime]::UtcNow.AddDays(-$configuredHistoryDays)
            Write-ConnectorLog -Message "Full sync for the last $configuredHistoryDays days started."
        }
        else {
            $changedSince = $lastSuccessful.ToUniversalTime().AddDays(-$IncrementalOverlapDays)
            Write-ConnectorLog -Message "Incremental sync started with a $IncrementalOverlapDays-day overlap."
        }

        $credential = [pscredential]::new($Config.OneCUsername, $Config.OneCPassword)
        $token = ConvertFrom-ProtectedString -Value $Config.ConnectorToken
        $configuredPageSize = if ($Config.PageSize) { [int]$Config.PageSize } else { $PageSize }
        $totalSent = 0
        $totalStored = 0
        $totalDuplicates = 0

        try {
            foreach ($entity in @($Config.Entities)) {
                $entitySent = 0
                foreach ($page in Get-ODataPages -Entity $entity -Credential $credential `
                    -BaseUrl $Config.OneCBaseUrl -ChangedSince $changedSince -ConfiguredPageSize $configuredPageSize) {
                    $records = @($page.Records)
                    if ($records.Count -eq 0) { continue }
                    $result = Send-RevoraBatch -Entity $entity -Records $records -ApiUrl $Config.RevoraApiUrl -Token $token
                    $entitySent += $records.Count
                    $totalSent += $records.Count
                    $totalStored += [int]$result.records_stored
                    $totalDuplicates += [int]$result.records_duplicate
                }
                Write-ConnectorLog -Message "${entity}: sent=$entitySent"
            }
        }
        finally {
            $token = $null
        }

        Save-LastSuccessfulSync -StartedUtc $startedUtc
        Write-ConnectorLog -Message "Sync completed: sent=$totalSent, stored=$totalStored, duplicates=$totalDuplicates."
    }
    catch {
        Write-ConnectorLog -Level "ERROR" -Message $_.Exception.Message
        throw
    }
    finally {
        if ($lockTaken) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

if ($Setup) {
    Save-ConnectorConfig
    exit 0
}

if ($InstallTask) {
    Install-ConnectorTask
    exit 0
}

$config = Load-ConnectorConfig
if ($TestConnection) {
    Test-Connector -Config $config
    exit 0
}

if ($DiscoverMetadata) {
    Send-RevoraMetadata -Config $config | Out-Null
    exit 0
}

Invoke-ConnectorSync -Config $config -ForceFull:$FullSync -ForceAllHistory:$AllHistory
