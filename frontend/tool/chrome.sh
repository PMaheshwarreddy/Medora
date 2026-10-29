#!/usr/bin/env bash
# Launches Chrome with a clean desktop environment.
#
# A terminal inside the VS Code snap inherits the snap's own GTK and GSettings
# paths. Chrome then reads the snap's older settings schemas, hits a missing
# key and aborts ("Failed to launch browser" from `flutter run`). The snap
# keeps the original values in *_VSCODE_SNAP_ORIG; put them back for Chrome.
for name in XDG_DATA_DIRS XDG_CONFIG_DIRS GSETTINGS_SCHEMA_DIR GTK_PATH GTK_EXE_PREFIX \
            GIO_MODULE_DIR GTK_IM_MODULE_FILE GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR LOCPATH; do
  original="${name}_VSCODE_SNAP_ORIG"
  if [ -n "${!original+set}" ] && [ -n "${!original}" ]; then
    export "$name=${!original}"
  elif [ -n "${!original+set}" ] || [ "${!name#*/snap/}" != "${!name}" ]; then
    unset "$name"
  fi
done
# Web Bluetooth (the smart band) is hidden from pages in Chrome on Linux
# unless experimental web platform features are on; the same switch lets a
# page reconnect to a band chosen earlier without asking again.
exec google-chrome --enable-experimental-web-platform-features "$@"
