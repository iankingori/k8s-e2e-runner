class ConnectionFailed(Exception):
    pass


class ShellCmdFailed(Exception):
    pass


class ConformanceTestsFailed(Exception):
    pass


class BuildFailed(Exception):
    pass


class EnvVarNotFound(Exception):
    pass


class PodNotFound(Exception):
    pass


class KubernetesEndpointNotFound(Exception):
    pass


class KubernetesNodeNotFound(Exception):
    pass


class KubernetesVersionNotFound(Exception):
    pass


class InvalidKubernetesEndpoint(Exception):
    pass


class InvalidOperatingSystem(Exception):
    pass


class VersionMismatch(Exception):
    pass
