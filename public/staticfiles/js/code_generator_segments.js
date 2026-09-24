/*
 * code_generator_segments.js — "Code segments" en /generate/code/ solo se
 * enseña cuando algo lo va a usar de verdad.
 *
 * Antes de esto la tarjeta se veia siempre, incluso generando un barcode o
 * un QR con su propio contenido (un texto libre, una URL): rellenarla no
 * tenia ningun efecto en ese caso, porque nada consume el codigo compuesto.
 * Se enseña cuando:
 *
 *   - el barcode esta en modo "The code composed below" (no un texto propio);
 *   - el QR pide "The generated code itself"; o
 *   - se va a certificar un documento, que siempre estampa el codigo
 *     institucional compuesto (NIT, secuencia, hash, fecha).
 *
 * La validacion de verdad sigue en el servidor
 * (`CodeGeneratorView._issue_code`): esto solo evita pedir de mas en la
 * pantalla, igual que `code_generator_certify.js` con la tarjeta de
 * certificacion.
 */
(function () {
  'use strict';

  var segmentsCard = document.getElementById('codeSegmentsCard');

  if (!segmentsCard) {
    return;
  }

  var certifyToggle = document.getElementById('id_certify_document');
  var barcodeCheckbox = document.getElementById('id_generate_barcode');
  var barcodeContentSelect = document.getElementById('id_barcode_content');
  var qrCheckbox = document.getElementById('id_generate_qr');
  var qrContentSelect = document.getElementById('id_qr_content');
  var qrLogoModeSelect = document.getElementById('id_qr_logo_mode');
  var qrLogoImageField = document.getElementById('qrLogoImageField');

  function needsComposedCode() {
    if (certifyToggle && certifyToggle.checked) {
      return true;
    }

    if (
      barcodeCheckbox && barcodeCheckbox.checked &&
      (!barcodeContentSelect || barcodeContentSelect.value !== 'CUSTOM')
    ) {
      return true;
    }

    if (
      qrCheckbox && qrCheckbox.checked &&
      qrContentSelect && qrContentSelect.value === 'CODE'
    ) {
      return true;
    }

    return false;
  }

  function syncSegments() {
    segmentsCard.classList.toggle('d-none', !needsComposedCode());
  }

  function syncLogoImageField() {
    if (!qrLogoImageField) {
      return;
    }

    var showUpload = qrLogoModeSelect && qrLogoModeSelect.value === 'CUSTOM';
    qrLogoImageField.classList.toggle('d-none', !showUpload);
  }

  [
    certifyToggle, barcodeCheckbox, barcodeContentSelect,
    qrCheckbox, qrContentSelect,
  ].forEach(function (field) {
    if (field) {
      field.addEventListener('change', syncSegments);
    }
  });

  if (qrLogoModeSelect) {
    qrLogoModeSelect.addEventListener('change', syncLogoImageField);
  }

  syncSegments();
  syncLogoImageField();
}());
