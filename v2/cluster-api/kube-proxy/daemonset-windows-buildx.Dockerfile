ARG baseImage="e2eteam/kube-proxy-windows:v1.18.5-windowsservercore-1809"

FROM ${baseImage}

ADD kube-proxy.exe /k/kube-proxy/kube-proxy.exe

# When cross-building from a Linux environment with Docker buildx, the PATH is
# inherited from the environment building the image. Therefore, the Windows
# Docker image will have the PATH broken, unless we explicitly set it to
# overwrite the default behaviour.
ENV PATH "C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0\;C:\Windows\System32\OpenSSH\;C:\Users\ContainerAdministrator\AppData\Local\Microsoft\WindowsApps;C:\utils;"
