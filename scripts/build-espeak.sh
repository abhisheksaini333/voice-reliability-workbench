#!/bin/sh
# Reproduce the original eSpeak NG 1.51 release without modifying upstream code.
set -eu
prefix=${1:-/opt/espeak}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cd "$work"
curl --fail --silent --show-error --location --connect-timeout 20 --max-time 180 --retry 3 --output release.tar.gz \
  https://github.com/espeak-ng/espeak-ng/releases/download/1.51/espeak-ng-1.51.tar.gz
curl --fail --silent --show-error --location --connect-timeout 20 --max-time 180 --retry 3 --output tag.tar.gz \
  https://github.com/espeak-ng/espeak-ng/archive/refs/tags/1.51.tar.gz
printf '%s\n' \
  '027fa5dfa8616d5cc13f883209ff5f735eee6559f7689a019d5b2d01d290cd39  release.tar.gz' \
  'f0e028f695a8241c4fa90df7a8c8c5d68dcadbdbc91e758a97e594bbb0a3bdbf  tag.tar.gz' \
  | sha256sum --check --strict
mkdir release tag
tar -xzf release.tar.gz -C release --strip-components=1
tar -xzf tag.tar.gz -C tag --strip-components=1
# The release archive omits inputs required by its generated Makefile.
# Supplement only absent paths from the exact same tag; preserve release files.
cp -an tag/. release/
cd release
./configure --prefix="$prefix" --disable-shared --enable-static \
  --without-async --without-pcaudiolib --without-klatt --without-mbrola --without-sonic
make -j2
make install
mkdir -p "$prefix/share/source" "$prefix/share/licenses"
cp "$work/release.tar.gz" "$prefix/share/source/espeak-ng-1.51.tar.gz"
cp "$work/tag.tar.gz" "$prefix/share/source/espeak-ng-1.51-tag.tar.gz"
cp COPYING COPYING.APACHE COPYING.BSD2 COPYING.UCD "$prefix/share/licenses/"
"$prefix/bin/espeak-ng" --version
