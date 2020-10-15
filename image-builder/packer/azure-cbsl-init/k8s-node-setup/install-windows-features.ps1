$ErrorActionPreference = "Stop"

Install-WindowsFeature -Name "Containers" -IncludeManagementTools -IncludeAllSubFeature -Confirm:$false
