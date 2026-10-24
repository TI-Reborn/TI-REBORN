$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'base\shared config\items.xml'
if (!(Test-Path -LiteralPath $target)) { throw 'Place this installer beside Launcher.cmd in the game folder.' }
if (Get-Process ti -ErrorAction SilentlyContinue) { throw 'Close the game, then run this installer again.' }
$doc = New-Object System.Xml.XmlDocument
$doc.PreserveWhitespace = $true
$doc.Load($target)
$rules = @(
    @(256, 'melee', '25'),
    @(262, 'sight', '1'),
    @(264, 'maxload', '200'), @(341, 'armor', '85')
)
foreach ($item in $doc.SelectNodes('/items/item')) {
    $itype = $item.SelectSingleNode("value[@key='itype']")
    if ($itype -and $itype.GetAttribute('val') -eq 'armor') {
        $type = $item.SelectSingleNode("value[@key='type']")
        if (!$type) { $type = $doc.CreateElement('value'); $type.SetAttribute('key','type'); [void]$item.AppendChild($type) }
        $type.SetAttribute('val','armor')
    }
}
foreach ($old in @(@(254,'melee'),@(263,'maxload'))) {
    foreach ($node in @($doc.SelectNodes("/items/item[@id='$($old[0])']/for/add[@stat='$($old[1])']"))) {
        [void]$node.ParentNode.RemoveChild($node)
    }
}
foreach ($rule in $rules) {
    $item = $doc.SelectSingleNode("/items/item[@id='$($rule[0])']")
    if (!$item) { throw "Missing original item $($rule[0]); no files changed." }
    $stats = $item.SelectSingleNode('for')
    if (!$stats) { $stats = $doc.CreateElement('for'); [void]$item.AppendChild($stats) }
    $nodes = @($stats.SelectNodes("add[@stat='$($rule[1])']"))
    if ($nodes.Count -eq 0) {
        $node = $doc.CreateElement('add'); $node.SetAttribute('stat', $rule[1]); [void]$stats.AppendChild($node)
    } else {
        $node = $nodes[0]
        foreach ($duplicate in ($nodes | Select-Object -Skip 1)) { [void]$stats.RemoveChild($duplicate) }
    }
    $node.SetAttribute('val', $rule[2])
}
$backup = "$target.before-effects-$([guid]::NewGuid().ToString('N'))"
Copy-Item -LiteralPath $target -Destination $backup
try {
    $doc.Save($target)
    $verify = New-Object System.Xml.XmlDocument
    $verify.Load($target)
    foreach ($rule in $rules) {
        $node = $verify.SelectSingleNode("/items/item[@id='$($rule[0])']/for/add[@stat='$($rule[1])']")
        if (!$node -or $node.GetAttribute('val') -ne $rule[2]) { throw 'Verification failed.' }
    }
} catch {
    Copy-Item -LiteralPath $backup -Destination $target -Force
    throw
}
Write-Host 'Equipment descriptions updated. Start the game through Launcher.cmd.'
Write-Host 'The VPS catalog must also be updated; login replaces this local file.'
Write-Host "Backup: $backup"
