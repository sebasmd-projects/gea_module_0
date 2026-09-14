#!/bin/sh
# ---------------------------------------------------------------------
#  GEA - Comprobacion de integridad / Integrity check   (Linux y macOS)
#
#  Sin dependencias: usa `sha256sum` (Linux) o `shasum` (macOS), que vienen
#  con el sistema. No hay binario a proposito -- un ejecutable sin firmar
#  copiado de una USB es lo que un antivirus debe bloquear.
# ---------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1

if command -v sha256sum >/dev/null 2>&1; then
    SUMA="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    SUMA="shasum -a 256"
else
    echo "No se encontro sha256sum ni shasum en este sistema." >&2
    exit 2
fi

printf '\n  GEA - Comprobacion de integridad\n'
printf '  ================================\n\n'

ok=0; malos=0; ausentes=0

# El manifiesto lleva el formato de sha256sum: huella, dos espacios, ruta.
while IFS= read -r linea; do
    case "$linea" in
        [0-9a-f][0-9a-f]*"  "*) ;;
        *) continue ;;
    esac

    esperada=$(printf '%s' "$linea" | cut -c1-64)
    nombre=$(printf '%s' "$linea" | cut -c67-)

    if [ ! -f "$nombre" ]; then
        printf '  FALTA     %s\n' "$nombre"
        ausentes=$((ausentes + 1))
        continue
    fi

    actual=$($SUMA "$nombre" | cut -c1-64)

    if [ "$actual" = "$esperada" ]; then
        printf '  OK        %s\n' "$nombre"
        ok=$((ok + 1))
    else
        printf '  ALTERADO  %s\n' "$nombre"
        malos=$((malos + 1))
    fi
done < manifiesto.sha256

printf '\n'

if [ "$malos" -eq 0 ] && [ "$ausentes" -eq 0 ]; then
    printf '  Los %s archivos coinciden con el manifiesto.\n' "$ok"
else
    printf '  %s alterado(s), %s ausente(s). NO use este dossier.\n' \
        "$malos" "$ausentes"
fi

cat <<'TEXTO'

  Esto comprueba que los archivos no han cambiado desde que se grabaron.
  Para comprobar ADEMAS el sello Ed25519 y el anclaje en la cadena de
  bloques, suba el PDF en:

  https://geausa.propensionesabogados.com/verify/aegis/asset/certification/

  SUBIR EL DOCUMENTO comprueba su integridad.
  TECLEAR EL CODIGO PUBLICO no: solo muestra la ficha.

TEXTO

# El resultado tambien en el codigo de salida, no solo en la pantalla: quien
# llame a esto desde otro guion lee el codigo, y salir con 0 tras escribir «NO
# use este dossier» le dice lo contrario de lo que pone arriba.
if [ "$malos" -ne 0 ] || [ "$ausentes" -ne 0 ]; then
    exit 1
fi

exit 0
