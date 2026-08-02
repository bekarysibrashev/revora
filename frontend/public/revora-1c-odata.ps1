[CmdletBinding()]
param(
    [switch]$Setup,
    [string]$RevoraApiUrl,
    [string]$OneCBaseUrl = "http://localhost/revora_odata/odata/standard.odata",
    [string]$ConfigPath = "$env:LOCALAPPDATA\Revora\one-c-odata.xml",
    [ValidateRange(10, 500)]
    [int]$PageSize = 200
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ApprovedEntities = @(
    "AccumulationRegister_Выручка_RecordType",
    "AccumulationRegister_ДенежныеСредства_RecordType",
    "AccumulationRegister_Затраты_RecordType",
    "AccumulationRegister_НарядЗаказы_RecordType",
    "AccumulationRegister_Продажи_RecordType",
    "AccumulationRegister_ПродажиСебестоимость_RecordType",
    "AccumulationRegister_РабочееВремяСотрудников_RecordType",
    "AccumulationRegister_РасчетыСПерсоналом_RecordType"
)

function ConvertFrom-ProtectedString {
    param([Security.SecureString]$Value)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Assert-ConnectorUrls {
    param([string]$ApiUrl, [string]$ODataUrl)

    $apiUri = [Uri]$ApiUrl
    if ($apiUri.Scheme -ne "https" -and $apiUri.Host -notin @("localhost", "127.0.0.1")) {
        throw "Revora API must use HTTPS."
    }

    $odataUri = [Uri]$ODataUrl
    if ($odataUri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "For safety, 1C OData must remain on localhost."
    }
}

function Assert-LocalODataUrl {
    param([string]$Url)

    $uri = [Uri]$Url
    if ($uri.Scheme -notin @("http", "https") -or $uri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Refusing to send the 1C credential outside localhost."
    }
}

function Save-ConnectorConfig {
    if (-not $RevoraApiUrl) {
        $RevoraApiUrl = Read-Host "Revora API URL (ends with /api/v1)"
    }
    Assert-ConnectorUrls -ApiUrl $RevoraApiUrl -ODataUrl $OneCBaseUrl

    Write-Host "Enter the dedicated read-only 1C username and password."
    $oneCCredential = Get-Credential
    $connectorToken = Read-Host "Paste the one-time Revora connector token" -AsSecureString

    $directory = Split-Path -Parent $ConfigPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [pscustomobject]@{
        RevoraApiUrl = $RevoraApiUrl.TrimEnd("/")
        OneCBaseUrl = $OneCBaseUrl.TrimEnd("/")
        OneCUsername = $oneCCredential.UserName
        OneCPassword = $oneCCredential.Password
        ConnectorToken = $connectorToken
        Entities = $ApprovedEntities
    } | Export-Clixml -LiteralPath $ConfigPath

    Write-Host "Configuration saved with Windows DPAPI: $ConfigPath"
    Write-Host "It can only be decrypted by this Windows user on this computer."
}

function Get-NextLink {
    param($Response)
    foreach ($name in @("odata.nextLink", "@odata.nextLink")) {
        $property = $Response.PSObject.Properties[$name]
        if ($null -ne $property -and $property.Value) { return [string]$property.Value }
    }
    if ($null -ne $Response.d -and $Response.d.__next) { return [string]$Response.d.__next }
    if ($Response.__next) { return [string]$Response.__next }
    return $null
}

function Get-ODataRecords {
    param([string]$Entity, [pscredential]$Credential, [string]$BaseUrl)

    $encodedEntity = [Uri]::EscapeDataString($Entity)
    $url = "$BaseUrl/$encodedEntity`?`$format=json&`$top=$PageSize"
    while ($url) {
        # 1C controls the pagination link. Validate every page so a malformed
        # response can never redirect the Basic credential to another host.
        Assert-LocalODataUrl -Url $url
        $response = Invoke-RestMethod -Method Get -Uri $url -Credential $Credential -Headers @{ Accept = "application/json" }
        if ($null -ne $response.value) {
            $records = @($response.value)
        }
        elseif ($null -ne $response.d -and $null -ne $response.d.results) {
            $records = @($response.d.results)
        }
        else {
            throw "Unexpected OData response for $Entity."
        }
        [pscustomobject]@{ Records = $records; NextLink = (Get-NextLink -Response $response) }
        $url = Get-NextLink -Response $response
    }
}

function Send-RevoraBatch {
    param([string]$Entity, [object[]]$Records, [string]$ApiUrl, [string]$Token)
    if ($Records.Count -eq 0) { return }

    $json = @{
        entity = $Entity
        records = $Records
        schema_version = "1c-odata-v3"
    } | ConvertTo-Json -Depth 30 -Compress
    $body = [Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Method Post -Uri "$ApiUrl/integrations/1c/push" `
        -Headers @{ Authorization = "Bearer $Token" } `
        -ContentType "application/json; charset=utf-8" -Body $body
}

if ($Setup) {
    Save-ConnectorConfig
    exit 0
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Connector is not configured. Run this script once with -Setup."
}

$config = Import-Clixml -LiteralPath $ConfigPath
Assert-ConnectorUrls -ApiUrl $config.RevoraApiUrl -ODataUrl $config.OneCBaseUrl
$oneCCredential = [pscredential]::new($config.OneCUsername, $config.OneCPassword)
$token = ConvertFrom-ProtectedString -Value $config.ConnectorToken

try {
    foreach ($entity in @($config.Entities)) {
        $received = 0
        foreach ($page in Get-ODataRecords -Entity $entity -Credential $oneCCredential -BaseUrl $config.OneCBaseUrl) {
            $records = @($page.Records)
            if ($records.Count -gt 0) {
                $result = Send-RevoraBatch -Entity $entity -Records $records -ApiUrl $config.RevoraApiUrl -Token $token
                $received += $records.Count
                Write-Host "${entity}: stored=$($result.records_stored), duplicates=$($result.records_duplicate)"
            }
        }
        Write-Host "${entity}: sent=$received"
    }
}
finally {
    $token = $null
}
