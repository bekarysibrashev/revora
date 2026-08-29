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

    [Parameter(ParameterSetName = "Run")]
    [string]$ResumeEntity,

    [Parameter(ParameterSetName = "Run")]
    [ValidateRange(0, 100000000)]
    [int]$ResumeOffset = 0,

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
$ApprovedEntityDefinitionBase64 = @(
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUs0JrQsNGB0YHQsF9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQntGA0LPQsNC90LjQt9Cw0YbQuNGPX0tleSzQotC40L/QlNC10L3QtdC20L3Ri9GF0KHRgNC10LTRgdGC0LIs0JLQuNC00J7Qv9C10YDQsNGG0LjQuCzQmtC+0L3RgtGA0LDQs9C10L3Rgl9LZXks0JrRg9GA0LDRgtC+0YBfS2V5LNCh0YPQvNC80LAsUmVjb3JkZXJfVHlwZSIsImVudGl0eSI6IkFjY3VtdWxhdGlvblJlZ2lzdGVyX9CS0YvRgNGD0YfQutCwX1JlY29yZFR5cGUiLCJkYXRlX2ZpZWxkIjoiUGVyaW9kIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUsUmVjb3JkVHlwZSzQodGC0YDRg9C60YLRg9GA0L3QsNGP0JXQtNC40L3QuNGG0LBfS2V5LNCi0LjQv9CU0LXQvdC10LbQvdGL0YXQodGA0LXQtNGB0YLQsizQodGD0LzQvNCwLNCh0YLQsNGC0YzRj9CU0JTQoV9LZXksUmVjb3JkZXJfVHlwZSIsImVudGl0eSI6IkFjY3VtdWxhdGlvblJlZ2lzdGVyX9CU0LXQvdC10LbQvdGL0LXQodGA0LXQtNGB0YLQstCwX1JlY29yZFR5cGUiLCJkYXRlX2ZpZWxkIjoiUGVyaW9kIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUs0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQndC+0LzQtdC90LrQu9Cw0YLRg9GA0LBfS2V5LNCa0L7QvdGC0YDQsNCz0LXQvdGCX0tleSzQodC+0YLRgNGD0LTQvdC40LpfS2V5LNCh0YLQsNGC0YzRj9CX0LDRgtGA0LDRgizQodGD0LzQvNCwLFJlY29yZGVyX1R5cGUs0KHRgtCw0YLRjNGP0JfQsNGC0YDQsNGCX1R5cGUiLCJlbnRpdHkiOiJBY2N1bXVsYXRpb25SZWdpc3Rlcl/Ql9Cw0YLRgNCw0YLRi19SZWNvcmRUeXBlIiwiZGF0ZV9maWVsZCI6IlBlcmlvZCIsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUsUmVjb3JkVHlwZSzQodGC0YDRg9C60YLRg9GA0L3QsNGP0JXQtNC40L3QuNGG0LBfS2V5LNCd0L7QvNC10L3QutC70LDRgtGD0YDQsF9LZXks0JrQvtC90YLRgNCw0LPQtdC90YJfS2V5LNCd0LDRgNGP0LTQl9Cw0LrQsNC3X0tleSzQndC+0LzQtdGA0JfQsNC60LDQt9CwLNCa0L7Qu9C40YfQtdGB0YLQstC+LNCa0LvRjtGH0KHRgtGA0L7QutC4LFJlY29yZGVyX1R5cGUiLCJlbnRpdHkiOiJBY2N1bXVsYXRpb25SZWdpc3Rlcl/QndCw0YDRj9C00JfQsNC60LDQt9GLX1JlY29yZFR5cGUiLCJkYXRlX2ZpZWxkIjoiUGVyaW9kIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUs0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQndC+0LzQtdC90LrQu9Cw0YLRg9GA0LBfS2V5LNCU0L7QutGD0LzQtdC90YLQn9GA0L7QtNCw0LbQuCzQodC+0YLRgNGD0LTQvdC40LpfS2V5LNCa0L7QvdGC0YDQsNCz0LXQvdGCX0tleSzQmtC+0LvQuNGH0LXRgdGC0LLQvizQodGC0L7QuNC80L7RgdGC0Yws0KHRgtC+0LjQvNC+0YHRgtGM0JHQtdC30KHQutC40LTQutC4LNCh0YPQvNC80LDQndCU0KEsUmVjb3JkZXJfVHlwZSzQlNC+0LrRg9C80LXQvdGC0J/RgNC+0LTQsNC20LhfVHlwZSIsImVudGl0eSI6IkFjY3VtdWxhdGlvblJlZ2lzdGVyX9Cf0YDQvtC00LDQttC4X1JlY29yZFR5cGUiLCJkYXRlX2ZpZWxkIjoiUGVyaW9kIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUs0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQndC+0LzQtdC90LrQu9Cw0YLRg9GA0LBfS2V5LNCc0LDRgtC10YDQuNCw0LtfS2V5LNCU0L7QutGD0LzQtdC90YLQn9GA0L7QtNCw0LbQuCzQmtC+0L3RgtGA0LDQs9C10L3Rgl9LZXks0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQmtC+0LvQuNGH0LXRgdGC0LLQvizQodGC0L7QuNC80L7RgdGC0Yws0KHRg9C80LzQsNCd0JTQoSxSZWNvcmRlcl9UeXBlLNCU0L7QutGD0LzQtdC90YLQn9GA0L7QtNCw0LbQuF9UeXBlIiwiZW50aXR5IjoiQWNjdW11bGF0aW9uUmVnaXN0ZXJf0J/RgNC+0LTQsNC20LjQodC10LHQtdGB0YLQvtC40LzQvtGB0YLRjF9SZWNvcmRUeXBlIiwiZGF0ZV9maWVsZCI6IlBlcmlvZCIsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcl9LZXksUGVyaW9kLExpbmVOdW1iZXIsQWN0aXZlLNCh0YLRgNGD0LrRgtGD0YDQvdCw0Y/QldC00LjQvdC40YbQsF9LZXks0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQktGA0LDRh19LZXks0JTQvdC10Lks0KfQsNGB0L7QsiIsImVudGl0eSI6IkFjY3VtdWxhdGlvblJlZ2lzdGVyX9Cg0LDQsdC+0YfQtdC10JLRgNC10LzRj9Ch0L7RgtGA0YPQtNC90LjQutC+0LJfUmVjb3JkVHlwZSIsImRhdGVfZmllbGQiOiJQZXJpb2QiLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWNvcmRlcixQZXJpb2QsTGluZU51bWJlcixBY3RpdmUsUmVjb3JkVHlwZSzQodGC0YDRg9C60YLRg9GA0L3QsNGP0JXQtNC40L3QuNGG0LBfS2V5LNCh0L7RgtGA0YPQtNC90LjQul9LZXks0JzQtdGB0Y/RhtCd0LDRh9C40YHQu9C10L3QuNGPLNCU0L7QutGD0LzQtdC90YLQndCw0YfQuNGB0LvQtdC90LjRj19LZXks0KHRg9C80LzQsCxSZWNvcmRlcl9UeXBlIiwiZW50aXR5IjoiQWNjdW11bGF0aW9uUmVnaXN0ZXJf0KDQsNGB0YfQtdGC0YvQodCf0LXRgNGB0L7QvdCw0LvQvtC8X1JlY29yZFR5cGUiLCJkYXRlX2ZpZWxkIjoiUGVyaW9kIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjoi0KLQtdC70LXRhNC+0L0iLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLERlbGV0aW9uTWFyayzQlNCw0YLQsNCg0LXQs9C40YHRgtGA0LDRhtC40Lgs0JjRgdGC0L7Rh9C90LjQutCY0L3RhNC+0YDQvNCw0YbQuNC4X0tleSzQmtCw0L3QsNC70J/RgNC40LLQu9C10YfQtdC90LjRj19LZXks0JrQsNC90LDQu9Cf0YDQuNCy0LvQtdGH0LXQvdC40Y/Ql9C90LDRh9C10L3QuNC1LNCh0L7RgtGA0YPQtNC90LjQutCg0LXQs9C40YHRgtGA0LDRhtC40LhfS2V5LNCh0YLRgNGD0LrRgtGD0YDQvdCw0Y/QldC00LjQvdC40YbQsF9LZXks0KLQtdC70LXRhNC+0L0iLCJlbnRpdHkiOiJDYXRhbG9nX9Ca0L7QvdGC0YDQsNCz0LXQvdGC0YsiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjoiRGVsZXRpb25NYXJrIGVxIGZhbHNlIn0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLERlbGV0aW9uTWFyayzQlNC+0LvQttC90L7RgdGC0YxfS2V5LNCY0LzRjyzQntGC0YfQtdGB0YLQstC+LNCk0LDQvNC40LvQuNGPLNCd0LDQuNC80LXQvdC+0LLQsNC90LjQtdCh0L7QutGA0LDRidC10L3QvdC+0LUs0J/RgNC10LTRgdGC0LDQstC70LXQvdC40LXQlNC70Y/QntC90LvQsNC50L3Ql9Cw0L/QuNGB0Lgs0KDQvtC70Yws0KHQu9GD0LbQtdCx0L3Ri9C5IiwiZW50aXR5IjoiQ2F0YWxvZ1/QodC+0YLRgNGD0LTQvdC40LrQuCIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOiJEZWxldGlvbk1hcmsgZXEgZmFsc2UgYW5kINCh0LvRg9C20LXQsdC90YvQuSBlcSBmYWxzZSJ9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLERlbGV0aW9uTWFyayzQndCw0LjQvNC10L3QvtCy0LDQvdC40LXQn9C+0LvQvdC+0LUs0KHQv9C10YbQuNCw0LvQuNC30LDRhtC40Y9fS2V5LNCi0LjQv9Cd0L7QvNC10L3QutC70LDRgtGD0YDRiyzQndC+0YDQvNCw0JLRgNC10LzQtdC90Lgs0K3RgtC+0KPRgdC70YPQs9CwLNCt0YLQvtCX0LDQv9Cw0YEiLCJlbnRpdHkiOiJDYXRhbG9nX9Cd0L7QvNC10L3QutC70LDRgtGD0YDQsCIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOiJEZWxldGlvbk1hcmsgZXEgZmFsc2UgYW5kINCt0YLQvtCj0YHQu9GD0LPQsCBlcSB0cnVlIn0=",
    "eyJwcm90ZWN0X3Bob25lIjoi0J3QvtC80LXRgNCi0LXQu9C10YTQvtC90LAiLCJzZWxlY3QiOiJSZWZfS2V5LERlbGV0aW9uTWFyayx1dG1fY2FtcGFpZ24sdXRtX2NvbnRlbnQsdXRtX21lZGl1bSx1dG1fc291cmNlLHV0bV90ZXJtLNCU0LDRgtCw0J7QsdGA0LDQsdC+0YLQutC4LNCU0LDRgtCw0KHQvtC30LTQsNC90LjRjyzQmtCw0L3QsNC70J/RgNC40LLQu9C10YfQtdC90LjRj19LZXks0JrQsNC90LDQu9Cf0YDQuNCy0LvQtdGH0LXQvdC40Y/Ql9C90LDRh9C10L3QuNC1LNCd0L7QvNC10YDQotC10LvQtdGE0L7QvdCwLNCe0YHQvdC+0LLQvdC+0LnQmtC70LjQtdC90YJfS2V5LNCe0YHQvdC+0LLQvdC+0LnQnNC10L3QtdC00LbQtdGAX0tleSzQoNC10LrQu9Cw0LzQvdGL0LnQmNGB0YLQvtGH0L3QuNC6X0tleSzQodGC0LDRgtGD0YEs0KHRgtCw0YLRg9GB0J/QsNGG0LjQtdC90YLQsCzQodGC0YDRg9C60YLRg9GA0L3QsNGP0JXQtNC40L3QuNGG0LBfS2V5LNCd0LDQv9GA0LDQstC70LXQvdC40LVfS2V5LNCa0LDRgtC10LPQvtGA0LjRj19LZXkiLCJlbnRpdHkiOiJDYXRhbG9nX9CX0LDRj9Cy0LrQuCIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOiJEZWxldGlvbk1hcmsgZXEgZmFsc2UifQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JLRgNCw0YdfS2V5LNCU0LDRgtCw0J7QutC+0L3Rh9Cw0L3QuNGPLNCU0LDRgtCw0KHQvtC30LTQsNC90LjRjyzQmNGB0YLQvtGH0L3QuNC60JfQsNC/0LjRgdC4X0tleSzQmtC+0L3RgtGA0LDQs9C10L3Rgl9LZXks0J/RgNC40YfQuNC90LDQntGC0LzQtdC90YtfS2V5LNCh0LTQtdC70LrQsF9LZXks0KHRgdGL0LvQutCw0J3QsNCf0YDQuNC10LxfS2V5LNCh0YLQsNGC0YPRgSzQodGC0LDRgtGD0YHQn9Cw0YbQuNC10L3RgtCwLNCh0YLRgNGD0LrRgtGD0YDQvdCw0Y/QldC00LjQvdC40YbQsF9LZXks0KLQuNC/0KHQvtCx0YvRgtC40Y8iLCJlbnRpdHkiOiJEb2N1bWVudF/QodC+0LHRi9GC0LjQtSIsImRhdGVfZmllbGQiOiJEYXRlIiwic3RhdGljX2ZpbHRlciI6IkRlbGV0aW9uTWFyayBlcSBmYWxzZSJ9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JrQvtC90YLRgNCw0LPQtdC90YJfS2V5LNCa0YPRgNCw0YLQvtGAX0tleSzQodC+0YLRgNGD0LTQvdC40LpfS2V5LNCh0YLQsNGC0YPRgSzQodGC0YDRg9C60YLRg9GA0L3QsNGP0JXQtNC40L3QuNGG0LBfS2V5LNCh0YPQvNC80LDQlNC+0LrRg9C80LXQvdGC0LAs0KHRg9C80LzQsNCe0L/Qu9Cw0YfQtdC90L4iLCJlbnRpdHkiOiJEb2N1bWVudF/Qn9C70LDQvdCb0LXRh9C10L3QuNGPIiwiZGF0ZV9maWVsZCI6IkRhdGUiLCJzdGF0aWNfZmlsdGVyIjoiRGVsZXRpb25NYXJrIGVxIGZhbHNlIn0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJ1dG1DYW1wYWlnbix1dG1Db250ZW50LHV0bU1lZGl1bSx1dG1Tb3VyY2UsdXRtVGVybSzQlNCw0YLQsCzQodGD0LzQvNCwIiwiZW50aXR5IjoiSW5mb3JtYXRpb25SZWdpc3Rlcl/QoNC10LrQu9Cw0LzQvdGL0LXQoNCw0YHRhdC+0LTRiyIsImRhdGVfZmllbGQiOiLQlNCw0YLQsCIsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JTQsNGC0LDQndCw0YfQsNC70LDQn9C10YDQuNC+0LTQsCzQlNCw0YLQsNCe0LrQvtC90YfQsNC90LjRj9Cf0LXRgNC40L7QtNCwLNCh0L7RgtGA0YPQtNC90LjQul9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCh0YLQsNGC0YzRj9Cg0LDRgdGF0L7QtNC+0LJfS2V5IiwiZW50aXR5IjoiRG9jdW1lbnRf0J3QsNGH0LjRgdC70LXQvdC40LXQl9Cw0YDQv9C70LDRgtGLIiwiZGF0ZV9maWVsZCI6IkRhdGUiLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJzdGF0aWNfZmlsdGVyIjoiRGVsZXRpb25NYXJrIGVxIGZhbHNlIiwiZGF0ZV9maWVsZCI6bnVsbCwicHJvdGVjdF9waG9uZSI6bnVsbCwic2VsZWN0IjoiUmVmX0tleSxEZXNjcmlwdGlvbixDb2RlLERlbGV0aW9uTWFyayIsImVudGl0eSI6IkNhdGFsb2df0KHRgtGA0YPQutGC0YPRgNC90YvQtdCV0LTQuNC90LjRhtGLIn0="
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQmtC+0LQs0J3QsNGH0LjRgdC70LXQvdC40LXQo9C00LXRgNC20LDQvdC40LVfS2V5LNCf0LXRgNC40L7QtNChLNCf0LXRgNC40L7QtNCf0L4s0KHRg9C80LzQsCIsImVudGl0eSI6IkRvY3VtZW50X9Cd0LDRh9C40YHQu9C10L3QuNC10JfQsNGA0L/Qu9Cw0YLRi1/QoNCw0YHRh9C10YLQl9Cw0YDQv9C70LDRgtGLIiwiZGF0ZV9maWVsZCI6ItCf0LXRgNC40L7QtNCf0L4iLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ=="
)
$ApprovedEntityDefinitions = @($ApprovedEntityDefinitionBase64 | ForEach-Object {
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) | ConvertFrom-Json
})
$AdditionalEntityDefinitionBase64 = @(
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLENvZGUsRGVsZXRpb25NYXJrLNCY0L3QuNGG0LjQsNGC0L7RgNCe0YLQvNC10L3RiyIsImVudGl0eSI6IkNhdGFsb2df0J/RgNC40YfQuNC90YvQntGC0LzQtdC90YvQl9Cw0L/QuNGB0LgiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjoiRGVsZXRpb25NYXJrIGVxIGZhbHNlIn0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0JTQsNGC0LAs0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQktC40LTQndCw0YfQuNGB0LvQtdC90LjRjyzQndC+0LzQtdC90LrQu9Cw0YLRg9GA0LBfS2V5LNCh0YPQvNC80LAs0KHRgtCw0YLRjNGP0KDQsNGB0YXQvtC00L7Qsl9LZXkiLCJlbnRpdHkiOiJEb2N1bWVudF/QndCw0YfQuNGB0LvQtdC90LjQtdCX0LDRgNC/0LvQsNGC0Ytf0JfQsNGC0YDQsNGC0YsiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JrQvtC90YLRgNCw0LPQtdC90YJfS2V5LNCh0L7RgtGA0YPQtNC90LjQul9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCh0YPQvNC80LDQntC/0LvQsNGH0LXQvdC+LNCh0YLQsNGC0YPRgdCf0LDRhtC40LXQvdGC0LAs0K3RgtC+0J/QtdGA0LLQuNGH0L3Ri9C50J/QsNGG0LjQtdC90YLQlNC70Y/QktGA0LDRh9CwIiwiZW50aXR5IjoiRG9jdW1lbnRf0J/RgNC40LXQvCIsImRhdGVfZmllbGQiOiJEYXRlIiwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0J3QvtC80LXQvdC60LvQsNGC0YPRgNCwX0tleSzQmtC+0LvQuNGH0LXRgdGC0LLQvizQptC10L3QsCzQodGD0LzQvNCwLNCS0YHQtdCz0L4s0KHQvtGC0YDRg9C00L3QuNC6X0tleSIsImVudGl0eSI6IkRvY3VtZW50X9Cf0YDQuNC10Lxf0JvQtdGH0LXQvdC40LUiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JrQvtC90YLRgNCw0LPQtdC90YJfS2V5LNCh0L7RgtGA0YPQtNC90LjQul9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCh0YPQvNC80LDQntC/0LvQsNGH0LXQvdC+IiwiZW50aXR5IjoiRG9jdW1lbnRf0KDQtdCw0LvQuNC30LDRhtC40Y8iLCJkYXRlX2ZpZWxkIjoiRGF0ZSIsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0J3QvtC80LXQvdC60LvQsNGC0YPRgNCwX0tleSzQmtC+0LvQuNGH0LXRgdGC0LLQvizQptC10L3QsCzQodGD0LzQvNCwLNCS0YHQtdCz0L4iLCJlbnRpdHkiOiJEb2N1bWVudF/QoNC10LDQu9C40LfQsNGG0LjRj1/Qo9GB0LvRg9Cz0LgiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JrQvtC90YLRgNCw0LPQtdC90YJfS2V5LNCh0YLQsNGC0YzRj9CX0LDRgtGA0LDRgl9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCh0YPQvNC80LDQntC/0LvQsNGH0LXQvdC+LNCa0L7QvNC80LXQvdGC0LDRgNC40LkiLCJlbnRpdHkiOiJEb2N1bWVudF/Qn9C+0YHRgtGD0L/Qu9C10L3QuNC1IiwiZGF0ZV9maWVsZCI6IkRhdGUiLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JLQuNC00J7Qv9C10YDQsNGG0LjQuCzQmtCw0YHRgdCwX0tleSzQkdCw0L3QutC+0LLRgdC60LjQudCh0YfQtdGCX0tleSzQmtC+0L3RgtGA0LDQs9C10L3RgizQodC+0YLRgNGD0LTQvdC40LpfS2V5LNCh0YLQsNGC0YzRj9CU0JTQoV9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCi0LjQv9CU0LXQvdC10LbQvdGL0YXQodGA0LXQtNGB0YLQsizQktC+0LfQstGA0LDRgtCS0YvQv9C70LDRgtGL0JfQn9Cc0LXRgdGP0YYiLCJlbnRpdHkiOiJEb2N1bWVudF/Qn9C+0YHRgtGD0L/Qu9C10L3QuNC10JTQtdC90LXQttC90YvRhdCh0YDQtdC00YHRgtCyIiwiZGF0ZV9maWVsZCI6IkRhdGUiLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQodGD0LzQvNCwLNCh0YLQsNGC0YzRj9CU0JTQoV9LZXks0JTQvtC60YPQvNC10L3RgtCe0YHQvdC+0LLQsNC90LjRjyzQlNC+0LrRg9C80LXQvdGC0J7RgdC90L7QstCw0L3QuNGPX1R5cGUiLCJlbnRpdHkiOiJEb2N1bWVudF/Qn9C+0YHRgtGD0L/Qu9C10L3QuNC10JTQtdC90LXQttC90YvRhdCh0YDQtdC00YHRgtCyX9Cg0LDRgdGI0LjRhNGA0L7QstC60LDQn9C70LDRgtC10LbQsCIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LE51bWJlcixEYXRlLERlbGV0aW9uTWFyayxQb3N0ZWQs0JLQuNC00J7Qv9C10YDQsNGG0LjQuCzQmtCw0YHRgdCwX0tleSzQkdCw0L3QutC+0LLRgdC60LjQudCh0YfQtdGCX0tleSzQmtC+0L3RgtGA0LDQs9C10L3RgizQodC+0YLRgNGD0LTQvdC40LpfS2V5LNCh0YLQsNGC0YzRj9CU0JTQoV9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQodGD0LzQvNCw0JTQvtC60YPQvNC10L3RgtCwLNCi0LjQv9CU0LXQvdC10LbQvdGL0YXQodGA0LXQtNGB0YLQsizQktGL0L/Qu9Cw0YLQsNCX0J/QnNC10YHRj9GGLNCa0L7QvNC80LXQvdGC0LDRgNC40LkiLCJlbnRpdHkiOiJEb2N1bWVudF/QodC/0LjRgdCw0L3QuNC10JTQtdC90LXQttC90YvRhdCh0YDQtdC00YHRgtCyIiwiZGF0ZV9maWVsZCI6IkRhdGUiLCJzdGF0aWNfZmlsdGVyIjpudWxsfQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0KHRgtCw0YLRjNGP0JfQsNGC0YDQsNGCX0tleSzQodC/0LXRhtC40LDQu9C40LfQsNGG0LjRj19LZXks0KHRg9C80LzQsCzQodC+0YLRgNGD0LTQvdC40LpfS2V5IiwiZW50aXR5IjoiRG9jdW1lbnRf0KHQv9C40YHQsNC90LjQtdCU0LXQvdC10LbQvdGL0YXQodGA0LXQtNGB0YLQsl/Ql9Cw0YLRgNCw0YLRiyIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQodGD0LzQvNCwLNCh0YLQsNGC0YzRj9CU0JTQoV9LZXks0JTQvtC60YPQvNC10L3RgtCe0YHQvdC+0LLQsNC90LjRjyzQlNC+0LrRg9C80LXQvdGC0J7RgdC90L7QstCw0L3QuNGPX1R5cGUiLCJlbnRpdHkiOiJEb2N1bWVudF/QodC/0LjRgdCw0L3QuNC10JTQtdC90LXQttC90YvRhdCh0YDQtdC00YHRgtCyX9Cg0LDRgdGI0LjRhNGA0L7QstC60LDQn9C70LDRgtC10LbQsCIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOm51bGx9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLENvZGUsUGFyZW50X0tleSxJc0ZvbGRlcixEZWxldGlvbk1hcmsiLCJlbnRpdHkiOiJDYXRhbG9nX9Ch0L/QtdGG0LjQsNC70LjQt9Cw0YbQuNC4IiwiZGF0ZV9maWVsZCI6bnVsbCwic3RhdGljX2ZpbHRlciI6IkRlbGV0aW9uTWFyayBlcSBmYWxzZSJ9",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0KHQv9C10YbQuNCw0LvQuNC30LDRhtC40Y9fS2V5LNCe0YHQvdC+0LLQvdCw0Y8iLCJlbnRpdHkiOiJDYXRhbG9nX9Ch0L7RgtGA0YPQtNC90LjQutC4X9Ch0L/QtdGG0LjQu9Cw0LfQsNGG0LjQuNCh0L7RgtGA0YPQtNC90LjQutCwIiwiZGF0ZV9maWVsZCI6bnVsbCwic3RhdGljX2ZpbHRlciI6bnVsbH0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLENvZGUsUGFyZW50X0tleSxJc0ZvbGRlcixEZWxldGlvbk1hcmss0J7Qv9C40YHQsNC90LjQtSIsImVudGl0eSI6IkNhdGFsb2df0KHRgtCw0YLRjNC40JTQstC40LbQtdC90LjRj9CU0LXQvdC10LbQvdGL0YXQodGA0LXQtNGB0YLQsiIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOiJEZWxldGlvbk1hcmsgZXEgZmFsc2UifQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLENvZGUsUGFyZW50X0tleSxJc0ZvbGRlcixEZWxldGlvbk1hcmss0JLQuNC00KHRgtCw0YLRjNC40JTQvtGF0L7QtNC+0LLQmNCg0LDRgdGF0L7QtNC+0LIs0JLQuNC00KDQsNGB0L/RgNC10LTQtdC70LXQvdC40Y/QoNCw0YHRhdC+0LTQvtCyIiwiZW50aXR5IjoiQ2F0YWxvZ1/QodGC0LDRgtGM0LjQlNC+0YXQvtC00L7QstCY0KDQsNGB0YXQvtC00L7QsiIsImRhdGVfZmllbGQiOm51bGwsInN0YXRpY19maWx0ZXIiOiJEZWxldGlvbk1hcmsgZXEgZmFsc2UifQ==",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LERlc2NyaXB0aW9uLENvZGUsRGVsZXRpb25NYXJrLNCh0YLRgNGD0LrRgtGD0YDQvdCw0Y/QldC00LjQvdC40YbQsF9LZXks0J3QsNGH0LjRgdC70LXQvdC40LXQo9C00LXRgNC20LDQvdC40LUs0KLQuNC/0J3QsNGH0LjRgdC70LXQvdC40Y/Qo9C00LXRgNC20LDQvdC40Y8s0J/Qu9GO0YHQnNC40L3Rg9GBLNCf0L7Qu9C90L7QtdCd0LDQuNC80LXQvdC+0LLQsNC90LjQtSIsImVudGl0eSI6IkNhdGFsb2df0J3QsNGH0LjRgdC70LXQvdC40Y/QmNCj0LTQtdGA0LbQsNC90LjRj9Ch0L7RgtGA0YPQtNC90LjQutC+0LIiLCJkYXRlX2ZpZWxkIjpudWxsLCJzdGF0aWNfZmlsdGVyIjoiRGVsZXRpb25NYXJrIGVxIGZhbHNlIn0=",
    "eyJwcm90ZWN0X3Bob25lIjpudWxsLCJzZWxlY3QiOiJSZWZfS2V5LExpbmVOdW1iZXIs0JTQsNGC0LDQndCw0YfQsNC70LAs0JTQsNGC0LDQntC60L7QvdGH0LDQvdC40Y8s0J3QvtC80LXQvdC60LvQsNGC0YPRgNCwX0tleSzQndC+0YDQvNCw0JLRgNC10LzQtdC90Lgs0J/QvtC80LXRidC10L3QuNC1X0tleSzQn9GA0LjRh9C40L3QsNCX0LDQv9C40YHQuF9LZXks0KHQvtGC0YDRg9C00L3QuNC6X0tleSzQptC10L3QsCIsImVudGl0eSI6IkRvY3VtZW50X9Ch0L7QsdGL0YLQuNC1X9Cj0YHQu9GD0LPQuCIsImRhdGVfZmllbGQiOiLQlNCw0YLQsNCd0LDRh9Cw0LvQsCIsInN0YXRpY19maWx0ZXIiOm51bGx9"
)
$ApprovedEntityDefinitions += @($AdditionalEntityDefinitionBase64 | ForEach-Object {
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) | ConvertFrom-Json
})

