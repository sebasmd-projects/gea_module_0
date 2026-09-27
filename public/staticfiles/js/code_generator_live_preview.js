/*
 * code_generator_live_preview.js — la tarjeta "Preview" de /generate/code/
 * dibuja lo que se esta configurando, no solo una muestra generica, y esta
 * siempre visible: no depende de "Certificar documento".
 *
 * (El banco de trabajo de "Placements over the document", mas abajo, es
 * otra cosa: solo tiene sentido con un PDF delante para colocar los codigos
 * encima, y por eso sigue escondido hasta certificar. Esta tarjeta no monta
 * ningun PDF ni posiciones, solo los dos simbolos.)
 *
 * Lo que se puede reflejar exacto, sin pedirle nada al servidor con efectos
 * secundarios:
 *   - el texto del barcode, cuando "Barcode content" es "A custom text";
 *   - el contenido del QR, cuando "QR content" es "A custom URL or text".
 *
 * Lo que compone "Code segments" (NIT, iniciales+secuencia, hash del
 * documento, fecha, codigo aleatorio) se aproxima con un relleno del mismo
 * ANCHO que tendra el segmento real -- la secuencia autonoma y el codigo
 * aleatorio no se pueden adelantar sin reservar un valor de verdad en el
 * servidor, y el hash depende de un archivo que puede ni haberse subido
 * todavia. La fecha si es exacta: no depende de nada del servidor.
 */
