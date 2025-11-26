#!/bin/sh

set -eu

die() {
	echo "# FATAL: $*" >&2
	exit 1
}

info() {
	echo "# $*" >&2
}

# Parse -C option first (before extracting REMOTE)
CHDIR=
while [ $# -gt 0 ]; do
	case "$1" in
	-C)
		CHDIR="$2"
		shift 2
		;;
	*)
		break
		;;
	esac
done

# Change directory if -C was provided
if [ -n "$CHDIR" ]; then
	cd "$CHDIR" || die "Failed to change directory to: $CHDIR"
fi

REMOTE="$1"
REMOTE_PORT=
shift

SSH_OPT=" \
-o HashKnownHosts=no \
-o StrictHostKeyChecking=no \
-o UserKnownHostsFile=/dev/null \
"

# if a number is provided assume it's a local port forwarding
# e.g. ssh -N 192.168.0.207 -L 20722:192.168.9.2:22  ----> $0 20722
if [ -n "$(echo "${REMOTE#*@}" | sed -n -e 's/^\([0-9]\+\)$/\1/p')" ]; then
	REMOTE_PORT="${REMOTE#*@}"
	case "$REMOTE" in
	*@*) REMOTE="${REMOTE%%@*}@localhost" ;;
	*)   REMOTE=localhost ;;
	esac
fi

# did REMOTE get a user? assume the user is root instead of `id -n` if not
case "$REMOTE" in
*@*)	;;
*)	REMOTE="root@$REMOTE" ;;
esac

# did REMOTE get a port? split
case "$REMOTE" in
*:*)	REMOTE_PORT=${REMOTE#*:}
	REMOTE="${REMOTE%%:*}"
	;;
esac

if [ -n "$REMOTE_PORT" ]; then
	SSH_OPT="-p $REMOTE_PORT $SSH_OPT"
fi

SSH="ssh $SSH_OPT"
SCP="scp -B $SSH_OPT -q"
RSYNC=`which rsync`

MYDIR="$(dirname "$(readlink -f "$0")")"
REMOTE_UPDATE_DIR="/usr/local/update-src"
REMOTE_OPKG_STATUS=

run_remote() {
	local opt=
	if [ "$1" = '-q' ]; then
		opt="$1"
		shift
	fi
	$SSH $opt $REMOTE "$@"
}

do_rsync() {
	RSYNC_RSH="$SSH -q" $RSYNC -rtOi "$@"
}

cleanup() {
	if [ -n "$REMOTE_OPKG_STATUS" ]; then
		rm -f "$REMOTE_OPKG_STATUS"
	fi
}

MKUPDATE_OPTS=
if [ "${1:-}" = install ]; then
	OPKG_UPGRADE_OPTS="install"
	shift

	while [ $# -gt 0 ]; do
		case "$1" in
		-*)
			OPKG_UPGRADE_OPTS="$OPKG_UPGRADE_OPTS $1"
			;;
		*)
			MKUPDATE_OPTS="${MKUPDATE_OPTS:+$MKUPDATE_OPTS }-x $1"
			OPKG_UPGRADE_OPTS="$OPKG_UPGRADE_OPTS $1"
		esac
		shift
	done

	set -- $OPKG_UPGRADE_OPTS
fi

while [ $# -gt 0 ]; do
	case "$1" in
	-x)
		GOALS="${GOALS:+$GOALS }$2"
		shift 2
		;;
	*)
		break
	esac
done

MKUPDATE="$MYDIR/mkupdate.py"

