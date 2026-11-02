#!/usr/bin/env bash
# Compila l'APK sense Gradle ni baixar res: aapt2 + javac + d8 + zipalign + apksigner del SDK local.
set -euo pipefail
JAVAC="${JAVAC:-$(command -v javac || echo /snap/android-studio/current/jbr/bin/javac)}"
cd "$(dirname "$0")"
SDK="${ANDROID_SDK:-$HOME/Android/Sdk}"
BT="$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)"
AJAR="$(ls -d "$SDK"/platforms/android-35 | head -1)/android.jar"
rm -rf build && mkdir -p build/classes build/dex
"$BT/aapt2" link -o build/base.apk --manifest AndroidManifest.xml -I "$AJAR" --min-sdk-version 28 --target-sdk-version 35
"${JAVAC:-javac}" --release 11 -cp "$AJAR" -d build/classes $(find src -name '*.java')
"$BT/d8" --release --min-api 28 --lib "$AJAR" --output build/dex $(find build/classes -name '*.class')
(cd build/dex && zip -q ../base.apk classes.dex)
"$BT/zipalign" -f 4 build/base.apk build/captura-align.apk
"$BT/apksigner" sign --ks "$HOME/.android/debug.keystore" --ks-pass pass:android --out build/captura.apk build/captura-align.apk
echo "APK: $(pwd)/build/captura.apk"
