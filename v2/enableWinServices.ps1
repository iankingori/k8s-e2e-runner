# Variables
$cert = New-SelfSignedCertificate -DnsName (hostname) -CertStoreLocation Cert:\LocalMachine\My
$ssh_package = (Get-WindowsCapability -Online | ? Name -Like 'OpenSSH.Server*').Name
$ssh_config = "C:\ProgramData\ssh\sshd_config"

# Enable WinRM
winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"$(hostname)`"; CertificateThumbprint=`"$($cert.Thumbprint)`"}"
winrm set winrm/config/service/auth "@{Basic=`"true`"}"

# Enable SSH
Add-WindowsCapability -Online -Name $ssh_package

# Start SSHD to create default config
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# Modify SSHD config
((Get-Content -path $ssh_config -Raw) -replace '#SyslogFacility AUTH','SyslogFacility LOCAL0') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace '#LogLevel INFO','LogLevel DEBUG3') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace 'Match Group administrators','') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace 'AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys','') | Set-Content -Path $ssh_config

# Restart SSHD to load new config
Restart-Service sshd

# Add firewall rules
New-NetFirewallRule -Name winRM -Description "TCP traffic for WinRM" -Action Allow -LocalPort 5986 -Enabled True -DisplayName "WinRM Traffic" -Protocol TCP -ErrorAction SilentlyContinue
New-NetFirewallRule -Name SSH -Description "TCP traffic for SSH" -Action Allow -LocalPort 22 -Enabled True -DisplayName "SSH Traffic" -Protocol TCP -ErrorAction SilentlyContinue