# Expand two existing allowlists without placing Cyrillic source names in this
# ASCII-compatible script body.
$PatientSelect = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("UmVmX0tleSxEZXNjcmlwdGlvbixEZWxldGlvbk1hcmss0JTQsNGC0LDQoNC10LPQuNGB0YLRgNCw0YbQuNC4LNCY0LzRjyzQntGC0YfQtdGB0YLQstC+LNCk0LDQvNC40LvQuNGPLNCd0LDQuNC80LXQvdC+0LLQsNC90LjQtdCf0L7Qu9C90L7QtSzQmNGB0YLQvtGH0L3QuNC60JjQvdGE0L7RgNC80LDRhtC40LhfS2V5LNCa0LDQvdCw0LvQn9GA0LjQstC70LXRh9C10L3QuNGPX0tleSzQmtCw0L3QsNC70J/RgNC40LLQu9C10YfQtdC90LjRj9CX0L3QsNGH0LXQvdC40LUs0KHQvtGC0YDRg9C00L3QuNC60KDQtdCz0LjRgdGC0YDQsNGG0LjQuF9LZXks0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQotC10LvQtdGE0L7QvQ=="))
$MoneySelect = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("UmVjb3JkZXIsUGVyaW9kLExpbmVOdW1iZXIsQWN0aXZlLFJlY29yZFR5cGUs0KHRgtGA0YPQutGC0YPRgNC90LDRj9CV0LTQuNC90LjRhtCwX0tleSzQotC40L/QlNC10L3QtdC20L3Ri9GF0KHRgNC10LTRgdGC0LIs0JHQsNC90LrQvtCy0YHQutC40LnQodGH0LXRgtCa0LDRgdGB0LAs0KHRg9C80LzQsCzQodGC0LDRgtGM0Y/QlNCU0KFfS2V5LFJlY29yZGVyX1R5cGU="))
$PatientEntityName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("Q2F0YWxvZ1/QmtC+0L3RgtGA0LDQs9C10L3RgtGL"))
$MoneyEntityName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("QWNjdW11bGF0aW9uUmVnaXN0ZXJf0JTQtdC90LXQttC90YvQtdCh0YDQtdC00YHRgtCy0LBfUmVjb3JkVHlwZQ=="))
@($ApprovedEntityDefinitions | Where-Object { $_.entity -eq $PatientEntityName })[0].select = $PatientSelect
@($ApprovedEntityDefinitions | Where-Object { $_.entity -eq $MoneyEntityName })[0].select = $MoneySelect

