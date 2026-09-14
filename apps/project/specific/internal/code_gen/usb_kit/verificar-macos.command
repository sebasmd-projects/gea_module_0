#!/bin/bash
# ---------------------------------------------------------------------
#  GEA - Comprobacion de integridad / Integrity check        (macOS)
#
#  Sin nada que instalar: `shasum` viene con macOS. Doble clic para abrirlo.
#  Si macOS se niega la primera vez: clic derecho > Abrir.
# ---------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1
exec /bin/bash ./verificar-linux.sh
