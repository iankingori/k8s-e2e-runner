package kube_proxy

type IPv4 struct {
	IP      string `json:"ip"`
	Gateway string `json:"gateway"`
}

type SourceVip struct {
	IP4 IPv4 `json:"ip4"`
}
