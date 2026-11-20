<#
  Stoa Check - "Will my stuff work on Stoa?"

  Run this on a Windows PC before switching. It looks at the PC's hardware, installed apps, Steam games,
  printers and gaming gear, and writes a report to the Desktop:

    Stoa readiness report.html   what works, what has a Stoa version, what to do first
    Stoa-plan.json               read by Stoa's "Move from Windows" to install the same apps for you

  Nothing is changed and nothing is sent anywhere except two public look-ups for game ratings
  (protondb.com and AreWeAntiCheatYet on GitHub). Runs on Windows 10 and 11 (Windows PowerShell 5.1).
  Start it with "Stoa Check.cmd" (double-click). For TPM, Secure Boot and BitLocker details, right-click it
  and choose "Run as administrator".
#>
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($text) { Write-Host $text -ForegroundColor Cyan }
function Esc($s) { if ($null -eq $s) { return '' }; return [System.Net.WebUtility]::HtmlEncode([string]$s) }
function GB($bytes) { if (-not $bytes) { return '?' }; return ('{0:N0} GB' -f ($bytes / 1GB)) }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

Say 'Stoa Check: looking at this PC (nothing is changed)...'

# ------------------------------------------------------------------ hardware
$os   = Get-CimInstance Win32_OperatingSystem
$cs   = Get-CimInstance Win32_ComputerSystem
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic Display|Remote|Virtual' })
$ram  = [double]$cs.TotalPhysicalMemory
$sysDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$disks = @(Get-CimInstance Win32_DiskDrive)
$uefi = ($env:firmware_type -eq 'UEFI')
if (-not $env:firmware_type) { $uefi = Test-Path "$env:SystemRoot\Boot\EFI" }

$tpm = 'Unknown (run as administrator to check)'
$secureBoot = 'Unknown (run as administrator to check)'
$bitlocker = 'Unknown (run as administrator to check)'
if ($isAdmin) {
    $t = Get-Tpm
    $tpm = if ($t -and $t.TpmPresent) { 'Yes' } else { 'No' }
    $sb = Confirm-SecureBootUEFI
    $secureBoot = if ($sb -eq $true) { 'On' } elseif ($sb -eq $false) { 'Off' } else { 'Not supported (legacy BIOS)' }
    $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive
    $bitlocker = if ($bl -and $bl.ProtectionStatus -eq 'On') { 'On' } else { 'Off' }
}

$hw = @()
$hwOk = $true
$hw += ,@('This PC', "$($cs.Manufacturer) $($cs.Model)", 'ok', '')
$hw += ,@('Windows', "$($os.Caption) ($($os.Version))", 'ok', '')
$is64 = ($os.OSArchitecture -match '64')
$hw += ,@('Processor', $cpu.Name.Trim(), $(if ($is64) { 'ok' } else { 'bad' }),
          $(if ($is64) { '' } else { 'Stoa needs a 64-bit processor.' }))
if (-not $is64) { $hwOk = $false }
$ramGB = [math]::Round($ram / 1GB)
$hw += ,@('Memory', "$ramGB GB", $(if ($ramGB -ge 4) { 'ok' } else { 'warn' }),
          $(if ($ramGB -ge 8) { '' } elseif ($ramGB -ge 4) { 'Fine for everyday use; 8 GB or more is better for games and Stoa AI Local.' } else { 'Stoa needs at least 4 GB.' }))
foreach ($g in $gpus) {
    $note = ''
    if ($g.Name -match 'NVIDIA') { $note = 'Stoa installs the NVIDIA driver for you (Settings > Software & Updates, or the Store: "graphics-drivers").' }
    elseif ($g.Name -match 'AMD|Radeon|Intel') { $note = 'Works straight away - drivers are built in.' }
    $hw += ,@('Graphics', $g.Name, 'ok', $note)
}
foreach ($d in $disks) {
    $kind = if ($d.MediaType -match 'SSD' -or $d.Model -match 'SSD|NVMe') { 'SSD' } else { $d.MediaType }
    $hw += ,@('Drive', "$($d.Model) - $(GB $d.Size) $kind", 'ok', '')
}
$free = [double]$sysDrive.FreeSpace
$hw += ,@('Free space on C:', (GB $free), $(if ($free -ge 40GB) { 'ok' } else { 'warn' }),
          $(if ($free -ge 40GB) { 'Enough to install Stoa alongside Windows.' } else { 'Install alongside Windows needs about 40 GB free - or replace Windows / use another drive.' }))
