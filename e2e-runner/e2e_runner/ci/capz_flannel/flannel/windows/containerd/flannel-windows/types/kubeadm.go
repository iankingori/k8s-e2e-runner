package types

type KubeadmNetworking struct {
	PodSubnet     string `yaml:"podSubnet"`
	ServiceSubnet string `yaml:"serviceSubnet"`
}

type KubeadmConfig struct {
	Networking KubeadmNetworking `yaml:"networking"`
}
