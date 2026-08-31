/*
 * busy_buttons.js — estado "ocupado" en los botones que disparan trabajo largo.
 *
 * Certificar un PDF de 50 MB tarda segundos: sin senal visual el operador
 * vuelve a pulsar y se emiten codigos o certificaciones duplicadas. Este
 * modulo pone un spinner, cambia el texto y bloquea el boton.
 *
 * Dos detalles que importan:
 *
 * 1. El boton NO se deshabilita en el propio evento `submit`. Un boton
 *    deshabilitado no se envia, y aqui hay botones cuyo `name` decide la
 *    accion en servidor (`verify_by_file`, `resend_otp`, `change_email`):
 *    deshabilitarlos a destiempo cambiaria el significado de la peticion. El
 *    bloqueo real lo hace una bandera en el formulario; el `disabled` se
 *    aplica en el siguiente turno del bucle de eventos, cuando el navegador
 *    ya serializo el formulario.
 *
 * 2. El estado se limpia en `pageshow`. Al volver con el boton Atras el
 *    navegador restaura la pagina desde la cache y, sin esto, el operador se
 *    encontraria un boton bloqueado para siempre.
 *
 * 3. El modulo se instala **una sola vez**, y ademas cada evento `submit` se
 *    marca al tratarlo. Las dos cosas cubren el mismo fallo desde lados
 *    distintos, y no sobran: una pagina que cargara este fichero dos veces
 *    registraba dos escuchadores de captura, y entonces el segundo veia la
 *    marca que acababa de poner el primero, lo tomaba por un doble clic y
 *    cancelaba el envio. El formulario no se mandaba nunca, el boton se
 *    quedaba en «Procesando…» para siempre y en la pestana de red no aparecia
 *    ninguna peticion: nada que leer en ningun log, porque del lado del
 *    servidor no llegaba a pasar nada.
 */
(function () {
  'use strict';

  // Ya instalado por otra copia del fichero: no se registra nada mas.
  if (window.GEABusy) {
    return;
  }

  var BUSY_FLAG = 'geaBusy';
  var ORIGINAL_HTML = 'geaOriginalHtml';
  var HANDLED = '__geaSubmitHandled';

  var script = document.currentScript;

  function defaultText(element) {
    return (
      element.getAttribute('data-loading-text') ||
      (script && script.getAttribute('data-default-loading-text')) ||
      'Procesando…'
    );
  }

  function spinner() {
    var element = document.createElement('span');
    element.className = 'spinner-border spinner-border-sm me-2';
    element.setAttribute('role', 'status');
    element.setAttribute('aria-hidden', 'true');
    return element;
  }

  function setBusy(button, text) {
    if (!button || button.dataset[BUSY_FLAG] === 'true') {
      return false;
    }

    button.dataset[BUSY_FLAG] = 'true';

    if (button.tagName === 'INPUT') {
      button.dataset[ORIGINAL_HTML] = button.value;
      button.value = text || defaultText(button);
    } else {
      button.dataset[ORIGINAL_HTML] = button.innerHTML;
      button.innerHTML = '';
      button.appendChild(spinner());
      button.appendChild(
        document.createTextNode(text || defaultText(button))
      );
    }

    button.setAttribute('aria-busy', 'true');
    button.classList.add('is-busy');

    return true;
  }

  function clearBusy(button) {
    if (!button || button.dataset[BUSY_FLAG] !== 'true') {
      return;
    }

    if (button.tagName === 'INPUT') {
      button.value = button.dataset[ORIGINAL_HTML] || button.value;
    } else {
      button.innerHTML = button.dataset[ORIGINAL_HTML] || button.innerHTML;
    }

    delete button.dataset[BUSY_FLAG];
    delete button.dataset[ORIGINAL_HTML];

    button.removeAttribute('aria-busy');
    button.classList.remove('is-busy');
    button.disabled = false;
  }

  function submitButtons(form) {
    return Array.prototype.slice.call(
      form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]')
    );
  }

  function releaseForm(form) {
    if (!form) {
      return;
    }

    delete form.dataset.geaSubmitting;

    submitButtons(form).forEach(function (button) {
      clearBusy(button);
      button.disabled = false;
    });
  }

  // ------------------------------------------------------------------
  // Envio de formularios
  // ------------------------------------------------------------------
  document.addEventListener('submit', function (event) {
    var form = event.target;

    if (!form || form.tagName !== 'FORM') {
      return;
    }

    if (form.hasAttribute('data-no-busy')) {
      return;
    }

    // Este mismo evento ya lo trato otra copia del modulo. No es un segundo
    // envio: es el mismo, visto dos veces. Cancelarlo aqui seria matar el
    // envio bueno, que es exactamente lo que pasaba.
    if (event[HANDLED]) {
      return;
    }

    // Segundo envio: se corta aqui. Esta es la proteccion real contra el
    // doble click, no el atributo disabled.
    if (form.dataset.geaSubmitting === 'true') {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }

    event[HANDLED] = true;

    // Si el navegador va a rechazar el formulario por validacion nativa no
    // hay envio, y bloquearlo dejaria el boton colgado.
    if (!form.noValidate &&
        typeof form.checkValidity === 'function' &&
        !form.checkValidity()) {
      return;
    }

    var button = event.submitter || submitButtons(form)[0];

    if (button && button.hasAttribute('data-no-busy')) {
      return;
    }

    form.dataset.geaSubmitting = 'true';

    setBusy(button, button ? button.getAttribute('data-loading-text') : null);

    // El disabled va en el siguiente turno: para entonces el navegador ya
    // incluyo el name/value del boton en la peticion.
    window.setTimeout(function () {
      submitButtons(form).forEach(function (item) {
        item.disabled = true;
      });
    }, 0);
  }, true);

  // ------------------------------------------------------------------
  // Vuelta atras: la pagina puede venir de la cache del navegador
  // ------------------------------------------------------------------
  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) {
      return;
    }

    Array.prototype.forEach.call(
      document.querySelectorAll('form'),
      releaseForm
    );
  });

  // ------------------------------------------------------------------
  // API para los botones que no envian formulario (fetch)
  // ------------------------------------------------------------------
  window.GEABusy = {
    set: setBusy,
    clear: clearBusy,
    release: releaseForm,

    /**
     * Envuelve una promesa: el boton queda ocupado hasta que se resuelve.
     * Devuelve null si el boton ya estaba ocupado, para que quien llama
     * pueda descartar el segundo click.
     */
    wrap: function (button, text, factory) {
      if (!setBusy(button, text)) {
        return null;
      }

      button.disabled = true;

      var done = function () {
        clearBusy(button);
      };

      var result;

      try {
        result = factory();
      } catch (error) {
        done();
        throw error;
      }

      if (!result || typeof result.then !== 'function') {
        done();
        return result;
      }

      return result.then(
        function (value) { done(); return value; },
        function (error) { done(); throw error; }
      );
    }
  };
})();