# Dependencies first. Table parts follow their parents so they can update the
# already-created canonical object with the resolved specialty/direction.
foreach ($definition in $ApprovedEntityDefinitions) {
    $order = if ($definition.entity.StartsWith("Catalog_")) { 10 }
        elseif ($definition.entity.StartsWith("Document_")) { 20 }
        elseif ($definition.entity.StartsWith("InformationRegister_")) { 30 }
        else { 40 }
    if ([string]$definition.select -match "LineNumber" -and $order -lt 30) { $order += 5 }
    $definition | Add-Member -NotePropertyName "sync_order" -NotePropertyValue $order -Force
}
$ApprovedEntityDefinitions = @($ApprovedEntityDefinitions | Sort-Object sync_order, entity)
$ApprovedEntities = @($ApprovedEntityDefinitions | ForEach-Object { $_.entity })
# The initial import can load the full patient directory. Subsequent runs only
# need newly registered patients; otherwise every three-hour sync rereads the
# entire catalog even though 1C exposes a registration date.
$CounterpartyEntity = $PatientEntityName
$CounterpartyRegistrationDateField = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0JTQsNGC0LDQoNC10LPQuNGB0YLRgNCw0YbQuNC4"))
@($ApprovedEntityDefinitions | Where-Object { $_.entity -eq $CounterpartyEntity })[0].date_field = $CounterpartyRegistrationDateField

