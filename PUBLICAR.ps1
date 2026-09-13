# Publica exclusivamente la entrega original. No ejecuta ni modifica la app.
# Compatible con Windows PowerShell 5.1 y Git 2.28 o posterior.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/emmanuelmarioarevalolimon-bit/Cashflow-coach.git'
$WebRepo = 'https://github.com/emmanuelmarioarevalolimon-bit/Cashflow-coach'
$ExpectedZipHash = '3663b7eb7e2ee26af9547de4d66f4116778b7a720ea47b8396ffc67ea71bb3dc'
$ZipPath = Join-Path $PSScriptRoot 'c1-web-integrada.zip'
$PreviousLocation = Get-Location
$Project = $null
$Published = $false
$Branch = $null
$ResultCode = 0

function Invoke-Git {
    param([Parameter(Mandatory=$true)][string[]]$GitArgs)
    & $script:GitExe @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw ('Git fallo (' + $LASTEXITCODE + '): git ' + ($GitArgs -join ' '))
    }
}

function Get-GitIdentity {
    param([string]$Key, [string]$Question)
    $value = & $script:GitExe config --get $Key
    if ($LASTEXITCODE -gt 1) { throw ('No pude leer ' + $Key) }
    $text = (($value | Out-String).Trim())
    if ([string]::IsNullOrWhiteSpace($text)) {
        $text = (Read-Host $Question).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) { throw ($Key + ' no puede estar vacio.') }
        Invoke-Git -GitArgs @('config', '--local', $Key, $text)
    }
    return $text
}

