param(
    [string]$InputDir = ".",
    [string]$OutputPath = ".\WordTables_Combined.xlsx"
)

Add-Type -AssemblyName "System.IO.Compression"
Add-Type -AssemblyName "System.IO.Compression.FileSystem"

function Get-SafeSheetName {
    param(
        [string]$BaseName,
        [hashtable]$UsedNames
    )

    $name = $BaseName -replace '[:\\\/\?\*\[\]]', "_"
    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = "Sheet"
    }

    if ($name.Length -gt 31) {
        $name = $name.Substring(0, 31)
    }

    if (-not $UsedNames.ContainsKey($name)) {
        $UsedNames[$name] = $true
        return $name
    }

    $i = 1
    while ($true) {
        $suffix = "_$i"
        $maxBaseLength = 31 - $suffix.Length
        $candidateBase = $name
        if ($candidateBase.Length -gt $maxBaseLength) {
            $candidateBase = $candidateBase.Substring(0, $maxBaseLength)
        }
        $candidate = "$candidateBase$suffix"
        if (-not $UsedNames.ContainsKey($candidate)) {
            $UsedNames[$candidate] = $true
            return $candidate
        }
        $i++
    }
}

function Get-DocxXmlDocument {
    param([string]$DocxPath)

    $zip = $null
    $stream = $null
    $reader = $null
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($DocxPath)
        $entry = $zip.GetEntry("word/document.xml")
        if ($null -eq $entry) {
            return $null
        }

        $stream = $entry.Open()
        $reader = New-Object System.IO.StreamReader($stream)
        $xmlContent = $reader.ReadToEnd()

        $xml = New-Object System.Xml.XmlDocument
        $xml.LoadXml($xmlContent)
        return $xml
    }
    finally {
        if ($reader -ne $null) { $reader.Dispose() }
        if ($stream -ne $null) { $stream.Dispose() }
        if ($zip -ne $null) { $zip.Dispose() }
    }
}

$resolvedInput = (Resolve-Path $InputDir).Path
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$docFiles = Get-ChildItem -Path $resolvedInput -File -Filter "*.docx" | Sort-Object Name

if (-not $docFiles) {
    Write-Host "No .docx files found in $resolvedInput"
    exit 0
}

if (Test-Path $resolvedOutput) {
    Remove-Item -Path $resolvedOutput -Force
}

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Add()
    while ($workbook.Worksheets.Count -gt 1) {
        $workbook.Worksheets.Item($workbook.Worksheets.Count).Delete()
    }
    $firstSheet = $workbook.Worksheets.Item(1)

    $usedSheetNames = @{}
    $processedCount = 0
    $sheetCount = 0

    foreach ($file in $docFiles) {
        $processedCount++
        Write-Host "Processing: $($file.Name)"

        $xml = Get-DocxXmlDocument -DocxPath $file.FullName
        if ($null -eq $xml) {
            Write-Host "  document.xml not found, skipped."
            continue
        }

        $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $ns.AddNamespace("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main")

        $tables = $xml.SelectNodes("//w:tbl", $ns)
        if ($null -eq $tables -or $tables.Count -eq 0) {
            Write-Host "  No tables, skipped."
            continue
        }

        if ($sheetCount -eq 0) {
            $sheet = $firstSheet
        } else {
            $sheet = $workbook.Worksheets.Add()
        }

        $sheetName = Get-SafeSheetName -BaseName $file.BaseName -UsedNames $usedSheetNames
        $sheet.Name = $sheetName

        $outRow = 1
        $tableIndex = 1

        foreach ($table in $tables) {
            $sheet.Cells.Item($outRow, 1).Value2 = "Table $tableIndex"
            $outRow++

            $rows = $table.SelectNodes("./w:tr", $ns)
            foreach ($row in $rows) {
                $cells = $row.SelectNodes("./w:tc", $ns)
                $col = 1
                foreach ($cell in $cells) {
                    $textNodes = $cell.SelectNodes(".//w:t", $ns)
                    $cellText = ($textNodes | ForEach-Object { $_.InnerText }) -join ""
                    $cellText = $cellText.Trim()
                    $cellText = $cellText -replace "[\x00-\x08\x0B\x0C\x0E-\x1F]", ""
                    if ($cellText.Length -gt 32767) {
                        $cellText = $cellText.Substring(0, 32767)
                    }

                    try {
                        $sheet.Cells.Item($outRow, $col).Value2 = $cellText
                    }
                    catch {
                        Write-Host "  Cell write failed in $($file.Name) [table=$tableIndex row=$outRow col=$col], value replaced."
                        $sheet.Cells.Item($outRow, $col).Value2 = "[UNSUPPORTED_VALUE]"
                    }
                    $col++
                }
                $outRow++
            }

            $outRow++
            $tableIndex++
        }

        $sheet.UsedRange.EntireColumn.AutoFit() | Out-Null
        $sheetCount++
        Write-Host "  Tables exported: $($tables.Count)"
    }

    if ($sheetCount -eq 0) {
        $firstSheet.Name = "NoTables"
        $firstSheet.Cells.Item(1, 1).Value2 = "No tables found in .docx files."
    }

    $workbook.SaveAs($resolvedOutput, 51)

    Write-Host "Processed documents: $processedCount"
    Write-Host "Sheets created: $sheetCount"
    Write-Host "Saved: $resolvedOutput"
}
finally {
    if ($workbook -ne $null) {
        $workbook.Close($true)
    }
    if ($excel -ne $null) {
        $excel.Quit()
    }
}
