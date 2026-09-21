/*
 * code_generator_certify.js — que se ve en /generate/code/ segun se elija
 * "Certificar documento" en Identificacion.
 *
 * El hash del documento (segmentos del codigo), la URL publica de
 * verificacion (simbolos) y la tarjeta entera de certificacion -- con las
 * posiciones sobre el documento, al final de la pagina -- no significan nada
 * sin un archivo que certificar. Antes se veian siempre, aunque nadie hubiera
 * marcado la casilla; ahora la casilla es la que decide, y este script solo
 * mueve clases y atributos, nunca logica de negocio: la validacion de verdad
 * sigue en `CodeGeneratorForm.clean()`, que exige exactamente lo mismo en el
 * servidor.
 */
(function () {
  'use strict';

  var toggle = document.getElementById('id_certify_document');

  if (!toggle) {
    return;
  }

  var certificationCard = document.getElementById('certificationCard');
  var documentHashField = document.getElementById('documentHashField');
  var stampWorkspace = document.getElementById('layoutWorkspace');
  var includeHash = document.getElementById('id_include_document_hash');
  var qrContent = document.getElementById('id_qr_content');
  var verificationOption = qrContent
    ? qrContent.querySelector('option[value="VERIFICATION"]')
    : null;

  function setHidden(el, hidden) {
    if (el) {
      el.classList.toggle('d-none', hidden);
    }
  }

  function repaintStampWorkspace() {
    // El lienzo de la vista previa mide el ancho disponible al construirse
    // (`clientWidth`), y `display:none` da 0: iniciado mientras la seccion
    // estaba oculta, se queda mas estrecho de lo que le toca. Un segundo
    // repintado, ya visible, es lo que corrige eso. `requestAnimationFrame`
    // espera a que el navegador aplique el cambio de clase antes de medir.
    if (!stampWorkspace || !window.GEAStampPreview) {
      return;
    }

    var root = stampWorkspace.querySelector('[data-gea-preview]');
    var instance = root && window.GEAStampPreview.instance(root);

    if (!instance) {
      return;
    }

    window.requestAnimationFrame(function () {
      instance.render();
    });
  }

  function sync() {
    var certifying = toggle.checked;

    setHidden(certificationCard, !certifying);
    setHidden(documentHashField, !certifying);
    setHidden(stampWorkspace, !certifying);

    if (certifying) {
      repaintStampWorkspace();
    } else {
      if (includeHash) {
        includeHash.checked = false;
      }

      if (qrContent && qrContent.value === 'VERIFICATION') {
        qrContent.value = 'CODE';
      }
    }

    if (verificationOption) {
      // La opcion no vale sin certificar (`CodeGeneratorForm.clean()` la
      // rechaza igual), asi que ni se ofrece: `hidden` la quita de la lista
      // desplegable, `disabled` impide dejarla seleccionada por teclado.
      verificationOption.hidden = !certifying;
      verificationOption.disabled = !certifying;
    }
  }

  toggle.addEventListener('change', sync);
  sync();
}());