$hw += ,@('Start-up', $(if ($uefi) { 'UEFI' } else { 'Legacy BIOS' }), 'ok', '')
$hw += ,@('Secure Boot', $secureBoot, $(if ($secureBoot -eq 'On') { 'warn' } else { 'ok' }),
          $(if ($secureBoot -eq 'On') { 'If the Stoa USB stick does not start, turn Secure Boot off in the BIOS/UEFI settings (you can turn it back on after).' } else { '' }))
$hw += ,@('TPM', $tpm, 'ok', $(if ($tpm -eq 'Yes') { 'Stoa can use it to unlock an encrypted drive automatically.' } else { '' }))
$hw += ,@('BitLocker', $bitlocker, $(if ($bitlocker -eq 'On') { 'warn' } else { 'ok' }),
          $(if ($bitlocker -eq 'On') { 'To install alongside Windows, turn BitLocker / Device Encryption off first (save your recovery key: aka.ms/myrecoverykey).' } else { '' }))

# Fast Startup leaves the Windows drive locked
$hiber = Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' 'HiberbootEnabled'
if ($hiber -eq 1) {
    $hw += ,@('Fast Startup', 'On', 'warn', 'Turn it off before installing alongside Windows: Control Panel > Power Options > Choose what the power buttons do > untick "Turn on fast startup".')
}