function Write-ConnectorLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR")][string]$Level = "INFO"
    )

    if (-not (Test-Path -LiteralPath $ConnectorDirectory)) {
        New-Item -ItemType Directory -Path $ConnectorDirectory -Force | Out-Null
    }
    $line = "{0} [{1}] {2}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Level, $Message
    try {
        if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
            $archive = "$LogPath.1"
            if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
            Move-Item -LiteralPath $LogPath -Destination $archive -Force
        }
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
    catch {
        # Logging must never abort a data sync because another console or an
        # antivirus scanner briefly holds the file.
        Write-Warning "Could not write the connector log: $($_.Exception.Message)"
    }
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
    # Entities and scalar fields are discovered from the live 1C $metadata at
    # the start of every run. The saved list is retained only for compatibility
    # with old config files and is never authoritative.
    $loaded.Entities = @()
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
        [string]$SelectFields,
        [string[]]$AvailableFields,
        [string]$DateField,
        [string]$StaticFilter,
        [Parameter(Mandatory = $true)][int]$ConfiguredPageSize,
        [ValidateRange(0, 100000000)][int]$InitialSkip = 0
    )

    $encodedEntity = [Uri]::EscapeDataString($Entity)
    $queryUrl = "$BaseUrl/$encodedEntity`?`$format=json&`$top=$ConfiguredPageSize&allowedOnly=true"
    # Every paged query needs a stable business key. A mutable physical order
    # can skip or repeat register rows while the clinic keeps working in 1C.
    if (($Entity.StartsWith("Catalog_") -or $Entity.StartsWith("Document_")) -and $AvailableFields -contains "Ref_Key") {
        $referenceOrder = if ($AvailableFields -contains "LineNumber") {
            "Ref_Key,LineNumber"
        }
        else { "Ref_Key" }
        $queryUrl += "&`$orderby=$referenceOrder"
    }
    elseif ($Entity.StartsWith("AccumulationRegister_") -and $AvailableFields -contains "Period") {
        $registerOrder = if ($AvailableFields -contains "Recorder_Key") {
            "Period,Recorder_Key,LineNumber"
        }
        elseif ($AvailableFields -contains "Recorder") {
            $parts = @("Period")
            if ($AvailableFields -contains "Recorder_Type") { $parts += "Recorder_Type" }
            $parts += "Recorder"
            if ($AvailableFields -contains "LineNumber") { $parts += "LineNumber" }
            $parts -join ","
        }
        else { "Period" }
        $queryUrl += "&`$orderby=$registerOrder"
    }
    elseif ($DateField) {
        $queryUrl += "&`$orderby=$([Uri]::EscapeDataString($DateField))"
    }
    if ($SelectFields) {
        $queryUrl += "&`$select=$([Uri]::EscapeDataString($SelectFields))"
    }
    $filterParts = @()
    if ($StaticFilter) { $filterParts += $StaticFilter }
    if ($null -ne $ChangedSince -and $DateField) {
        $dateText = ([datetime]$ChangedSince).ToString("yyyy-MM-ddTHH:mm:ss")
        $filterParts += "$DateField ge datetime'$dateText'"
    }
    if ($filterParts.Count -gt 0) {
        $filter = [Uri]::EscapeDataString(($filterParts -join " and "))
        $queryUrl += "&`$filter=$filter"
    }
    # 1C treats $top as the total result limit and does not necessarily emit
    # odata.nextLink. Page explicitly with $skip. Ref_Key remains the stable
    # order for catalogs/documents; this 1C version cannot compare GUIDs with gt.
    $skip = $InitialSkip
    $pageNumber = [int][Math]::Floor($InitialSkip / $ConfiguredPageSize)
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
        # Do not emit an empty page into the downstream pipeline. In Windows
        # PowerShell, consumer control-flow statements can otherwise resume the
        # producer loop before it reaches this termination condition.
        if ($records.Count -eq 0) { break }
        Write-Output -NoEnumerate ([pscustomobject]@{ Records = $records })
        if ($records.Count -lt $ConfiguredPageSize) { break }
        $skip += $records.Count
    }
}

