FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/*

COPY repos.yml /repos.yml
RUN apt-get update \
    && apt-get install -y --no-install-recommends $(python3 -c "import yaml; d=yaml.safe_load(open('/repos.yml')); print(' '.join(sorted({p for t in d['tools'] if t.get('enabled', True) for p in t.get('build', {}).get('apt_deps', [])})))") \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/install-tools.sh /scripts/install-tools.sh
RUN INSTALL_SKIP_APT=1 bash /scripts/install-tools.sh true && pip3 check

COPY scripts/osint-flow.sh /scripts/osint-flow.sh
COPY scripts/case_store.py /scripts/case_store.py
COPY dashboard /dashboard
RUN chmod +x /scripts/osint-flow.sh && ln -s /scripts/osint-flow.sh /usr/local/bin/osint

WORKDIR /workspace
CMD ["bash", "-l"]
