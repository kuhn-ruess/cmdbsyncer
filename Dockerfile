FROM python:3.10-alpine3.17
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
    openssl-dev

ENV TZ=Etc/Universal
RUN ln -sf /usr/share/zoneinfo/Ect/Universal /etc/localtime

COPY requirements.txt ./
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt


ARG config
ENV config=$config

COPY . /srv/
COPY  ./application/config-docker.py /srv/application/config.py


USER uwsgi

CMD [ "uwsgi", "--master", "/srv/deploy_configs/uwsgi_docker.ini" ]

EXPOSE 9090
