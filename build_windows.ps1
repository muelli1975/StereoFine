$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv-build"
$BuildDir = Join-Path $Root "build"
$DistRoot = Join-Path $Root "dist"
$Dist = Join-Path $DistRoot "StereoFine_1.0"
$ReleaseDir = Join-Path $Root "release"
$ZipPath = Join-Path $ReleaseDir "StereoFine_1.0.zip"
$SourceOut = Join-Path $Dist "Source"

Write-Host "StereoFine 1.0 - clean Windows release build"
Write-Host "Source:" $Root

# Always build the public release from a clean Python environment and clean
# PyInstaller output. The source tree itself remains untouched.
foreach ($Path in @($Venv, $BuildDir, $DistRoot, $ReleaseDir)) {
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
}

$BootstrapPython = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3.12 -c "import sys; assert sys.version_info[:3] == (3, 12, 10)" 2>$null
        if ($LASTEXITCODE -eq 0) { $BootstrapPython = @("py", "-3.12") }
    }
    catch {}
}
if (-not $BootstrapPython) {
    $PythonCommand = Get-Command python -ErrorAction Stop
    & $PythonCommand.Source -c "import sys; assert sys.version_info[:3] == (3, 12, 10), f'StereoFine 1.0 requires Python 3.12.10, got {sys.version}'"
    $BootstrapPython = @($PythonCommand.Source)
}

if ($BootstrapPython.Count -eq 2) {
    & $BootstrapPython[0] $BootstrapPython[1] -m venv $Venv
}
else {
    & $BootstrapPython[0] -m venv $Venv
}
$Python = Join-Path $Venv "Scripts\python.exe"

& $Python -c "import sys; assert sys.version_info[:3] == (3, 12, 10), f'StereoFine 1.0 requires Python 3.12.10 for the reference build, got {sys.version}'; assert sys.maxsize > 2**32, '64-bit Python required'; print(sys.version)"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-build.txt

# Fast reproducible pre-build checks. GUI smoke is deliberately manual on the
# target Windows desktop because display scaling and dialogs are part of it.
& $Python -m unittest discover -s tests -p "test_*.py"
& $Python -m compileall -q StereoFine.py stereofine tests
& $Python -c "import importlib, pkgutil, stereofine; mods=[m.name for m in pkgutil.iter_modules(stereofine.__path__, stereofine.__name__+'.')]; [importlib.import_module(n) for n in sorted(mods)]; print(f'Imported {len(mods)} StereoFine modules')"

& $Python -m PyInstaller --noconfirm --clean StereoFine.spec

$Exe = Join-Path $Dist "StereoFine.exe"
if (-not (Test-Path $Exe)) {
    throw "PyInstaller did not create StereoFine.exe"
}

# Keep the complete ExifTool Windows package visible and intact next to the EXE.
$ToolsSource = Join-Path $Root "tools"
if (-not (Test-Path $ToolsSource)) {
    $ToolsSource = Join-Path (Split-Path $Root -Parent) "tools"
}
if (-not (Test-Path (Join-Path $ToolsSource "exiftool.exe"))) {
    throw "Bundled ExifTool package not found. Expected tools\exiftool.exe."
}
Copy-Item -Recurse -Force $ToolsSource (Join-Path $Dist "tools")

# Public documentation and StereoFine's own MIT license.
foreach ($File in @(
    "README_DE.md",
    "README_EN.md",
    "LICENSE.txt",
    "THIRD_PARTY_NOTICES.md"
)) {
    Copy-Item -Force (Join-Path $Root $File) (Join-Path $Dist $File)
}
Copy-Item -Recurse -Force (Join-Path $Root "licenses") (Join-Path $Dist "licenses")

# Add runtime license material.  The source tree already contains the official
# Tcl/Tk 8.6 license terms, so Windows Python installations that omit the
# standalone tcl/tk license.terms files do not make the release build fail.
# If the build Python installation does expose those files, use its exact
# copies.  Python's own license remains required and is copied from the
# interpreter used for this build.
$BasePrefix = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$LicenseDir = Join-Path $Dist "licenses"

$PythonLicenseCandidates = @(
    (Join-Path $BasePrefix "LICENSE.txt"),
    (Join-Path $BasePrefix "LICENSE"),
    (Join-Path $BasePrefix "Doc\license.rst")
)
$PythonLicenseSource = $PythonLicenseCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $PythonLicenseSource) {
    throw "Required Python runtime license file not found below: $BasePrefix"
}
Copy-Item -Force $PythonLicenseSource (Join-Path $LicenseDir "Python-3.12.10-LICENSE.txt")

