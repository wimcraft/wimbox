FROM alpine:3.22

RUN apk add --no-cache bash git openssh-client-default supercronic curl jq tzdata \
    # Pin GitHub's host keys from its TLS-protected API rather than trusting on first use.
    && mkdir -p /etc/ssh \
    && curl -fsSL https://api.github.com/meta \
        | jq -r '.ssh_keys[] | "github.com " + .' > /etc/ssh/github_known_hosts \
    && test -s /etc/ssh/github_known_hosts \
    && apk del --no-cache jq

# ssh refuses to run as a uid with no passwd entry; compose runs this as 1000:1000.
RUN adduser -D -u 1000 backup && chmod 1777 /tmp

COPY backup.sh entrypoint.sh /usr/local/bin/

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
