$ErrorActionPreference = "Stop"

$cfg = Get-Content -Path /k/kubeclusterconfig.json | ConvertFrom-Json
$cfg.Kubernetes.Kubeproxy.FeatureGates += "ProxyTerminatingEndpoints=true"
$cfg | ConvertTo-Json -Depth 100 | Out-File -Encoding ascii -PSPath /k/kubeclusterconfig.json
Write-Output "Enabled ProxyTerminatingEndpoints kube-proxy feature gate"
