#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=$HERE/lib
GEN=$HERE/.cache/generator
OUT=$HERE/build
GENERATOR_REPO=https://github.com/cinit/NeoAuthBotPlugin
GENERATOR_COMMIT=d1d51dafe9f1a2f8fe4c7a761cd977436a411d7e

fetch() {
  local url=$1 dest=$2 sha256=$3
  if [[ ! -f $dest ]]; then
    curl -sfL --retry 3 -o "$dest.part" "$url"
    mv "$dest.part" "$dest"
  fi
  echo "$sha256  $dest" | sha256sum -c --quiet -
}
mkdir -p "$LIB"
MAVEN=https://repo1.maven.org/maven2
SKIJA=https://packages.jetbrains.team/maven/p/skija/maven/org/jetbrains/skija
fetch $SKIJA/skija-shared/0.93.1/skija-shared-0.93.1.jar "$LIB/skija-shared-0.93.1.jar" 2c750f23efec52c8f8a865d2bd6f71a7181ae90f8ccfcfb224a14090d3d5f1ab
fetch $SKIJA/skija-linux/0.93.1/skija-linux-0.93.1.jar "$LIB/skija-linux-0.93.1.jar" 520da68cb5548e4ce12e741a9f731f0a77c75e0005d4d814aeed62245ffab435
fetch $MAVEN/org/jetbrains/annotations/23.0.0/annotations-23.0.0.jar "$LIB/annotations-23.0.0.jar" 7b0f19724082cbfcbc66e5abea2b9bc92cf08a1ea11e191933ed43801eb3cd05
fetch $MAVEN/com/github/luben/zstd-jni/1.5.7-4/zstd-jni-1.5.7-4.jar "$LIB/zstd-jni-1.5.7-4.jar" e7f064bf1eab83fa785cf587f657f09649e3b0af6f27caa5382416953b5a35f8

if [[ ! -d $GEN/.git ]]; then
  git init -q "$GEN"
  git -C "$GEN" remote add origin "$GENERATOR_REPO"
fi
if [[ $(git -C "$GEN" rev-parse -q --verify HEAD || true) != "$GENERATOR_COMMIT" ]]; then
  git -C "$GEN" fetch -q --depth 1 origin "$GENERATOR_COMMIT"
  git -C "$GEN" checkout -q --detach "$GENERATOR_COMMIT"
fi
[[ $(git -C "$GEN" rev-parse HEAD) == "$GENERATOR_COMMIT" ]]
[[ -z $(git -C "$GEN" status --porcelain --ignored) ]] || { echo "$GEN has local changes" >&2; exit 1; }

SRC=$GEN/src/main
rm -rf "$OUT/classes"
mkdir -p "$OUT/classes"
mapfile -t OURS < <(find "$HERE/src/main/java" -name '*.java')
javac --release 17 -encoding UTF-8 -nowarn -d "$OUT/classes" -cp "$(ls "$LIB"/*.jar | tr '\n' ':')" \
  "$SRC"/java/cc/ioctl/neoauth3bot/chiral/*.java "$SRC"/java/cc/ioctl/neoauth3bot/util/*.java "${OURS[@]}"
cp "$SRC/resources/Roboto-Regular.ttf" "$OUT/classes/"
echo "$GENERATOR_COMMIT" > "$OUT/classes/generator-commit.txt"
jar --create --file "$OUT/harness.jar" --main-class noauthbot.harness.Main -C "$OUT/classes" .
echo "built $OUT/harness.jar"
