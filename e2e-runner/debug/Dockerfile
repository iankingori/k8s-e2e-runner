FROM ghcr.io/e2e-win/k8s-e2e-runner:main

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

RUN ln -fs /usr/bin/python3 /usr/bin/python

WORKDIR /app
COPY . /app

ENTRYPOINT ["python", "-m", "e2e_runner.cli.shell"]
