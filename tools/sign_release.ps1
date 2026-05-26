param(
    [string]$WorkspaceRoot = "C:\Users\sornr\Desktop\MAYDAY\New\python-mayday",
    [string]$PfxPath = $env:MAYDAY_SIGN_PFX_PATH,
    [string]$PfxPassword = $env:MAYDAY_SIGN_PFX_PASSWORD,
    [string]$Thumbprint = $env:MAYDAY_SIGN_CERT_SHA1,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$IncludeRuntimeDlls
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $sdkRoots = @(
        "$env:ProgramFiles(x86)\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    )

    foreach ($root in $sdkRoots) {
        if (-not (Test-Path $root)) {
            continue
        }
        $candidate = Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    return $null
}

function Get-SignTargets {
    param(
        [string]$Root,
        [switch]$WithDlls
    )

    $targets = @(
        (Join-Path $Root "dist\client\Mayday.exe"),
        (Join-Path $Root "dist\server\MaydayServer.exe"),
        (Join-Path $Root "dist\client\data\bin\MaydayAudioHost.exe")
    )

    if ($WithDlls) {
        $targets += Get-ChildItem -Path (Join-Path $Root "dist\client\data\bin") -Filter *.dll -File -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }

    return $targets | Where-Object { Test-Path $_ } | Select-Object -Unique
}

function Invoke-Sign {
    param(
        [string]$SignTool,
        [string]$FilePath
    )

    $args = @(
        "sign",
        "/fd", "SHA256",
        "/td", "SHA256",
        "/tr", $TimestampUrl
    )

    if ($PfxPath) {
        $args += @("/f", $PfxPath)
        if ($PfxPassword) {
            $args += @("/p", $PfxPassword)
        }
    }
    elseif ($Thumbprint) {
        $args += @("/sha1", $Thumbprint)
    }
    else {
        throw "A PFX path or certificate thumbprint is required."
    }

    $args += $FilePath
    & $SignTool @args
}

function Resolve-CertificateFromStore {
    param(
        [string]$Sha1
    )

    if (-not $Sha1) {
        return $null
    }

    $stores = @(
        "Cert:\CurrentUser\My",
        "Cert:\LocalMachine\My"
    )

    foreach ($store in $stores) {
        if (-not (Test-Path $store)) {
            continue
        }
        $cert = Get-ChildItem $store -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $Sha1 -and $_.HasPrivateKey } |
            Sort-Object NotAfter -Descending |
            Select-Object -First 1
        if ($cert) {
            return $cert
        }
    }

    return $null
}

function Invoke-SignFallback {
    param(
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate,
        [string]$FilePath
    )

    if (-not $Certificate) {
        throw "No code signing certificate with private key was found in the local store."
    }

    $result = Set-AuthenticodeSignature -FilePath $FilePath -Certificate $Certificate -HashAlgorithm SHA256
    if ($result.Status -notin @("Valid", "UnknownError")) {
        throw "Signing failed for $FilePath with status $($result.Status)"
    }
}

$signTool = Resolve-SignTool
$targets = Get-SignTargets -Root $WorkspaceRoot -WithDlls:$IncludeRuntimeDlls

if (-not $targets) {
    throw "No sign targets were found."
}

if ($signTool) {
    Write-Host "signtool:" $signTool
}
else {
    Write-Host "signtool: not found, using Set-AuthenticodeSignature fallback"
}

$storeCert = $null
if (-not $signTool) {
    $storeCert = Resolve-CertificateFromStore -Sha1 $Thumbprint
    if (-not $storeCert) {
        throw "signtool.exe was not found and no matching thumbprint certificate with private key is available."
    }
}

foreach ($target in $targets) {
    Write-Host "Signing:" $target
    if ($signTool) {
        Invoke-Sign -SignTool $signTool -FilePath $target
    }
    else {
        Invoke-SignFallback -Certificate $storeCert -FilePath $target
    }
}

Write-Host "Done:" $targets.Count "file(s) processed for signing"