(function () {
  'use strict';

  var card = document.getElementById('symbolPreviewCard');

  if (!card) {
    return;
  }

  var symbolsUrl = card.getAttribute('data-symbols-url') || '';
  var companyNit = card.getAttribute('data-company-nit') || '';
  var sequencePad = parseInt(card.getAttribute('data-sequence-pad'), 10) || 8;

  var barcodeWrap = document.getElementById('barcodePreviewWrap');
  var qrWrap = document.getElementById('qrPreviewWrap');
  var barcodeImg = document.getElementById('barcodePreviewImg');
  var qrImg = document.getElementById('qrPreviewImg');

  if (!symbolsUrl || (!barcodeImg && !qrImg)) {
    return;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function fieldValue(id) {
    var field = byId(id);
    return field ? (field.value || '').trim() : '';
  }

  function fieldChecked(id) {
    var field = byId(id);
    return !!(field && field.checked);
  }

  function stripAccents(value) {
    return (value || '').normalize('NFKD').replace(/[̀-ͯ]/g, '');
  }

  // Espejo de `services.codes.derive_initials`: solo para aproximar el
  // segmento en la vista previa, nunca lo que de verdad se emite.
  function deriveInitials(reference, maxLength) {
    maxLength = maxLength || 6;

    var cleaned = stripAccents(reference).toUpperCase();
    var words = cleaned.split(/[^A-Z0-9]+/).filter(Boolean);

    if (!words.length) {
      return '';
    }

    if (words.length === 1) {
      return words[0].slice(0, maxLength);
    }

    return words.map(function (word) { return word[0]; }).join('').slice(0, maxLength);
  }

  function filler(length, char) {
    length = Math.max(0, length || 0);
    return new Array(length + 1).join(char || 'X');
  }

  function todayDDMMYYYY() {
    var now = new Date();
    var day = String(now.getDate()).padStart(2, '0');
    var month = String(now.getMonth() + 1).padStart(2, '0');
    return day + month + now.getFullYear();
  }

  // Espejo de `services.codes.build_code_payload`: mismo orden de
  // segmentos, con relleno donde el valor real solo lo sabe el servidor.
  function composedPreviewPayload() {
    var segments = [];

    if (fieldChecked('id_include_nit') && companyNit) {
      segments.push(companyNit);
    }

    var customText = fieldValue('id_custom_text_input');
    if (customText) {
      segments.push(customText);
    }

    if (fieldChecked('id_include_initials_sequence')) {
      var initials = fieldValue('id_initials') ||
        deriveInitials(fieldValue('id_reference'));
      var sequence = filler(sequencePad, '0');
      var identity = [initials, sequence].filter(Boolean).join('_');

      if (identity) {
        segments.push(identity);
      }
    }

    if (fieldChecked('id_include_document_hash')) {
      var hashLength = parseInt(fieldValue('id_hash_fragment_length'), 10) || 16;
      segments.push(filler(hashLength));
    }

    if (fieldChecked('id_include_date')) {
      segments.push(todayDDMMYYYY());
    }

    if (fieldChecked('id_include_random_code')) {
      var randomLength = parseInt(fieldValue('id_random_code_length'), 10) || 12;
      segments.push(filler(randomLength));
    }

    return segments.join(' ').trim();
  }

  function computePayloads() {
    var composed = composedPreviewPayload();

    var barcodeEnabled = fieldChecked('id_generate_barcode');
    var barcodeContent = fieldValue('id_barcode_content') || 'COMPOSED';
    var barcodePayload = '';

    if (barcodeEnabled) {
      barcodePayload = barcodeContent === 'CUSTOM'
        ? fieldValue('id_barcode_custom_value')
        : composed;
    }

    var qrEnabled = fieldChecked('id_generate_qr');
    var qrContent = fieldValue('id_qr_content') || 'VERIFICATION';
    var qrPayload = '';

    if (qrEnabled) {
      if (qrContent === 'CUSTOM') {
        qrPayload = fieldValue('id_qr_custom_value');
      } else if (qrContent === 'CODE') {
        qrPayload = composed;
      }
      // "VERIFICATION" no tiene nada que adelantar: no existe hasta
      // certificar, asi que se queda en la muestra por defecto.
    }

    return {
      barcodeEnabled: barcodeEnabled,
      barcodePayload: barcodePayload,
      qrEnabled: qrEnabled,
      qrPayload: qrPayload,
    };
  }

  function applyVisibility(payloads) {
    if (barcodeWrap) {
      barcodeWrap.classList.toggle('d-none', !payloads.barcodeEnabled);
    }
    if (qrWrap) {
      qrWrap.classList.toggle('d-none', !payloads.qrEnabled);
    }
  }

  var pending = null;

  function scheduleUpdate() {
    var payloads = computePayloads();

    // Mostrar u ocultar cada simbolo no depende de la red: se aplica ya.
    applyVisibility(payloads);

    if (pending) {
      window.clearTimeout(pending);
    }

    pending = window.setTimeout(function () {
      pending = null;

      var query = [];

      if (payloads.barcodePayload) {
        query.push('payload=' + encodeURIComponent(payloads.barcodePayload));
      }
      if (payloads.qrPayload) {
        query.push('qr_payload=' + encodeURIComponent(payloads.qrPayload));
      }

      fetch(symbolsUrl + (query.length ? '?' + query.join('&') : ''), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('HTTP ' + response.status);
          }
          return response.json();
        })
        .then(function (data) {
          var symbols = data && data.symbols;

          if (!symbols) {
            return;
          }

          if (barcodeImg && symbols.BARCODE) {
            barcodeImg.src = symbols.BARCODE.src;
          }
          if (qrImg && symbols.QR) {
            qrImg.src = symbols.QR.src;
          }
        })
        .catch(function (error) {
          if (window.console) {
            console.warn('Live preview symbols could not be reloaded', error);
          }
        });
    }, 350);
  }

  var watchedIds = [
    'id_reference', 'id_custom_text_input',
    'id_include_nit', 'id_include_initials_sequence', 'id_initials',
    'id_include_document_hash', 'id_hash_fragment_length',
    'id_include_date', 'id_include_random_code', 'id_random_code_length',
    'id_generate_barcode', 'id_barcode_content', 'id_barcode_custom_value',
    'id_generate_qr', 'id_qr_content', 'id_qr_custom_value',
  ];

  watchedIds.forEach(function (id) {
    var field = byId(id);

    if (field) {
      field.addEventListener('input', scheduleUpdate);
      field.addEventListener('change', scheduleUpdate);
    }
  });

  scheduleUpdate();
}());