# ------------------------------------------------------------------ apps
Say 'Checking installed apps...'
# pattern, verdict (same | alt | builtin | skip | no), Stoa catalogue id, note
$rules = @(
    @('^Google Chrome', 'same', 'google-chrome', ''), @('^Microsoft Edge$', 'same', 'microsoft-edge', ''),
    @('^Mozilla Firefox', 'same', 'firefox', ''), @('^Brave', 'same', 'brave', ''), @('^Vivaldi', 'same', 'vivaldi', ''),
    @('^Opera', 'alt', 'brave', 'Opera has no Linux version with sync; Brave or Chrome are close.'),
    @('Microsoft 365|Microsoft Office|Office 16|Office 19|Office 21', 'same', 'microsoft-365', 'Word, Excel, PowerPoint and Outlook as apps on Stoa (the online versions). For offline files, ONLYOFFICE opens them too.'),
    @('Microsoft Teams', 'same', 'microsoft-teams', ''), @('^Zoom', 'same', 'zoom', ''), @('^Slack', 'same', 'slack', ''),
    @('^Discord', 'same', 'discord', ''), @('WhatsApp', 'same', 'whatsapp', ''), @('^Spotify', 'same', 'spotify', ''),
    @('^VLC', 'same', 'vlc', ''), @('^GIMP', 'same', 'gimp', ''), @('^Inkscape', 'same', 'inkscape', ''),
    @('^OBS Studio', 'same', 'obs-studio', ''), @('Visual Studio Code', 'same', 'vscode', ''), @('^Git( version|$)', 'same', 'git', ''),
    @('Notepad\+\+', 'same', 'notepad-plus-plus', ''), @('^Steam$', 'same', 'steam', 'Your games carry over - see below.'),
    @('Epic Games Launcher|GOG Galaxy|Amazon Games', 'alt', 'heroic', 'Heroic Games Launcher runs your Epic, GOG and Amazon games.'),
    @('EA app|^Origin$|Ubisoft Connect|Battle\.net', 'alt', 'lutris', 'Lutris installs this launcher for you.'),
    @('^Obsidian', 'same', 'obsidian', ''), @('^Notion', 'same', 'notion', ''), @('^Telegram', 'same', 'telegram', ''),
    @('^Signal', 'same', 'signal', ''), @('^Audacity', 'same', 'audacity', ''), @('^Kdenlive', 'same', 'kdenlive', ''),
    @('^Shotcut', 'same', 'shotcut', ''), @('^HandBrake', 'same', 'handbrake', ''), @('^Krita', 'same', 'krita', ''),
    @('^Blender', 'same', 'blender', ''), @('^Calibre', 'same', 'calibre', ''), @('^Mozilla Thunderbird', 'same', 'thunderbird', ''),
    @('^Dropbox', 'same', 'dropbox-sync', ''), @('OneDrive', 'same', 'onedrive-sync', ''), @('Google Drive', 'same', 'google-drive-sync', ''),
    @('^iCloud', 'same', 'icloud', 'iCloud on the web (Photos, Drive, Mail).'), @('^Bitwarden', 'same', 'bitwarden', ''),
    @('^KeePass', 'same', 'keepassxc', ''), @('^qBittorrent', 'same', 'qbittorrent', ''), @('^AnyDesk', 'same', 'anydesk', ''),
    @('^RustDesk', 'same', 'rustdesk', ''), @('^7-Zip', 'same', '7zip', ''), @('^WinRAR', 'alt', '7zip', 'Stoa opens .rar files already; 7-Zip is there too.'),
    @('^Plex', 'same', 'plex', ''), @('^Minecraft', 'alt', 'prism-launcher', 'Prism Launcher runs Minecraft Java Edition.'),
    @('Adobe Acrobat|Adobe Reader|Foxit', 'builtin', '', 'Stoa opens PDFs with its built-in Document Viewer.'),
    @('Adobe Photoshop', 'alt', 'krita', 'Photoshop has no Linux version. Krita or GIMP are the closest; Photopea in the browser opens PSD files.'),
    @('Adobe Premiere', 'alt', 'kdenlive', 'Premiere has no Linux version; Kdenlive or DaVinci Resolve are the closest.'),
    @('Adobe Lightroom', 'alt', 'darktable', 'Lightroom has no Linux version; darktable is the closest.'),
    @('^iTunes|Apple Music', 'alt', 'apple-music', 'Apple Music on the web.'),
    @('GeForce Experience|NVIDIA App', 'alt', 'graphics-drivers', 'Stoa installs the NVIDIA driver; GeForce NOW is in the Store.'),
    @('Razer Synapse|Razer Central|Razer Cortex', 'alt', 'razer', "Synapse is Windows-only. Stoa's Razer support (OpenRazer + Polychromatic) does lighting, DPI and battery."),
    @('Logitech G HUB|Logitech Gaming Software|Corsair iCUE|SteelSeries GG|Armoury Crate|MSI Center|SignalRGB', 'alt', 'openrgb', 'Windows-only; OpenRGB controls the lighting on most of this gear.'),
    @('MSI Afterburner|RivaTuner', 'builtin', '', "Stoa's Task Manager and Game Mode cover monitoring and performance."),
    @('CCleaner', 'alt', 'bleachbit', 'Stoa cleans up by itself (Task Manager > Health); BleachBit is there too.'),
    @('Malwarebytes|Norton|McAfee|Avast|AVG|Kaspersky|Bitdefender|ESET|Avira|Webroot|Windows Defender', 'builtin', '', 'Stoa Protect (antivirus and firewall) is built in.'),
    @('Microsoft Visual C\+\+|\.NET|Windows SDK|DirectX|Redistributable|Runtime|Update for|Security Update|Hotfix|Driver|Realtek|Intel\(R\)|AMD Software|AMD Chipset|NVIDIA (Graphics|PhysX|HD Audio|FrameView|USBC)|Microsoft Update Health|Windows PC Health|Microsoft Edge (Update|WebView)|Teams Machine-Wide|Office 16 Click-to-Run|Bonjour|Java Auto Updater', 'skip', '', '')
)

$keys = @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')
$installed = @(Get-ItemProperty $keys | Where-Object {
    $_.DisplayName -and $_.SystemComponent -ne 1 -and -not $_.ParentKeyName -and $_.DisplayName -notmatch '^KB\d+' } |
    Sort-Object DisplayName -Unique)
# Store apps people actually use
$storeApps = @(Get-AppxPackage | Where-Object { $_.Name -match 'Spotify|WhatsApp|Netflix|Disney|PrimeVideo|Telegram|Discord|iCloud|Zoom' } |
    ForEach-Object { [pscustomobject]@{ DisplayName = ($_.Name -replace '^[^.]+\.', '') } })
$installed += $storeApps

