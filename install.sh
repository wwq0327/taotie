#!/bin/bash
set -e

INSTALL_DIR="${HOME}/.local/share/taotie"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$BIN_DIR"
rm -rf "$INSTALL_DIR"
git clone -q https://github.com/wwq0327/taotie.git "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/taotie.py"
ln -sf "$INSTALL_DIR/taotie.py" "$BIN_DIR/taotie"

echo "taotie 安装完成: ${BIN_DIR}/taotie"
