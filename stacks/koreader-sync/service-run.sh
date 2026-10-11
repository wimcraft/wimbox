#!/bin/sh
# Replaces /etc/service/koreader-sync-server/run from the upstream image.
#
# The original guard is `grep -q 'daemon off;'`, which matches the commented
# out `# daemon off;` already present in config/nginx.conf, so the directive is
# never appended. nginx then daemonises, `gin start` returns immediately, and
# runit restarts the service every two seconds forever - each attempt failing
# to bind 7200/17200 and writing two lines to logs/error.log. Matching the
# whole line instead keeps nginx in the foreground, where runit can supervise
# it.
grep -qx 'daemon off;' /app/koreader-sync-server/config/nginx.conf ||
	echo 'daemon off;' >>/app/koreader-sync-server/config/nginx.conf
cd /app/koreader-sync-server
exec gin start
