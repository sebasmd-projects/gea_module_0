/*
 * code_generator_live_preview.js — la vista previa de /generate/code/ dibuja
 * lo que se esta configurando, no solo una muestra generica.
 *
 * Antes del generador (`preview_symbols`) solo se volvia a pedir cuando se
 * cambiaba "Sample characters": la vista previa embebida al cargar la pagina
 * era siempre la misma muestra de relleno, sin relacion con lo que el
 * operador fuera escribiendo.
 *
 * Lo que SI se puede mostrar en vivo, sin pedirle nada al servidor que tenga
 * efectos secundarios, es el contenido que el propio operador teclea:
 *   - el texto del barcode, cuando "Barcode content" es "A custom text";
 *   - el contenido del QR, cuando "QR content" es "A custom URL or text";
 *   - y el QR con "The generated code itself", que seguira al barcode de
 *     arriba cuando ese sea un texto propio.
 *
 * Lo que compone "Code segments" (secuencia autonoma, hash del documento,
 * codigo aleatorio) no se previsualiza exacto aqui a proposito: la secuencia
 * la reserva el servidor al emitir, y adelantarla solo para pintar una
 * muestra consumiria un valor real sin haber generado nada. Para ese caso la
 * vista previa se queda en la muestra de relleno de siempre, que ya avisa del
 * ancho aproximado.
 */
(function () {
  'use strict';

  var barcodeCheckbox = document.getElementById('id_generate_barcode');
  var barcodeContentSelect = document.getElementById('id_barcode_content');
  var barcodeCustomInput = document.getElementById('id_barcode_custom_value');

  var qrCheckbox = document.getElementById('id_generate_qr');
  var qrContentSelect = document.getElementById('id_qr_content');
  var qrCustomInput = document.getElementById('id_qr_custom_value');

  var watched = [
    barcodeCheckbox, barcodeContentSelect, barcodeCustomInput,
    qrCheckbox, qrContentSelect, qrCustomInput,
  ].filter(Boolean);

  if (!watched.length) {
    return;
  }

  function fieldValue(field) {
    if (!field) {
      return '';
    }
    return (field.value || '').trim();
  }

  function computePayloads() {
    var payload = '';

    if (
      barcodeCheckbox && barcodeCheckbox.checked &&
      fieldValue(barcodeContentSelect) === 'CUSTOM'
    ) {
      payload = fieldValue(barcodeCustomInput);
    }

    var qrPayload = '';

    if (qrCheckbox && qrCheckbox.checked) {
      var qrContent = fieldValue(qrContentSelect);

      if (qrContent === 'CUSTOM') {
        qrPayload = fieldValue(qrCustomInput);
      } else if (qrContent === 'CODE') {
        qrPayload = payload;
      }
    }

    return { payload: payload, qrPayload: qrPayload };
  }

  function previewInstance() {
    var root = document.querySelector('[data-gea-preview]');
    return root && window.GEAStampPreview && window.GEAStampPreview.instance(root);
  }

  var pending = null;

  function scheduleUpdate() {
    if (pending) {
      window.clearTimeout(pending);
    }

    pending = window.setTimeout(function () {
      pending = null;

      var instance = previewInstance();
      if (!instance) {
        return;
      }

      var payloads = computePayloads();

      instance.reloadSymbols({
        length: instance.sampleLength,
        payload: payloads.payload,
        qrPayload: payloads.qrPayload,
      });
    }, 350);
  }

  watched.forEach(function (field) {
    field.addEventListener('input', scheduleUpdate);
    field.addEventListener('change', scheduleUpdate);
  });

  // Si el formulario vuelve con un error y estos campos ya traian algo
  // escrito (persistencia normal de un `forms.Form`), la vista previa
  // arranca ya reflejandolo en vez de esperar al primer cambio.
  var initialPayloads = computePayloads();
  if (initialPayloads.payload || initialPayloads.qrPayload) {
    scheduleUpdate();
  }
}());
