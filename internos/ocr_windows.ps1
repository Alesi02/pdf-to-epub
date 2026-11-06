param([string]$Image, [string]$Language = 'auto', [switch]$List)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
$method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($operation, $type) {
    $task = $method.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$available = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
if ($List) {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    ConvertTo-Json -InputObject @($available | ForEach-Object { ($_.LanguageTag -split '-')[0] } | Select-Object -Unique) -Compress
    exit
}
$wanted = $Language -split ','
$languages = @($available | Where-Object { $Language -eq 'auto' -or ($_.LanguageTag -split '-')[0] -in $wanted } | Group-Object { ($_.LanguageTag -split '-')[0] } | ForEach-Object { $_.Group[0] })
if (-not $languages) { throw 'No hay idiomas OCR compatibles instalados en Windows.' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Image)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$candidates = @($languages | ForEach-Object {
$lang = $_
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @($result.Lines | ForEach-Object {
    $words = @($_.Words | ForEach-Object { @{text=$_.Text; x=$_.BoundingRect.X; y=$_.BoundingRect.Y; w=$_.BoundingRect.Width; h=$_.BoundingRect.Height} })
    @{text=$_.Text; words=$words}
})
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@{language=$lang.LanguageTag; lines=$lines}
})
ConvertTo-Json -InputObject @{candidates=$candidates} -Depth 8 -Compress
$bitmap.Dispose(); $stream.Dispose()
