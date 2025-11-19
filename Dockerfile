FROM python:3.12-alpine

WORKDIR /etc/palbot/

ENV ENVIRONMENT="local"
ENV LOG_LEVEL="info"
ENV AKASH_BASE_URL=""
ENV AKASH_MODEL=""
ENV OPENAI_BASE_URL=""
ENV OPENAI_MODEL=""
ENV REGION="local"
ENV VERSION="unknown"

RUN addgroup -g 1000 palbot
RUN adduser -u 1000 -G palbot -h /home/palbot -D palbot
RUN apk -U upgrade
RUN apk add --no-cache bash build-base libffi-dev python3-dev gcompat patchelf ffmpeg

COPY ./requirements.txt /tmp/requirements.txt
COPY ./*.py /etc/palbot/

USER palbot

RUN pip3 install --progress-bar off --no-color --upgrade pip && \
    pip3 install --progress-bar off --no-color --upgrade setuptools
RUN pip3 install --progress-bar off --no-color --user -r /tmp/requirements.txt

CMD ["python", "./paldiscord.py"]
