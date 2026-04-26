FROM python:3.12-alpine3.20
WORKDIR /srv

RUN addgroup -S app && adduser -S app -G app \
 && chown app:app /srv

RUN apk add --no-cache python3 \
    ca-certificates \
    gcc \
    git \
    g++ \
    linux-headers \
    libxml2-dev \
    libxslt-dev \
    python3-dev \
    tzdata \
    libffi-dev \
    openssl-dev \
    krb5-pkinit \
    krb5-dev \
    krb5 \
    openldap-dev \
    unixodbc-dev \
    dcron \
    su-exec

ENV TZ=Etc/Universal
RUN ln -sf /usr/share/zoneinfo/Ect/Universal /etc/localtime

COPY requirements.txt ./
COPY requirements-extras.txt ./
COPY requirements-ansible.txt ./

RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir -r requirements-extras.txt
RUN pip3 install --no-cache-dir -r requirements-ansible.txt
RUN pip3 install --no-cache-dir gunicorn

COPY ./deploy_configs/run_cron.sh /etc/periodic/15min/


ARG config
ENV config=$config

COPY --chown=app:app . /srv/


# Container starts as root so the entrypoint can start crond (which needs
# root) and so self_configure can create /srv/local_config.py on first boot.
# The entrypoint drops privileges to 'app' via su-exec before running the
# CMD, so gunicorn itself never runs as root.
ENTRYPOINT ["/srv/entrypoint.sh"]

CMD ["gunicorn", "--config", "/srv/deploy_configs/gunicorn.conf.py", "app:app"]

EXPOSE 9090
# Optional MCP server port — only listened on when MCPSERVER_ENABLED=1.
EXPOSE 8765