$apps = @(); $planIds = @()
foreach ($a in $installed) {
    $name = [string]$a.DisplayName
    $hit = $null
    foreach ($r in $rules) { if ($name -match $r[0]) { $hit = $r; break } }
    if ($hit -and $hit[1] -eq 'skip') { continue }
    if ($hit) {
        $apps += ,@($name, $hit[1], $hit[2], $hit[3])
        if ($hit[2] -and $planIds -notcontains $hit[2]) { $planIds += $hit[2] }
    } else {
        $apps += ,@($name, 'wine', '', "No Linux version known. Many Windows programs install on Stoa directly (double-click the .exe) - check appdb.winehq.org for this one.")
    }
}
# Streaming apps on Stoa are web apps
foreach ($m in @(@('Netflix', 'netflix'), @('Disney', 'disney-plus'), @('PrimeVideo', 'prime-video'))) {
    if ($storeApps | Where-Object { $_.DisplayName -match $m[0] }) { if ($planIds -notcontains $m[1]) { $planIds += $m[1] } }
}

# ------------------------------------------------------------------ Steam games
Say 'Checking Steam games...'
$games = @()
$steamPath = (Get-ItemProperty 'HKCU:\Software\Valve\Steam').SteamPath
if ($steamPath) {
    $libs = @($steamPath -replace '/', '\')
    $vdf = Join-Path $libs[0] 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) { $libs += ($m.Groups[1].Value -replace '\\\\', '\') }
    }
    $seen = @{}
    foreach ($lib in ($libs | Select-Object -Unique)) {
        foreach ($acf in Get-ChildItem (Join-Path $lib 'steamapps') -Filter 'appmanifest_*.acf') {
            $text = Get-Content $acf.FullName -Raw
            $id = [regex]::Match($text, '"appid"\s+"(\d+)"').Groups[1].Value
            $nm = [regex]::Match($text, '"name"\s+"([^"]*)"').Groups[1].Value
            if ($id -and -not $seen[$id] -and $nm -notmatch 'Proton|Steamworks|Redistributable|Steam Linux Runtime|SteamVR') {
                $seen[$id] = $true
                $games += [pscustomobject]@{ Id = $id; Name = $nm; Library = $lib; Tier = $null; AC = $null; ACNames = '' }
            }
        }
    }
}
if ($games.Count -gt 0) {
    $ac = @{}
    try {
        $acData = Invoke-RestMethod 'https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json' -TimeoutSec 25
        foreach ($g in $acData) { if ($g.storeIds.steam) { $ac[[string]$g.storeIds.steam] = $g } }
    } catch { }
    $n = 0
    foreach ($g in $games) {
        $n++
        Write-Progress -Activity 'Looking up game ratings' -Status $g.Name -PercentComplete (100 * $n / $games.Count)
        try {
            $s = Invoke-RestMethod "https://www.protondb.com/api/v1/reports/summaries/$($g.Id).json" -TimeoutSec 10
            $g.Tier = if ($s.trendingTier) { $s.trendingTier } else { $s.tier }
        } catch { }
        if ($ac.ContainsKey($g.Id)) { $g.AC = $ac[$g.Id].status; $g.ACNames = ($ac[$g.Id].anticheats -join ', ') }
    }
}
function GameVerdict($g) {
    if ($g.AC -in @('Denied', 'Broken')) { return @('no', "Online play is blocked by its anti-cheat ($($g.ACNames)).") }
    if ($g.AC -eq 'Planned') { return @('maybe', 'Its anti-cheat blocks Linux for now; the developers plan to allow it.') }
    switch ($g.Tier) {
        'platinum' { return @('yes', 'Works perfectly') }
        'gold'     { return @('yes', 'Works well') }
        'silver'   { return @('yes', 'Works, with small issues') }
        'bronze'   { return @('maybe', 'Runs, with problems - see protondb.com') }
        'borked'   { return @('no', "Doesn't run on Linux yet") }
    }
    return @('unknown', 'No reports yet - most games work')
}

# ------------------------------------------------------------------ printers and gear
$printers = @(Get-Printer | Where-Object { $_.Name -notmatch 'PDF|XPS|OneNote|Fax|Send To' } | ForEach-Object { $_.Name })
$gear = @()
$vendors = @{ 'VID_1532' = @('Razer', 'Lighting, DPI and battery work with Stoa''s Razer support (Store: "Razer devices").');
              'VID_046D' = @('Logitech', 'Works; lighting and DPI with OpenRGB or Piper (Store).');
              'VID_1B1C' = @('Corsair', 'Works; lighting with OpenRGB (Store).');
              'VID_1038' = @('SteelSeries', 'Works; lighting with OpenRGB (Store).');
              'VID_045E' = @('Xbox controller', 'Works straight away (Steam and most games).');
              'VID_054C' = @('PlayStation controller', 'Works straight away (Steam and most games).') }
foreach ($dev in Get-PnpDevice -PresentOnly) {
    foreach ($k in $vendors.Keys) {
        if ($dev.InstanceId -match $k -and $gear -notcontains $vendors[$k][0]) { $gear += $vendors[$k][0] }
    }
}
$wifi = @(Get-NetAdapter -Physical | Where-Object { $_.InterfaceDescription -match 'Wi-?Fi|Wireless|802\.11|WLAN' } | ForEach-Object { $_.InterfaceDescription })

# ------------------------------------------------------------------ report
$appsSame = @($apps | Where-Object { $_[1] -in @('same', 'builtin') }).Count
$appsAlt  = @($apps | Where-Object { $_[1] -eq 'alt' }).Count
$appsWine = @($apps | Where-Object { $_[1] -eq 'wine' }).Count
$gv = @{ yes = 0; maybe = 0; no = 0; unknown = 0 }
foreach ($g in $games) { $gv[(GameVerdict $g)[0]]++ }

$badge = @{ ok = '<span class="b ok">OK</span>'; warn = '<span class="b warn">Check</span>'; bad = '<span class="b bad">Problem</span>';
            same = '<span class="b ok">On Stoa</span>'; builtin = '<span class="b ok">Built in</span>'; alt = '<span class="b alt">Alternative</span>';
            wine = '<span class="b warn">Windows app</span>'; yes = '<span class="b ok">Yes</span>'; maybe = '<span class="b warn">Maybe</span>';
            no = '<span class="b bad">No</span>'; unknown = '<span class="b alt">Unknown</span>' }

$sb = New-Object System.Text.StringBuilder
[void]$sb.Append(@"
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stoa readiness report</title><style>
:root{--bg:#121829;--card:#1a2238;--line:#263150;--text:#e8ecf5;--muted:#8a93aa;--blue:#4f8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 "Segoe UI",Inter,system-ui,sans-serif}
header{background:linear-gradient(135deg,#1e3a7a,#4f3f9c);padding:32px 24px}header h1{margin:0;font-size:28px}header p{margin:6px 0 0;color:#c9d3ea}
main{max-width:1000px;margin:0 auto;padding:20px 16px 60px}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:8px 0 24px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}.tile b{font-size:26px;display:block}
h2{margin:28px 0 10px;font-size:20px}table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}
td,th{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600;font-size:13px}
td.n{color:var(--muted);font-size:13px}.b{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:700;white-space:nowrap}
.ok{background:#1f4d3a;color:#7ee2b0}.warn{background:#4d3d1a;color:#f5c66b}.bad{background:#4d1f26;color:#ff8a98}.alt{background:#263150;color:#9ab4ff}
.next{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:14px 18px}
.next li{margin:6px 0}footer{color:var(--muted);font-size:13px;margin-top:30px}
</style></head><body><header><h1>Will my stuff work on Stoa?</h1>
<p>$(Esc "$($cs.Manufacturer) $($cs.Model)") &middot; checked $(Get-Date -Format 'd MMMM yyyy')</p></header><main>
<div class="sum">
<div class="tile"><b>$(if ($hwOk) { 'Ready' } else { 'Not ready' })</b>Hardware</div>
<div class="tile"><b>$appsSame of $($apps.Count)</b>apps are on Stoa or built in</div>
<div class="tile"><b>$appsAlt</b>apps have a good alternative</div>
<div class="tile"><b>$($gv.yes) of $($games.Count)</b>Steam games known to run</div>
</div>
<div class="next"><b>What to do next</b><ol>
<li>Download Stoa and put it on a USB stick (8 GB or more).</li>
"@)
if ($hiber -eq 1 -or $bitlocker -eq 'On') { [void]$sb.Append('<li>Fix the items marked <span class="b warn">Check</span> under Hardware before installing alongside Windows.</li>') }
[void]$sb.Append('<li>Start the PC from the USB stick, try Stoa, then choose <b>Install alongside Windows</b> (or replace it).</li>')
[void]$sb.Append('<li>On Stoa, open <b>Move from Windows</b>: it brings your files, bookmarks and games over, and installs the apps in this report.</li></ol></div>')

[void]$sb.Append('<h2>Hardware</h2><table><tr><th>Part</th><th>This PC</th><th></th><th>Notes</th></tr>')
foreach ($h in $hw) { [void]$sb.Append("<tr><td>$(Esc $h[0])</td><td>$(Esc $h[1])</td><td>$($badge[$h[2]])</td><td class=n>$(Esc $h[3])</td></tr>") }
if ($wifi) { [void]$sb.Append("<tr><td>Wi-Fi</td><td>$(Esc ($wifi -join ', '))</td><td>$($badge[$(if ($wifi -match 'Broadcom') { 'warn' } else { 'ok' })])</td><td class=n>$(if ($wifi -match 'Broadcom') { 'Broadcom Wi-Fi may need a driver: connect a network cable the first time and Stoa sets it up.' } else { '' })</td></tr>") }
[void]$sb.Append('</table>')

[void]$sb.Append("<h2>Apps ($($apps.Count))</h2><table><tr><th>App on Windows</th><th></th><th>On Stoa</th></tr>")
foreach ($a in ($apps | Sort-Object { @{ same = 0; builtin = 1; alt = 2; wine = 3 }[$_[1]] }, { $_[0] })) {
    $note = if ($a[3]) { $a[3] } elseif ($a[2]) { 'Same app - Stoa can install it for you.' } else { '' }
    [void]$sb.Append("<tr><td>$(Esc $a[0])</td><td>$($badge[$a[1]])</td><td class=n>$(Esc $note)</td></tr>")
}
[void]$sb.Append('</table>')

if ($games.Count -gt 0) {
    [void]$sb.Append("<h2>Steam games ($($games.Count))</h2><p class=n>From ProtonDB player reports and AreWeAntiCheatYet. Stoa can add these games to Steam without downloading them again (Move from Windows).</p><table><tr><th>Game</th><th>Runs?</th><th>Details</th></tr>")
    foreach ($g in ($games | Sort-Object { @{ no = 0; maybe = 1; unknown = 2; yes = 3 }[(GameVerdict $_)[0]] }, Name)) {
        $v = GameVerdict $g
        [void]$sb.Append("<tr><td>$(Esc $g.Name)</td><td>$($badge[$v[0]])</td><td class=n>$(Esc $v[1])</td></tr>")
    }
    [void]$sb.Append('</table>')
}
if ($printers -or $gear) {
    [void]$sb.Append('<h2>Printers and devices</h2><table>')
    foreach ($p in $printers) { [void]$sb.Append("<tr><td>$(Esc $p)</td><td>$($badge.ok)</td><td class=n>Most printers are found automatically on Stoa; HP, Brother, Canon and Epson drivers are included.</td></tr>") }
    foreach ($g in $gear) { $info = ($vendors.Values | Where-Object { $_[0] -eq $g } | Select-Object -First 1); [void]$sb.Append("<tr><td>$(Esc $g)</td><td>$($badge.ok)</td><td class=n>$(Esc $info[1])</td></tr>") }
    [void]$sb.Append('</table>')
}
[void]$sb.Append('<footer>Made by Stoa Check. Nothing on this PC was changed. Stoa-plan.json on your Desktop lets Stoa install the same apps for you.</footer></main></body></html>')

$desktop = [Environment]::GetFolderPath('Desktop')
$report = Join-Path $desktop 'Stoa readiness report.html'
[IO.File]::WriteAllText($report, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
$plan = [ordered]@{
    version = 1; created = (Get-Date).ToString('s'); pc = "$($cs.Manufacturer) $($cs.Model)"; user = $env:USERNAME
    apps = $planIds; steam_games = @($games | ForEach-Object { $_.Id }); printers = $printers; gear = $gear
}
[IO.File]::WriteAllText((Join-Path $desktop 'Stoa-plan.json'), ($plan | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))

Say "Done. Your report is on the Desktop: Stoa readiness report.html"
Start-Process $report