try {
    Write-Host ''
    Write-Host 'COMPRIA - PUBLICAR ENTREGA 6.0.0-web-integrada'
    Write-Host ('Destino: ' + $Repo)
    Write-Host 'No se usaran tus otras carpetas, .env, bases de datos ni mejoras nuevas.'
    Write-Host ''

    $gitCommand = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $gitCommand) {
        throw 'No encuentro Git. Instala Git for Windows desde https://git-scm.com/downloads/win y abre este archivo de nuevo.'
    }
    $script:GitExe = $gitCommand.Source
    foreach ($key in @('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')) {
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($key))) {
            throw ('La variable ' + $key + ' esta activa. Abre una terminal sin esa configuracion para evitar usar otro repositorio.')
        }
    }
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
        throw 'Falta c1-web-integrada.zip. Extrae TODO el paquete antes de abrir PUBLICAR.bat.'
    }
    if ((Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash -ne $ExpectedZipHash) {
        throw 'El ZIP no coincide con la entrega original. No se publicara.'
    }

    $suffix = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,8))
    $Project = Join-Path $PSScriptRoot ('codigo-6.0.0-' + $suffix)
    if (Test-Path -LiteralPath $Project) { throw 'La carpeta de destino ya existe; no se sobrescribira.' }

    # Construye el inventario desde el ZIP cuya huella acaba de verificarse.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $expected = @{}
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) { continue }
            $relative = $entry.FullName.Replace('\','/')
            if ($relative -match '(^/|^[A-Za-z]:|(^|/)\.\.(/|$)|(^|/)\.git(/|$))') {
                throw ('Ruta no permitida en el ZIP: ' + $relative)
            }
            $stream = $entry.Open()
            $hasher = [System.Security.Cryptography.SHA256]::Create()
            try {
                $expected[$relative] = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','')
            } finally { $stream.Dispose(); $hasher.Dispose() }
        }
    } finally { $archive.Dispose() }
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $Project
    Set-Location -LiteralPath $Project
    Invoke-Git -GitArgs @('init', '-b', 'main')
    Invoke-Git -GitArgs @('config', '--local', 'core.autocrlf', 'false')
    Invoke-Git -GitArgs @('remote', 'add', 'origin', $Repo)

    Write-Host ''
    Write-Host 'Comprobando las ramas remotas. Git puede pedir iniciar sesion en GitHub.'
    $heads = @(& $script:GitExe ls-remote --heads origin)
    if ($LASTEXITCODE -ne 0) {
        throw 'No pude leer el repositorio. Revisa la sesion de GitHub, el acceso al repo y la conexion. No se ha subido nada.'
    }
    $Branch = 'main'
    if ($heads.Count -gt 0) {
        $Branch = 'entrega-web-final-6.0.0-' + $suffix
        Invoke-Git -GitArgs @('checkout', '-b', $Branch)
        Write-Host 'El repo ya contiene ramas: se creara una entrega independiente SIN cambiar main ni mezclar historiales.'
    } else {
        Write-Host 'El repo no tiene ramas: se publicara en main.'
    }

    Write-Host ''
    Write-Host 'El nombre y correo del commit quedaran en el historial. Puedes usar tu correo noreply de GitHub.'
    $commitName = Get-GitIdentity -Key 'user.name' -Question 'Nombre para el commit (no es tu contrasena)'
    $commitEmail = Get-GitIdentity -Key 'user.email' -Question 'Correo para el commit'
    Write-Host ('Autor: ' + $commitName + ' <' + $commitEmail + '>')

    # Verifica cada archivo extraido: no se acepta codigo distinto del ZIP.
    $paths = @($expected.Keys | Sort-Object)
    foreach ($relative in $paths) {
        $full = Join-Path $Project $relative
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw ('Falta: ' + $relative) }
        if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $expected[$relative]) {
            throw ('El archivo cambio respecto del original: ' + $relative)
        }
    }
    $rawHashes = @($paths | & $script:GitExe hash-object --no-filters --stdin-paths)
    if ($LASTEXITCODE -ne 0 -or $rawHashes.Count -ne $paths.Count) { throw 'No pude verificar los objetos Git originales.' }
    $expectedObjects = @{}
    for ($i = 0; $i -lt $paths.Count; $i++) { $expectedObjects[$paths[$i]] = $rawHashes[$i] }
    Invoke-Git -GitArgs @('add', '--', '.')
    $tracked = @(Invoke-Git -GitArgs @('ls-files'))
    if (@(Compare-Object -ReferenceObject $paths -DifferenceObject $tracked).Count -gt 0) {
        throw 'El listado preparado por Git no coincide con el ZIP. No se publicara.'
    }
    Invoke-Git -GitArgs @('diff', '--cached', '--stat')
    Write-Host ''
    Write-Host ('Repo: ' + $Repo)
    Write-Host ('Rama: ' + $Branch)
    Write-Host ('Archivos originales: ' + $paths.Count)
    Write-Host 'Solo se publicara el codigo y las plantillas originales. No se inicia la app.'
    $answer = Read-Host 'Escribe SUBIR para publicar; cualquier otra respuesta cancela'
    if ($answer.Trim() -ne 'SUBIR') {
        Write-Host 'Cancelado. No se envio nada a GitHub. La copia local se conserva.'
    } else {
        Invoke-Git -GitArgs @('commit', '-m', 'Entrega 6.0.0-web-integrada sin mejoras posteriores')
        # Comprueba el commit real, incluso si existe un hook local que cambie el indice.
        $tree = @(Invoke-Git -GitArgs @('ls-tree', '-r', '--full-tree', 'HEAD'))
        if ($tree.Count -ne $paths.Count) { throw 'El commit no tiene el inventario original. No se publicara.' }
        foreach ($line in $tree) {
            if ($line -notmatch '^100(?:644|755) blob ([0-9a-f]+)\t(.+)$') { throw 'Objeto inesperado en el commit.' }
            $objectId = $Matches[1]
            $relative = $Matches[2]
            if (-not $expectedObjects.ContainsKey($relative) -or $expectedObjects[$relative] -ne $objectId) {
                throw ('El commit no conserva los bytes originales de ' + $relative + '. No se publicara.')
            }
        }
        # Refspec unico; sin force, sin borrado de ramas y sin merge/pull.
        Invoke-Git -GitArgs @('push', '--set-upstream', 'origin', ('HEAD:refs/heads/' + $Branch))
        $Published = $true
        Write-Host ''
        Write-Host 'SUBIDA COMPLETADA'
        Write-Host ('Rama publicada: ' + $Branch)
        Write-Host ($WebRepo + '/tree/' + $Branch)
        Write-Host ('Copia local: ' + $Project)
        if ($Branch -ne 'main') {
            Write-Host 'En GitHub selecciona esta rama para ver la app. main sigue intacta.'
            Write-Host 'Esta es una instantanea independiente: no la mezcles automaticamente con las ideas nuevas.'
        }
    }
} catch {
    $ResultCode = 1
    Write-Host ''
    Write-Host ('DETENIDO: ' + $_.Exception.Message)
    if (-not $Published) { Write-Host 'No se ha confirmado una subida exitosa. No uses push --force para resolver errores.' }
    if ($null -ne $Project) { Write-Host ('Carpeta de trabajo conservada: ' + $Project) }
    Write-Host 'Comparte el error, nunca tokens, claves ni contrasenas.'
} finally {
    Set-Location -LiteralPath $PreviousLocation.Path
}
exit $ResultCode
