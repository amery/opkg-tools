#!/bin/sh

set -eu

update_src="$1"
shift

update_dir="$(cd "$update_src" && pwd -P)"
opkg_conf="/etc/opkg/update-from.conf"

do_opkg() {
	echo "+ opkg $*" >&2
	env - PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin" opkg "$@"
}

cleanup() {
	trap '' EXIT

	rm -f "$opkg_conf"
	do_opkg update
}

trap cleanup EXIT

# can it sort -V?
if echo 1 | sort -V > /dev/null 2>&1; then
	SORT="sort -V"
else
	SORT=sort
fi
# can we make pretty columns?
COLUMN=`which column 2> /dev/null || echo`
if [ -x "$COLUMN" ]; then
	COLUMN="$COLUMN -t -c3"
else
	COLUMN=cat
fi

find "$update_dir" -name Packages.gz | $SORT |
	sed -ne "s|^\(.*/\([^/]\+\)\)/[^/]*$|src/gz \2 file://\1|p" | $COLUMN > "$opkg_conf"

[ $# -ne 0 ] || set -- upgrade --autoremove
do_opkg update
do_opkg "$@"
cleanup
