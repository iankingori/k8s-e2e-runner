package flannel

import (
	"github.com/Microsoft/windows-container-networking/cni"
	"github.com/containernetworking/cni/pkg/types"
)

type NetConfDelegate struct {
	Type           string          `json:"type"`
	OptionalFlags  map[string]bool `json:"optionalFlags,omitempty"`
	AdditionalArgs []cni.KVP
}

type NetConf struct {
	types.NetConf

	Delegate NetConfDelegate `json:"delegate"`
}