function ConvertTo-ProtectedPhoneHash {
    param([object]$Value)

    if ($null -eq $Value) { return $null }
    $digits = ([string]$Value) -replace "[^0-9]", ""
    if ($digits.Length -eq 11 -and $digits.StartsWith("8")) { $digits = "7" + $digits.Substring(1) }
    elseif ($digits.Length -eq 10) { $digits = "7" + $digits }
    if ($digits.Length -lt 10) { return $null }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes("+$digits")))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Protect-OneCRecords {
    param([object[]]$Records, [string[]]$PhoneFields)

    if ($null -eq $PhoneFields -or $PhoneFields.Count -eq 0) { return @($Records) }
    foreach ($record in @($Records)) {
        $phoneHash = $null
        foreach ($phoneField in @($PhoneFields)) {
            $property = $record.PSObject.Properties[$phoneField]
            if ($null -ne $property) {
                if (-not $phoneHash) { $phoneHash = ConvertTo-ProtectedPhoneHash -Value $property.Value }
                $record.PSObject.Properties.Remove($phoneField)
            }
        }
        $record | Add-Member -NotePropertyName "PhoneHash" -NotePropertyValue $phoneHash -Force
    }
    return @($Records)
}

function Remove-OneCBinaryFields {
    param([object[]]$Records, [string[]]$BinaryFields)

    if ($null -eq $BinaryFields -or $BinaryFields.Count -eq 0) { return @($Records) }
    foreach ($record in @($Records)) {
        foreach ($field in @($BinaryFields)) {
            if ($null -ne $record.PSObject.Properties[$field]) {
                $record.PSObject.Properties.Remove($field)
            }
        }
    }
    return @($Records)
}