$TclTkLicenseCandidates = @(
    @{ Name = "Tcl"; Target = "Tcl-8.6-LICENSE.txt"; Candidates = @(
        (Join-Path $BasePrefix "tcl\tcl8.6\license.terms"),
        (Join-Path $BasePrefix "tcl\tcl8.6\LICENSE"),
        (Join-Path $BasePrefix "tcl\tcl8.6\LICENSE.txt")
    ) },
    @{ Name = "Tk"; Target = "Tk-8.6-LICENSE.txt"; Candidates = @(
        (Join-Path $BasePrefix "tcl\tk8.6\license.terms"),
        (Join-Path $BasePrefix "tcl\tk8.6\LICENSE"),
        (Join-Path $BasePrefix "tcl\tk8.6\LICENSE.txt")
    ) }
)
foreach ($Item in $TclTkLicenseCandidates) {
    $RuntimeLicense = $Item.Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($RuntimeLicense) {
        Write-Host "Using $($Item.Name) license from the Python installation:" $RuntimeLicense
        Copy-Item -Force $RuntimeLicense (Join-Path $LicenseDir $Item.Target)
    }
    else {
        $BundledLicense = Join-Path $Root "licenses\$($Item.Target)"
        if (-not (Test-Path $BundledLicense)) {
            throw "Bundled $($Item.Name) 8.6 license reference not found: $BundledLicense"
        }
        Write-Host "$($Item.Name) license.terms is not included in this Python installation; using the bundled official $($Item.Name) 8.6 license reference."
        # licenses\ was already copied to the distribution above, so no
        # additional action is necessary here.
    }
}

# The portable release contains the exact source snapshot used for the EXE.
New-Item -ItemType Directory -Force $SourceOut | Out-Null
$SourceFiles = @(
    ".gitignore",
    "StereoFine.py",
    "StereoFine.spec",
    "version_info.txt",
    "build_windows.ps1",
    "requirements-lock.txt",
    "requirements-build.txt",
    "README.md",
    "README_DE.md",
    "README_EN.md",
    "LICENSE.txt",
    "THIRD_PARTY_NOTICES.md",
    "BUILD_WINDOWS.md",
    "RELEASE_CHECKLIST.md",
    "CHANGELOG.md",
    "RELEASE_NOTES_1.0.md"
)
foreach ($File in $SourceFiles) {
    Copy-Item -Force (Join-Path $Root $File) (Join-Path $SourceOut $File)
}
foreach ($Directory in @("stereofine", "assets", "tests", "docs", "licenses")) {
    Copy-Item -Recurse -Force (Join-Path $Root $Directory) (Join-Path $SourceOut $Directory)
}

# No generated caches or local state belong in the release source snapshot.
Get-ChildItem -Path $Dist -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $Dist -Recurse -Directory -Filter ".pytest_cache" | Remove-Item -Recurse -Force
Get-ChildItem -Path $Dist -Recurse -File -Filter "*.pyc" | Remove-Item -Force

# Record the exact environment used for this binary build.
$PythonVersion = (& $Python -c "import platform; print(platform.python_version())").Trim()
$PyInstallerVersion = (& $Python -m PyInstaller --version).Trim()
$CustomTkinterVersion = (& $Python -c "import importlib.metadata as m; print(m.version('customtkinter'))").Trim()
$NumPyVersion = (& $Python -c "import numpy; print(numpy.__version__)").Trim()
$OpenCVVersion = (& $Python -c "import cv2; print(cv2.__version__)").Trim()
$PillowVersion = (& $Python -c "import PIL; print(PIL.__version__)").Trim()

$BuildInfoPath = Join-Path $Dist "BUILD_INFO.txt"
$BuildLines = @(
    "StereoFine 1.0",
    "Built: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss K'))",
    "Platform: Windows x64",
    "Python: $PythonVersion",
    "PyInstaller: $PyInstallerVersion",
    "CustomTkinter: $CustomTkinterVersion",
    "NumPy: $NumPyVersion",
    "OpenCV-Python: $OpenCVVersion",
    "Pillow: $PillowVersion",
    "ExifTool package: 13.53"
)
$BuildLines | Set-Content -Encoding UTF8 $BuildInfoPath

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Compress-Archive -Path $Dist -DestinationPath $ZipPath -CompressionLevel Optimal

$Hash = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()
"$Hash  StereoFine_1.0.zip" | Set-Content -Encoding ASCII (Join-Path $ReleaseDir "SHA256SUMS.txt")

Write-Host ""
Write-Host "Release build created successfully."
Write-Host "Folder:" $Dist
Write-Host "ZIP:   " $ZipPath
Write-Host "SHA256:" $Hash
Write-Host ""
Write-Host "Now extract the ZIP into a fresh folder and perform the short manual Windows smoke check in BUILD_WINDOWS.md."
