FROM python:3.12-alpine3.20
WORKDIR /srv

RUN addgroup -S uwsgi && adduser -S uwsgi -G uwsgi

RUN apk add --no-cache python3 \
    uwsgi \
    ca-certificates \
    gcc \
    git \
    g++ \
    linux-headers \
    libxml2-dev \
    libxslt-dev \
    python3-dev \
    uwsgi-python3 \
    tzdata \
    libffi-dev \
    openssl-dev \
    krb5-pkinit \
    krb5-dev \
    krb5 \
    openldap-dev \
    unixodbc-dev

ENV TZ=Etc/Universal
RUN ln -sf /usr/share/zoneinfo/Ect/Universal /etc/localtime

COPY requirements.txt ./
COPY requirements-extras.txt ./
COPY requirements-ansible.txt ./

RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir -r requirements-extras.txt
RUN pip3 install --no-cache-dir -r requirements-ansible.txt


ARG config
ENV config=$config

COPY . /srv/


ENTRYPOINT ["/srv/entrypoint.sh"]
USER uwsgi

CMD [ "uwsgi", "--master", "/srv/deploy_configs/uwsgi_docker.ini" ]

EXPOSE 9090