function Remove-OneCNavigationFields {
    param([object[]]$Records)

    # 1C may append navigation link URLs to JSON rows even though these
    # technical fields are not scalar properties from $metadata. They are
    # useful for OData clients but must not be uploaded as business data.
    foreach ($record in @($Records)) {
        foreach ($property in @($record.PSObject.Properties)) {
            if ([string]$property.Name -match '(?i)@navigationLinkUrl$') {
                $record.PSObject.Properties.Remove($property.Name)
            }
        }
    }
    return @($Records)
}

function Remove-OneCUnsupportedCharacters {
    param([object[]]$Records)

    # PostgreSQL JSONB cannot store U+0000.  Some legacy 1C text fields may
    # contain it, so remove only that unsupported character before upload.
    foreach ($record in @($Records)) {
        foreach ($property in @($record.PSObject.Properties)) {
            if ($property.Value -is [string] -and $property.Value.IndexOf([char]0) -ge 0) {
                $property.Value = $property.Value.Replace([string][char]0, "")
            }
        }
    }
    return @($Records)
}

function Get-RevoraUploadBatches {
    param(
        [Parameter(Mandatory = $true)][object[]]$Records,
        [ValidateRange(1, 500)][int]$MaxRecords = 200,
        [ValidateRange(100000, 1900000)][int]$MaxBytes = 1500000
    )

    $current = New-Object System.Collections.ArrayList
    $currentBytes = 0
    foreach ($record in @($Records)) {
        $recordJson = $record | ConvertTo-Json -Depth 30 -Compress
        $recordBytes = [Text.Encoding]::UTF8.GetByteCount($recordJson) + 1
        if ($recordBytes -gt $MaxBytes) {
            throw "A single OData row exceeds the safe Revora upload limit. Binary fields are excluded, so inspect entity metadata for another oversized scalar field."
        }
        if ($current.Count -gt 0 -and ($current.Count -ge $MaxRecords -or ($currentBytes + $recordBytes) -gt $MaxBytes)) {
            Write-Output -NoEnumerate ([pscustomobject]@{ Records = @($current.ToArray()) })
            $current.Clear()
            $currentBytes = 0
        }
        [void]$current.Add($record)
        $currentBytes += $recordBytes
    }
    if ($current.Count -gt 0) {
        Write-Output -NoEnumerate ([pscustomobject]@{ Records = @($current.ToArray()) })
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
        schema_version = "1c-odata-v5-dynamic-metadata"
    } | ConvertTo-Json -Depth 30 -Compress
    $body = [Text.Encoding]::UTF8.GetBytes($json)

    return Invoke-WithRetry -Description "Revora upload" -Operation {
        try {
            Invoke-RestMethod -Method Post -Uri "$ApiUrl/integrations/1c/push" -MaximumRedirection 0 -TimeoutSec 300 `
                -Headers @{ Authorization = "Bearer $Token" } `
                -ContentType "application/json; charset=utf-8" -Body $body
        }
        catch {
            $responseBody = $null
            if ($null -ne $_.Exception.Response) {
                try {
                    $stream = $_.Exception.Response.GetResponseStream()
                    if ($null -ne $stream) {
                        $reader = New-Object System.IO.StreamReader($stream)
                        $responseBody = $reader.ReadToEnd()
                        $reader.Dispose()
                    }
                } catch { }
            }
            if ($responseBody) {
                throw "Revora rejected entity '$Entity' ($($Records.Count) records): $responseBody"
            }
            throw
        }
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

function Get-MetadataEntityDefinitions {
    param([Parameter(Mandatory = $true)][object[]]$Entities)

    $definitions = @()
    # Keep the script body ASCII-only for Windows PowerShell 5.1, which reads
    # UTF-8 files without a BOM using the legacy Windows code page.
    $dateCandidateBase64 = @(
        "0JTQsNGC0LA=",
        "0JTQsNGC0LDQntC/0LXRgNCw0YbQuNC4",
        "0JTQsNGC0LDQodC+0LfQtNCw0L3QuNGP",
        "0JTQsNGC0LDQndCw0YfQsNC70LA="
    )
    $dateCandidates = @("Period", "Date") + @(
        $dateCandidateBase64 | ForEach-Object {
            [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_))
        }
    )
    $phoneWord = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String("0YLQtdC70LXRhNC+0L0=")
    )
    foreach ($item in @($Entities)) {
        $name = [string]$item.name
        $fields = @($item.properties | ForEach-Object { [string]$_.name } | Where-Object { $_ })
        if (-not $name -or $fields.Count -eq 0) { continue }

        $known = @($ApprovedEntityDefinitions | Where-Object { $_.entity -eq $name }) | Select-Object -First 1
        $dateField = $null
        if ($null -ne $known -and $known.date_field -and $fields -contains [string]$known.date_field) {
            $dateField = [string]$known.date_field
        }
        else {
            foreach ($candidate in $dateCandidates) {
                if ($fields -contains $candidate) { $dateField = $candidate; break }
            }
        }
        $protectPhone = if ($null -ne $known -and $known.protect_phone) {
            @($fields | Where-Object {
                $_ -eq [string]$known.protect_phone -or
                $_.IndexOf($phoneWord, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                $_ -match "(?i)phone"
            })
        }
        else { @() }
        $binaryFields = @(
            $item.properties |
                Where-Object { [string]$_.type -eq "Edm.Binary" } |
                ForEach-Object { [string]$_.name }
        )
        # Do not inherit the old per-entity row filters. Revora keeps the raw
        # OData layer complete (including deleted/inactive historical rows) and
        # applies business exclusions only when calculating a metric.
        $staticFilter = $null
        $order = if ($name.StartsWith("Catalog_")) { 10 }
            elseif ($name.StartsWith("Document_")) { 20 }
            elseif ($name.StartsWith("InformationRegister_")) { 30 }
            elseif ($name.StartsWith("AccumulationRegister_")) { 40 }
            else { 50 }
        $definitions += [pscustomobject]@{
            entity = $name
            # Omitting $select makes 1C return every scalar property declared
            # in metadata and avoids IIS URL-length failures on wide objects.
            select = $null
            fields = @($fields)
            date_field = $dateField
            static_filter = $staticFilter
            protect_phone = @($protectPhone)
            binary_fields = @($binaryFields)
            sync_order = $order
        }
    }
    return @($definitions | Sort-Object sync_order, entity)
}

function Send-RevoraMetadata {
    param($Config, [object[]]$Entities)

    $credential = [pscredential]::new($Config.OneCUsername, $Config.OneCPassword)
    $entities = if ($null -ne $Entities -and $Entities.Count -gt 0) {
        @($Entities)
    }
    else {
        @(Get-OneCMetadataInventory -BaseUrl $Config.OneCBaseUrl -Credential $credential)
    }
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

    $inventory = @(Get-OneCMetadataInventory -BaseUrl $Config.OneCBaseUrl -Credential $credential)
    $definitions = @(Get-MetadataEntityDefinitions -Entities $inventory)
    if ($definitions.Count -eq 0) { throw "No readable scalar OData entities were discovered." }
    $definition = $definitions[0]
    $entity = [string]$definition.entity
    $encodedEntity = [Uri]::EscapeDataString($entity)
    $probeField = [string]$definition.fields[0]
    $probeUrl = "$($Config.OneCBaseUrl)/$encodedEntity`?`$format=json&`$top=1&`$select=$([Uri]::EscapeDataString($probeField))&allowedOnly=true"
    $probe = Invoke-OneCGet -Url $probeUrl -Credential $credential
    if ($null -eq $probe.PSObject.Properties["value"] -and $null -eq $probe.PSObject.Properties["d"]) {
        throw "1C returned an unexpected test response."
    }
    Send-RevoraMetadata -Config $Config -Entities $inventory | Out-Null
    Write-ConnectorLog -Message "Connection test passed: OData metadata and all published scalar entities are discoverable."
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
        $credential = [pscredential]::new($Config.OneCUsername, $Config.OneCPassword)
        $inventory = @(Get-OneCMetadataInventory -BaseUrl $Config.OneCBaseUrl -Credential $credential)
        $entityDefinitions = @(Get-MetadataEntityDefinitions -Entities $inventory)
        if ($entityDefinitions.Count -eq 0) { throw "No readable scalar OData entities were discovered." }
        $runtimeEntities = @($entityDefinitions | ForEach-Object { $_.entity })
        Send-RevoraMetadata -Config $Config -Entities $inventory | Out-Null
        Write-ConnectorLog -Message "Dynamic OData inventory enabled: entities=$($runtimeEntities.Count)."
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

        $token = ConvertFrom-ProtectedString -Value $Config.ConnectorToken
        $configuredPageSize = if ($Config.PageSize) { [int]$Config.PageSize } else { $PageSize }
        $totalSent = 0
        $totalStored = 0
        $totalDuplicates = 0

        try {
            if ($ResumeOffset -gt 0 -and -not $ResumeEntity) {
                throw "-ResumeOffset requires -ResumeEntity."
            }
            if ($ResumeEntity -and $ResumeEntity -notin $runtimeEntities) {
                throw "Resume entity '$ResumeEntity' is not enabled in the connector configuration."
            }
            $waitingForResumeEntity = [bool]$ResumeEntity
            foreach ($entity in $runtimeEntities) {
                if ($waitingForResumeEntity -and $entity -ne $ResumeEntity) { continue }
                $entitySent = 0
                $entityInitialSkip = if ($waitingForResumeEntity) { $ResumeOffset } else { 0 }
                # A resumed initial import must keep the same unfiltered catalog
                # that produced the saved offset. Normal future runs use dates.
                $entityChangedSince = if ($waitingForResumeEntity -and $ResumeOffset -gt 0) {
                    $null
                }
                elseif ($entity -eq $CounterpartyEntity -and ($ForceFull -or $null -eq $lastSuccessful)) {
                    # Documents in the selected period can reference patients
                    # created years earlier. A full rebuild therefore needs the
                    # complete patient directory; regular scheduled runs remain
                    # incremental by registration date.
                    $null
                }
                else { $changedSince }
                $waitingForResumeEntity = $false
                $definition = @($entityDefinitions | Where-Object { $_.entity -eq $entity })[0]
                if ($null -eq $definition) { throw "No metadata definition is available for $entity." }
                # Use the pipeline so every OData page is uploaded immediately.
                # A regular foreach expression materializes all pages first and
                # can leave the console silent for a long time during upload.
                Get-ODataPages -Entity $entity -Credential $credential `
                    -BaseUrl $Config.OneCBaseUrl -ChangedSince $entityChangedSince `
                    -SelectFields $definition.select -DateField $definition.date_field `
                    -AvailableFields @($definition.fields) `
                    -StaticFilter $definition.static_filter -ConfiguredPageSize $configuredPageSize `
                    -InitialSkip $entityInitialSkip |
                ForEach-Object {
                    $page = $_
                    $records = @(Protect-OneCRecords -Records @($page.Records) -PhoneFields @($definition.protect_phone))
                    $records = @(Remove-OneCBinaryFields -Records $records -BinaryFields @($definition.binary_fields))
                    $records = @(Remove-OneCNavigationFields -Records $records)
                    $records = @(Remove-OneCUnsupportedCharacters -Records $records)
                    # Wide dynamically discovered objects can be much larger
                    # than the original fixed field subset. Split by both row
                    # count and encoded size to stay below API/proxy limits.
                    $uploadBatchSize = if ($entity -eq $CounterpartyEntity) { 50 } else { 200 }
                    Get-RevoraUploadBatches -Records $records -MaxRecords $uploadBatchSize |
                    ForEach-Object {
                        $batch = @($_.Records)
                        $result = Send-RevoraBatch -Entity $entity -Records $batch -ApiUrl $Config.RevoraApiUrl -Token $token
                        $entitySent += $batch.Count
                        $totalSent += $batch.Count
                        $totalStored += [int]$result.records_stored
                        $totalDuplicates += [int]$result.records_duplicate
                        $uploadedThrough = $entityInitialSkip + $entitySent
                        Write-ConnectorLog -Message "${entity}: uploaded_through=$uploadedThrough, stored=$($result.records_stored), duplicates=$($result.records_duplicate)"
                    }
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
