/*
 * stamp_preview.js — vista previa en tiempo real de las posiciones de estampado.
 *
 * Dibuja la pagina a escala y coloca sobre ella una caja por cada posicion,
 * usando exactamente la misma geometria que
 * `services/pdf_stamp.py::_resolve_position`: coordenadas en puntos
 * PostScript, medidas desde el anclaje hacia el interior de la pagina, con el
 * origen en la esquina inferior izquierda.
 *
 * Modos:
 *
 *   - Enlazado a un formulario (admin, editor de disposiciones, generador):
 *     lee los inputs de cada fila, se actualiza a cada pulsacion y permite
 *     arrastrar las cajas, escribiendo de vuelta los desplazamientos.
 *
 *   - Solo lectura: recibe las posiciones en `data-placements` como JSON.
 *
 * Si se declara `data-pdf-input`, el componente pinta de fondo la pagina real
 * del PDF elegido en ese input, renderizada en el navegador con pdf.js. El
 * archivo no se sube para eso: se lee del propio input.
 */
(function () {
  'use strict';

  var FIELDS = [
    'kind', 'member_code', 'anchor', 'offset_x', 'offset_y',
    'width', 'height', 'page_selector', 'page_numbers',
    'is_active', 'DELETE'
  ];

  var PAGE_PRESETS = {
    letter: [612, 792],
    aegis: [612, 793.5],
    a4: [595.28, 841.89],
    legal: [612, 1008]
  };

  var PDFJS_URL =
    'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js';
  var PDFJS_WORKER_URL =
    'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';

  var pdfjsPromise = null;

  // ----------------------------------------------------------------
  // Geometria (espejo de _resolve_position en Python)
  // ----------------------------------------------------------------
  function resolvePosition(anchor, pageW, pageH, p) {
    var x;
    var y;

    if (anchor === 'BR' || anchor === 'TR') {
      x = pageW - p.offset_x - p.width;
    } else if (anchor === 'BC' || anchor === 'TC') {
      x = (pageW - p.width) / 2 + p.offset_x;
    } else {
      x = p.offset_x;
    }

    if (anchor === 'TL' || anchor === 'TC' || anchor === 'TR') {
      y = pageH - p.offset_y - p.height;
    } else {
      y = p.offset_y;
    }

    return { x: x, y: y };
  }

  // Inversa: dada una esquina inferior izquierda, los offsets del anclaje.
  function offsetsFromPosition(anchor, pageW, pageH, x, y, w, h) {
    var offsetX;
    var offsetY;

    if (anchor === 'BR' || anchor === 'TR') {
      offsetX = pageW - w - x;
    } else if (anchor === 'BC' || anchor === 'TC') {
      offsetX = x - (pageW - w) / 2;
    } else {
      offsetX = x;
    }

    if (anchor === 'TL' || anchor === 'TC' || anchor === 'TR') {
      offsetY = pageH - h - y;
    } else {
      offsetY = y;
    }

    return { offset_x: offsetX, offset_y: offsetY };
  }

  // Espejo de StampPlacementModel.resolved_pages.
  function appliesToPage(placement, pageNumber, pageCount) {
    var selector = placement.page_selector;

    if (!selector || !pageCount) {
      return true;
    }

    if (selector === 'FIRST') {
      return pageNumber === 1;
    }
    if (selector === 'LAST') {
      return pageNumber === pageCount;
    }
    if (selector === 'ALL') {
      return true;
    }
    if (selector === 'NUMBERS') {
      return String(placement.page_numbers || '')
        .split(',')
        .map(function (token) { return parseInt(token.trim(), 10); })
        .indexOf(pageNumber) !== -1;
    }

    return true;
  }


  // Cada tipo de simbolo se pinta de un color, para distinguir de un vistazo
  // los codigos propios del documento de los que vienen de sus miembros.
  function kindClass(kind) {
    if (kind === 'BARCODE') { return 'barcode'; }
    if (kind === 'MEMBER') { return 'member'; }
    if (kind === 'ANCHOR') { return 'anchor'; }
    return 'qr';
  }

  function captionFor(placement) {
    var pages = placement.page_selector_label || placement.page_selector || '';

    if (placement.kind === 'MEMBER') {
      // Lo util aqui es de que documento es el codigo, no en que pagina cae.
      return '▮▯▮ ' + (placement.member_code || '?');
    }

    if (placement.kind === 'ANCHOR') {
      return '⛓ ' + pages;
    }

    return (placement.kind === 'BARCODE' ? '▮▯▮ ' : '▣ ') + pages;
  }

  function round2(value) {
    return Math.round(value * 100) / 100;
  }

  function toNumber(value, fallback) {
    var parsed = parseFloat(value);
    return isNaN(parsed) ? fallback : parsed;
  }

  // ----------------------------------------------------------------
  // Lectura de los inputs de una fila
  // ----------------------------------------------------------------
  function findInput(row, suffix) {
    return row.querySelector(
      '[name$="-' + suffix + '"], [name="' + suffix + '"]'
    );
  }

  function readRow(row) {
    var data = { _row: row, _inputs: {} };

    FIELDS.forEach(function (field) {
      var input = findInput(row, field);
      data._inputs[field] = input;

      if (!input) {
        return;
      }

      if (input.type === 'checkbox') {
        data[field] = input.checked;
      } else {
        data[field] = input.value;
      }
    });

    var selector = data._inputs.page_selector;
    if (selector && selector.tagName === 'SELECT' && selector.selectedIndex >= 0) {
      data.page_selector_label = selector.options[selector.selectedIndex].text;
    }

    var kind = data._inputs.kind;
    if (kind && kind.tagName === 'SELECT' && kind.selectedIndex >= 0) {
      data.kind_label = kind.options[kind.selectedIndex].text;
    }

    data.offset_x = toNumber(data.offset_x, 0);
    data.offset_y = toNumber(data.offset_y, 0);
    data.width = toNumber(data.width, 10);
    data.height = toNumber(data.height, 10);
    data.anchor = data.anchor || 'BL';
    data.kind = data.kind || 'QR';

    return data;
  }

  function rowIsVisible(data) {
    if (data.DELETE === true) {
      return false;
    }
    if (data._inputs.is_active && data.is_active === false) {
      return false;
    }
    if (!data._inputs.kind && !data._inputs.offset_x) {
      return false;
    }
    return true;
  }

  // ----------------------------------------------------------------
  // pdf.js bajo demanda
  // ----------------------------------------------------------------
  function loadPdfJs() {
    if (pdfjsPromise) {
      return pdfjsPromise;
    }

    pdfjsPromise = new Promise(function (resolve, reject) {
      if (window.pdfjsLib) {
        resolve(window.pdfjsLib);
        return;
      }

      var script = document.createElement('script');
      script.src = PDFJS_URL;
      script.onload = function () {
        if (!window.pdfjsLib) {
          reject(new Error('pdfjsLib missing'));
          return;
        }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
        resolve(window.pdfjsLib);
      };
      script.onerror = function () {
        reject(new Error('pdf.js could not be loaded'));
      };
      document.head.appendChild(script);
    });

    return pdfjsPromise;
  }

  // ----------------------------------------------------------------
  // Componente
  // ----------------------------------------------------------------
  function StampPreview(root) {
    this.root = root;
    this.pageW = toNumber(root.getAttribute('data-page-width'), 612);
    this.pageH = toNumber(root.getAttribute('data-page-height'), 792);
    this.rowSelector = root.getAttribute('data-row-selector') || '';
    this.formScope = root.getAttribute('data-form-scope') || '';
    this.editable = root.getAttribute('data-editable') === 'true';
    this.pdfInputSelector = root.getAttribute('data-pdf-input') || '';
    this.staticPlacements = null;

    this.pdfDocument = null;
    this.pdfRenderTask = null;
    this.pageCount = 0;
    this.currentPage = 1;
    this.renderToken = 0;

    var raw = root.getAttribute('data-placements');
    if (raw) {
      try {
        this.staticPlacements = JSON.parse(raw);
      } catch (error) {
        this.staticPlacements = [];
      }
    }

    this.build();
    this.bind();
    this.render();
  }

  StampPreview.prototype.label = function (name, fallback) {
    return this.root.getAttribute('data-label-' + name) || fallback || '';
  };

  StampPreview.prototype.build = function () {
    var self = this;

    this.root.classList.add('gea-stamp-preview');

    this.toolbar = document.createElement('div');
    this.toolbar.className = 'gea-stamp-preview__toolbar';

    var label = document.createElement('span');
    label.className = 'gea-stamp-preview__label';
    label.textContent = this.label('page', 'Page');
    this.toolbar.appendChild(label);

    this.presetSelect = document.createElement('select');
    this.presetSelect.className = 'gea-stamp-preview__select';

    [
      ['aegis', 'AEGIS (612 x 793.5)'],
      ['letter', 'Letter (612 x 792)'],
      ['a4', 'A4 (595 x 842)'],
      ['legal', 'Legal (612 x 1008)']
    ].forEach(function (option) {
      var element = document.createElement('option');
      element.value = option[0];
      element.textContent = option[1];
      self.presetSelect.appendChild(element);
    });

    this.presetSelect.addEventListener('change', function () {
      var size = PAGE_PRESETS[self.presetSelect.value];
      if (size) {
        self.pageW = size[0];
        self.pageH = size[1];
        self.render();
      }
    });

    this.toolbar.appendChild(this.presetSelect);

    // Navegacion de paginas, visible solo cuando hay un PDF cargado.
    this.pageNav = document.createElement('span');
    this.pageNav.className = 'gea-stamp-preview__pagenav';
    this.pageNav.style.display = 'none';
    this.toolbar.appendChild(this.pageNav);

    this.hint = document.createElement('span');
    this.hint.className = 'gea-stamp-preview__hint';
    this.hint.textContent = this.editable ? this.label('hint') : '';
    this.toolbar.appendChild(this.hint);

    this.stage = document.createElement('div');
    this.stage.className = 'gea-stamp-preview__stage';

    this.page = document.createElement('div');
    this.page.className = 'gea-stamp-preview__page';

    this.canvas = document.createElement('canvas');
    this.canvas.className = 'gea-stamp-preview__canvas';
    this.canvas.style.display = 'none';
    this.page.appendChild(this.canvas);

    this.boxLayer = document.createElement('div');
    this.boxLayer.className = 'gea-stamp-preview__layer';
    this.page.appendChild(this.boxLayer);

    this.stage.appendChild(this.page);

    this.empty = document.createElement('p');
    this.empty.className = 'gea-stamp-preview__empty';
    this.empty.textContent = this.label('empty');

    this.root.appendChild(this.toolbar);
    this.root.appendChild(this.stage);
    this.root.appendChild(this.empty);
  };

  StampPreview.prototype.scope = function () {
    if (this.formScope) {
      return document.querySelector(this.formScope) || document;
    }
    return document;
  };

  StampPreview.prototype.rows = function () {
    if (!this.rowSelector) {
      return [];
    }
    return Array.prototype.slice.call(
      this.scope().querySelectorAll(this.rowSelector)
    );
  };

  StampPreview.prototype.placements = function () {
    if (this.staticPlacements) {
      return this.staticPlacements.map(function (item) {
        return {
          kind: item.kind,
          kind_label: item.kind_label,
          anchor: item.anchor,
          offset_x: toNumber(item.offset_x, 0),
          offset_y: toNumber(item.offset_y, 0),
          width: toNumber(item.width, 10),
          height: toNumber(item.height, 10),
          member_code: item.member_code || '',
          page_selector: item.page_selector,
          page_selector_label: item.page_selector_label || item.page_selector,
          page_numbers: item.page_numbers,
          _inputs: {}
        };
      });
    }

    return this.rows().map(readRow).filter(rowIsVisible);
  };

  StampPreview.prototype.bind = function () {
    var self = this;

    if (!this.staticPlacements) {
      var scope = this.scope();

      ['input', 'change'].forEach(function (eventName) {
        scope.addEventListener(eventName, function (event) {
          if (!event.target || !event.target.name) {
            return;
          }
          for (var i = 0; i < FIELDS.length; i += 1) {
            if (event.target.name.indexOf('-' + FIELDS[i]) !== -1) {
              self.render();
              return;
            }
          }
        });
      });

      if (window.django && window.django.jQuery) {
        window.django.jQuery(document).on(
          'formset:added formset:removed',
          function () { self.render(); }
        );
      }

      document.addEventListener('gea:formset-changed', function () {
        self.render();
      });
    }

    if (this.pdfInputSelector) {
      var input = document.querySelector(this.pdfInputSelector);

      if (input) {
        input.addEventListener('change', function () {
          var file = input.files && input.files[0];
          if (file) {
            self.loadPdf(file);
          } else {
            self.clearPdf();
          }
        });

        if (input.files && input.files[0]) {
          self.loadPdf(input.files[0]);
        }
      }
    }

    window.addEventListener('resize', function () {
      if (self.pdfDocument) {
        self.renderPdfPage();
      }
    });
  };

  StampPreview.prototype.scale = function () {
    var available = this.page.clientWidth || this.stage.clientWidth || 320;
    return available / this.pageW;
  };

  // ----------------------------------------------------------------
  // PDF de fondo
  // ----------------------------------------------------------------
  StampPreview.prototype.clearPdf = function () {
    this.cancelPdfRender();
    this.pdfDocument = null;
    this.pageCount = 0;
    this.currentPage = 1;
    this.canvas.style.display = 'none';
    this.pageNav.style.display = 'none';
    this.presetSelect.disabled = false;
    this.render();
  };

  StampPreview.prototype.loadPdf = function (file) {
    var self = this;

    this.hint.textContent = this.label('loading', 'Loading…');

    loadPdfJs()
      .then(function (pdfjsLib) {
        return file.arrayBuffer().then(function (buffer) {
          return pdfjsLib.getDocument({ data: buffer }).promise;
        });
      })
      .then(function (document_) {
        self.pdfDocument = document_;
        self.pageCount = document_.numPages;
        self.currentPage = 1;
        // Con un PDF real el tamano de pagina lo manda el archivo.
        self.presetSelect.disabled = true;
        self.buildPageNav();
        self.hint.textContent = self.editable ? self.label('hint') : '';
        return self.renderPdfPage();
      })
      .catch(function () {
        // Sin fondo, la vista previa sigue siendo util: solo pierde el PDF.
        self.hint.textContent = self.label('pdffailed');
        self.clearPdf();
      });
  };

  StampPreview.prototype.buildPageNav = function () {
    var self = this;

    this.pageNav.innerHTML = '';

    if (!this.pageCount) {
      this.pageNav.style.display = 'none';
      return;
    }

    var previous = document.createElement('button');
    previous.type = 'button';
    previous.className = 'gea-stamp-preview__pagebtn';
    previous.textContent = '‹';
    previous.addEventListener('click', function () {
      if (self.currentPage > 1) {
        self.currentPage -= 1;
        self.renderPdfPage();
      }
    });

    this.pageLabel = document.createElement('span');
    this.pageLabel.className = 'gea-stamp-preview__pagelabel';

    var next = document.createElement('button');
    next.type = 'button';
    next.className = 'gea-stamp-preview__pagebtn';
    next.textContent = '›';
    next.addEventListener('click', function () {
      if (self.currentPage < self.pageCount) {
        self.currentPage += 1;
        self.renderPdfPage();
      }
    });

    this.pageNav.appendChild(previous);
    this.pageNav.appendChild(this.pageLabel);
    this.pageNav.appendChild(next);
    this.pageNav.style.display = '';
  };

  StampPreview.prototype.renderPdfPage = function () {
    var self = this;

    if (!this.pdfDocument) {
      return Promise.resolve();
    }

    var token = ++this.renderToken;

    // pdf.js no admite dos render() simultaneos sobre el mismo canvas: hay
    // que cancelar el anterior antes de lanzar el siguiente. Sin esto, dos
    // llamadas seguidas (cambiar de archivo, pasar de pagina deprisa, un
    // resize durante la carga) tiraban la segunda y dejaban la vista a medias.
    this.cancelPdfRender();

    return this.pdfDocument.getPage(this.currentPage).then(function (page) {
      if (token !== self.renderToken) {
        return;   // llego una peticion mas nueva
      }

      var base = page.getViewport({ scale: 1 });

      // El tamano de la pagina lo dicta el PDF, no el selector.
      self.pageW = base.width;
      self.pageH = base.height;

      // Las cajas se recolocan ya, con la geometria real de la pagina: no
      // dependen de que el lienzo llegue a pintarse.
      self.render();

      var targetWidth = Math.max(
        self.page.clientWidth || self.stage.clientWidth || 320, 320
      );
      var ratio = window.devicePixelRatio || 1;
      var viewport = page.getViewport({ scale: targetWidth / base.width });

      self.canvas.width = Math.floor(viewport.width * ratio);
      self.canvas.height = Math.floor(viewport.height * ratio);
      self.canvas.style.display = '';

      var context = self.canvas.getContext('2d');
      context.setTransform(ratio, 0, 0, ratio, 0, 0);

      if (self.pageLabel) {
        self.pageLabel.textContent =
          self.currentPage + ' / ' + self.pageCount;
      }

      var task = page.render({
        canvasContext: context,
        viewport: viewport
      });

      self.pdfRenderTask = task;

      return task.promise.then(function () {
        self.pdfRenderTask = null;
        self.render();
      }, function (error) {
        self.pdfRenderTask = null;
        if (error && error.name === 'RenderingCancelledException') {
          return;   // la sustituyo una peticion mas nueva
        }
        throw error;
      });
    });
  };

  StampPreview.prototype.cancelPdfRender = function () {
    if (!this.pdfRenderTask) {
      return;
    }

    try {
      this.pdfRenderTask.cancel();
    } catch (error) {
      /* la tarea ya habia terminado */
    }

    this.pdfRenderTask = null;
  };

  // ----------------------------------------------------------------
  // Pintado
  // ----------------------------------------------------------------
  StampPreview.prototype.render = function () {
    var self = this;
    var all = this.placements();

    var visible = all.filter(function (placement) {
      return appliesToPage(placement, self.currentPage, self.pageCount);
    });

    this.page.style.paddingTop = (this.pageH / this.pageW) * 100 + '%';
    this.boxLayer.innerHTML = '';

    this.empty.style.display = all.length ? 'none' : '';

    visible.forEach(function (placement) {
      self.boxLayer.appendChild(self.buildBox(placement));
    });
  };

  StampPreview.prototype.applyBoxGeometry = function (box, placement) {
    var position = resolvePosition(
      placement.anchor, this.pageW, this.pageH, placement
    );

    box.style.left = (position.x / this.pageW) * 100 + '%';
    box.style.top =
      ((this.pageH - position.y - placement.height) / this.pageH) * 100 + '%';
    box.style.width = (placement.width / this.pageW) * 100 + '%';
    box.style.height = (placement.height / this.pageH) * 100 + '%';

    var outOfPage =
      position.x < 0 ||
      position.y < 0 ||
      position.x + placement.width > this.pageW ||
      position.y + placement.height > this.pageH;

    box.classList.toggle('gea-stamp-preview__box--outside', outOfPage);
    box.title = outOfPage ? this.label('outside') : '';

    return position;
  };

  StampPreview.prototype.buildBox = function (placement) {
    var box = document.createElement('div');

    box.className =
      'gea-stamp-preview__box gea-stamp-preview__box--' +
      kindClass(placement.kind);

    this.applyBoxGeometry(box, placement);

    var caption = document.createElement('span');
    caption.className = 'gea-stamp-preview__caption';
    caption.textContent = captionFor(placement);
    box.appendChild(caption);

    if (this.editable && placement._inputs && placement._inputs.offset_x) {
      box.classList.add('gea-stamp-preview__box--draggable');
      this.makeDraggable(box, placement);
    }

    return box;
  };

  StampPreview.prototype.makeDraggable = function (box, placement) {
    var self = this;

    box.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      event.stopPropagation();

      // La posicion de partida se recalcula aqui: entre el pintado y el
      // click el operador puede haber editado los inputs a mano.
      var origin = resolvePosition(
        placement.anchor, self.pageW, self.pageH, placement
      );

      var scale = self.scale();
      var startX = event.clientX;
      var startY = event.clientY;

      box.classList.add('is-dragging');

      try {
        box.setPointerCapture(event.pointerId);
      } catch (error) {
        /* algunos navegadores no lo permiten sobre elementos sinteticos */
      }

      function onMove(moveEvent) {
        var dx = (moveEvent.clientX - startX) / scale;
        // El eje Y del PDF crece hacia arriba; el de la pantalla, hacia abajo.
        var dy = -(moveEvent.clientY - startY) / scale;

        var nextX = Math.min(
          Math.max(origin.x + dx, 0), self.pageW - placement.width
        );
        var nextY = Math.min(
          Math.max(origin.y + dy, 0), self.pageH - placement.height
        );

        var offsets = offsetsFromPosition(
          placement.anchor, self.pageW, self.pageH,
          nextX, nextY, placement.width, placement.height
        );

        self.writeOffsets(placement, offsets);

        // Se mueve ESTA caja, sin repintar: un render() aqui destruiria el
        // propio elemento que se esta arrastrando y se perderia la captura
        // del puntero, que es justo lo que hacia que el arrastre saltase.
        self.applyBoxGeometry(box, placement);
      }

      function onUp(upEvent) {
        box.classList.remove('is-dragging');
        box.removeEventListener('pointermove', onMove);
        box.removeEventListener('pointerup', onUp);
        box.removeEventListener('pointercancel', onUp);

        try {
          box.releasePointerCapture(upEvent.pointerId);
        } catch (error) {
          /* el puntero ya se solto */
        }

        // Ahora si: un repintado completo deja todo coherente.
        self.render();

        document.dispatchEvent(
          new CustomEvent('gea:placement-moved', { detail: placement })
        );
      }

      box.addEventListener('pointermove', onMove);
      box.addEventListener('pointerup', onUp);
      box.addEventListener('pointercancel', onUp);
    });
  };

  StampPreview.prototype.writeOffsets = function (placement, offsets) {
    var inputs = placement._inputs;

    placement.offset_x = round2(offsets.offset_x);
    placement.offset_y = round2(offsets.offset_y);

    if (inputs.offset_x) {
      inputs.offset_x.value = placement.offset_x;
    }
    if (inputs.offset_y) {
      inputs.offset_y.value = placement.offset_y;
    }
  };

  // ----------------------------------------------------------------
  // Arranque
  // ----------------------------------------------------------------
  function initAll() {
    var roots = document.querySelectorAll('[data-gea-preview]');

    Array.prototype.forEach.call(roots, function (root) {
      if (root.dataset.geaPreviewReady === 'true') {
        return;
      }
      root.dataset.geaPreviewReady = 'true';
      root.__geaPreview = new StampPreview(root);
    });
  }

  window.GEAStampPreview = {
    init: initAll,
    resolvePosition: resolvePosition,
    offsetsFromPosition: offsetsFromPosition,
    appliesToPage: appliesToPage,
    instance: function (root) { return root && root.__geaPreview; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
