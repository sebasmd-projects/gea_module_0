/*
 * toasts.js — avisos flotantes, visibles esté donde esté el usuario.
 *
 * El problema que resuelve: los mensajes se pintaban dentro de la página, en
 * una tarjeta arriba del contenido. Quien acaba de pulsar un botón que está
 * al pie de un formulario largo se queda mirando el pie, y el aviso aparece
 * a mil píxeles por encima. El usuario no ve nada y vuelve a pulsar.
 *
 * Un toast va en `position: fixed`, así que no depende del scroll. Esa es
 * toda la idea.
 *
 * Tres decisiones que no son obvias:
 *
 * - **Los errores no se van solos.** Un acierto se puede desvanecer: si te lo
 *   pierdes, no pasa nada, la acción salió bien. Un fallo hay que poder
 *   leerlo dos veces, y a veces copiarlo. Se cierra a mano.
 * - **Se anuncia a los lectores de pantalla**, con `aria-live`. Un aviso que
 *   solo existe visualmente no es un aviso para todo el mundo. Los errores
 *   interrumpen (`assertive`); el resto espera turno (`polite`).
 * - **Un mismo mensaje repetido no se apila.** Pulsar tres veces el mismo
 *   botón deja un toast, no tres.
 *
 * Uso:
 *     geaToast('Se guardó.', 'success');
 *     geaToast('No se pudo guardar.', 'danger');
 *     geaToast('Trabajando…', 'info', { autohide: false, id: 'tarea-7' });
 *
 * Los `id` sirven para reemplazar un aviso en su sitio, que es lo que hace
 * falta cuando una tarea larga pasa de «en curso» a «terminada».
 */

(function () {
  'use strict';

  var CONTAINER_ID = 'geaToastContainer';

  // Los aciertos se leen de un vistazo; un aviso pide algo más de tiempo.
  var DELAYS = { success: 5000, info: 6000, warning: 9000 };

  // Bootstrap llama a sus niveles de otra forma que Django.
  var LEVELS = {
    debug: 'secondary',
    info: 'info',
    success: 'success',
    warning: 'warning',
    error: 'danger',
    danger: 'danger'
  };

  function container() {
    var element = document.getElementById(CONTAINER_ID);

    if (element) {
      return element;
    }

    element = document.createElement('div');
    element.id = CONTAINER_ID;
    element.className = 'toast-container position-fixed bottom-0 end-0 p-3';

    // Las clases de Bootstrap ya colocan el contenedor, pero Bootstrap llega
    // por CDN. Que el aviso se vea es justo lo que no puede depender de que
    // un tercero responda: sin esa hoja de estilos, los toasts caerían al
    // final del documento y volveríamos al problema que esto arregla. Se
    // repite en línea lo imprescindible, que es la posición.
    element.style.position = 'fixed';
    element.style.right = '1rem';
    element.style.bottom = '1rem';
    element.style.maxWidth = 'min(28rem, calc(100vw - 2rem))';

    // Por encima de los modales de Bootstrap (1055): un fallo al guardar
    // dentro de un modal tiene que verse, y si no, se pierde justo cuando
    // más falta hace.
    element.style.zIndex = '1090';

    document.body.appendChild(element);

    return element;
  }

  function dismiss(toast) {
    if (!toast || !toast.parentElement) {
      return;
    }

    toast.classList.remove('show');

    // Dar tiempo a la transición de Bootstrap antes de quitarlo del DOM.
    window.setTimeout(function () {
      if (toast.parentElement) {
        toast.parentElement.removeChild(toast);
      }
    }, 300);
  }

  function build(message, level, options) {
    var toast = document.createElement('div');

    toast.className = 'toast align-items-center text-bg-' + level +
      ' border-0 show';
    toast.setAttribute('role', level === 'danger' ? 'alert' : 'status');
    toast.setAttribute(
      'aria-live', level === 'danger' ? 'assertive' : 'polite'
    );
    toast.setAttribute('aria-atomic', 'true');

    if (options.id) {
      toast.dataset.geaToastId = options.id;
    }

    var body = document.createElement('div');
    body.className = 'toast-body';
    // textContent y no innerHTML: el texto puede venir de un error del
    // servidor, y un aviso no es sitio para interpretar marcado.
    body.textContent = message;

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close btn-close-white me-2 m-auto';
    close.setAttribute('aria-label', options.closeLabel || 'Cerrar');
    close.addEventListener('click', function () {
      dismiss(toast);
    });

    var row = document.createElement('div');
    row.className = 'd-flex';
    row.appendChild(body);
    row.appendChild(close);

    toast.appendChild(row);

    return toast;
  }

  /**
   * Mostrar un aviso.
   *
   * @param {string} message  Lo que se dice. Texto plano.
   * @param {string} level    Nivel de Django o de Bootstrap. Por defecto info.
   * @param {object} options  autohide (bool), delay (ms), id (string).
   * @returns {HTMLElement|null}
   */
  function geaToast(message, level, options) {
    if (!message) {
      return null;
    }

    options = options || {};

    var resolved = LEVELS[level] || level || 'info';
    var host = container();

    // Reemplazar en su sitio el aviso que lleve este id: así una tarea que
    // pasa de «en curso» a «terminada» no deja dos toasts contándose cosas
    // distintas.
    if (options.id) {
      var previous = host.querySelector('[data-gea-toast-id="' + options.id + '"]');

      if (previous) {
        previous.parentElement.removeChild(previous);
      }
    }

    // Y no apilar el mismo mensaje repetido: pulsar tres veces deja uno.
    var existing = host.querySelectorAll('.toast-body');

    for (var i = 0; i < existing.length; i += 1) {
      if (existing[i].textContent === message) {
        return existing[i].closest('.toast');
      }
    }

    var toast = build(message, resolved, options);

    host.appendChild(toast);

    // Un error se queda hasta que lo cierren. Lo demás se va solo.
    var autohide = options.autohide;

    if (autohide === undefined) {
      autohide = resolved !== 'danger';
    }

    if (autohide) {
      window.setTimeout(function () {
        dismiss(toast);
      }, options.delay || DELAYS[resolved] || 6000);
    }

    return toast;
  }

  /**
   * Vaciar los avisos que haya en pantalla.
   *
   * Lo usa quien va a mostrar el resultado de una acción nueva y no quiere
   * que se lea junto al de la anterior.
   */
  function geaToastClear() {
    var host = document.getElementById(CONTAINER_ID);

    if (!host) {
      return;
    }

    var toasts = host.querySelectorAll('.toast');

    for (var i = 0; i < toasts.length; i += 1) {
      dismiss(toasts[i]);
    }
  }

  window.geaToast = geaToast;
  window.geaToastClear = geaToastClear;

  // Los mensajes que trae la página desde el servidor. El servidor los deja
  // en un <script type="application/json">, no en HTML ya pintado: así el
  // texto no puede escaparse a marcado y el aviso sale igual esté donde esté
  // el scroll.
  window.addEventListener('DOMContentLoaded', function () {
    var source = document.getElementById('djangoMessages');

    if (!source) {
      return;
    }

    var messages;

    try {
      messages = JSON.parse(source.textContent || '[]');
    } catch (error) {
      return;
    }

    for (var i = 0; i < messages.length; i += 1) {
      geaToast(messages[i].message, messages[i].level);
    }
  });
})();