# DEPLOY_IPK_DIR is the ipk/ directory where the newest Packages.gz is found
DEPLOY_IPK_DIR=$(for dd in $PWD ${PWD%/*} ipk/deploy tmp*/deploy *tmp*/*/deploy *tmp*/*/*/deploy; do
	[ -d "$dd" ] || continue
	for pd in "$dd/ipk" "$dd"/*/ipk; do
		ls -1 "$pd"/*/Packages.gz || true
	done
done 2> /dev/null | xargs -r ls -1t | sed -e 's|/[^/]\+/Packages.gz||' -e '1!d')

cat <<EOT
#    TARGET: ssh://$REMOTE${REMOTE_PORT:+:$REMOTE_PORT}
#    IPKDIR: $DEPLOY_IPK_DIR
#
EOT

# verify package-index
for x in "$DEPLOY_IPK_DIR"/*/Packages.gz; do
	if [ "$(ls -1t "$x" "${x%/*}"/*.ipk | head -n1)" != "$x" ]; then
		die "$x: OUT OF DATE - please build package-index again"
	else
		info "$x: OK"
	fi
done

trap cleanup EXIT

# get the opkg status of the remote
#
HAS_RSYNC=$(run_remote which rsync || true)
REMOTE_OPKG_STATUS=$(mktemp --suffix=.opkg_status.txt)
REMOTE_OPKG_STATUS_LOCATION=$(run_remote ls -1 /usr/lib/opkg/status /var/lib/opkg/status 2> /dev/null | head -n1)

info "$REMOTE:$REMOTE_OPKG_STATUS_LOCATION -> $REMOTE_OPKG_STATUS"
if [ -n "$HAS_RSYNC" ]; then
	do_rsync "$REMOTE:$REMOTE_OPKG_STATUS_LOCATION" "$REMOTE_OPKG_STATUS"
else
	$SCP "$REMOTE:$REMOTE_OPKG_STATUS_LOCATION" "$REMOTE_OPKG_STATUS"
fi
touch "$REMOTE_OPKG_STATUS"

info "Generating update material"
"$MKUPDATE" $MKUPDATE_OPTS "$DEPLOY_IPK_DIR" "$REMOTE_OPKG_STATUS"
LOCAL_UPDATE_DIR=$(ls -1dt \
	"$DEPLOY_IPK_DIR"/../images/update-from-*/ \
	"$DEPLOY_IPK_DIR"/../update-from-*/ \
	2> /dev/null | head -n1)

if [ -d "$LOCAL_UPDATE_DIR" ]; then
	T0=$(stat -c%Y "$LOCAL_UPDATE_DIR")
	T1=$(stat -c%Y "$REMOTE_OPKG_STATUS")
	if [ -n "$REMOTE" -a $T0 -ge $T1 ]; then
		info "Transfering update material"
		run_remote -q mkdir -p "$REMOTE_UPDATE_DIR/"
		if [ -n "$HAS_RSYNC" ]; then
			do_rsync --delete-after "$LOCAL_UPDATE_DIR/ipk" "$REMOTE:$REMOTE_UPDATE_DIR/"
		else
			$SCP -r "$LOCAL_UPDATE_DIR/ipk" "$REMOTE:$REMOTE_UPDATE_DIR/"
		fi

		OPKG_UPGRADE_FROM=opkg-upgrade-from
		# no warranty that /usr/local/bin is in $PATH when connecting via ssh
		x="$(run_remote -q which $OPKG_UPGRADE_FROM || true)"
		if [ -z "$x" ]; then
			OPKG_UPGRADE_FROM="/usr/local/bin/$OPKG_UPGRADE_FROM"
			run_remote -q mkdir -p "${OPKG_UPGRADE_FROM%/*}"
			if [ -n "$HAS_RSYNC" ]; then
				do_rsync "$MYDIR/opkg-upgrade-from.sh" "$REMOTE:$OPKG_UPGRADE_FROM"
			else
				$SCP "$MYDIR/opkg-upgrade-from.sh" "$REMOTE:$OPKG_UPGRADE_FROM"
			fi
		fi

		run_remote -q "$OPKG_UPGRADE_FROM" "$REMOTE_UPDATE_DIR/ipk" "$@"
		info "Done."
		exit 0
	fi
fi
info "Nothing to do."
