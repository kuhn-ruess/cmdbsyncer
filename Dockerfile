FROM python:3.12-alpine3.20
WORKDIR /srv

RUN addgroup -S app && adduser -S app -G app

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
    dcron

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

COPY . /srv/


ENTRYPOINT ["/srv/entrypoint.sh"]
USER app

CMD ["gunicorn", "--config", "/srv/deploy_configs/gunicorn.conf.py", "app:app"]

EXPOSE 9090
