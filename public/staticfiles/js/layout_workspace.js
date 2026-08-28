/*
 * layout_workspace.js — edicion de la disposicion desde el generador.
 *
 * La tabla de posiciones y la vista previa comparten los mismos inputs:
 * `stamp_preview.js` los lee para pintar, y al arrastrar una caja los
 * reescribe. Aqui solo se gestiona el alta y baja de filas, la carga de una
 * disposicion existente y el guardado contra la API.
 *
 * Guardar        -> PATCH sobre la disposicion seleccionada.
 * Guardar y crear-> POST de una disposicion nueva (pide nombre y descripcion).
 */
(function () {
  'use strict';

  var workspace = document.getElementById('layoutWorkspace');

  if (!workspace) {
    return;
  }

  var config = window.GEA_LAYOUT_CONFIG || {};

  var rows = document.getElementById('placementRows');
  var template = document.getElementById('placementRowTemplate');
  var layoutSelect = document.getElementById('id_stamp_layout');
  var feedback = document.getElementById('layoutFeedback');
  var previewRoot = document.getElementById('layoutPreview');

  var nextIndex = 0;

  // ----------------------------------------------------------------
  // Utilidades
  // ----------------------------------------------------------------
  function csrfToken() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function notify(message, level) {
    feedback.innerHTML = '';

    if (!message) {
      return;
    }

    var alert = document.createElement('div');
    alert.className = 'alert alert-' + (level || 'info') + ' py-2 small';
    alert.textContent = message;
    feedback.appendChild(alert);

    if (level === 'success') {
      window.setTimeout(function () {
        if (alert.parentElement) {
          alert.parentElement.removeChild(alert);
        }
      }, 4000);
    }
  }

  function repaint() {
    document.dispatchEvent(new CustomEvent('gea:formset-changed'));
  }

  // ----------------------------------------------------------------
  // Filas
  // ----------------------------------------------------------------
  function addRow(placement) {
    var html = template.innerHTML.replace(/IDX/g, nextIndex);
    nextIndex += 1;

    var holder = document.createElement('tbody');
    holder.innerHTML = html.trim();

    var row = holder.querySelector('tr');
    if (!row) {
      return null;
    }

    if (placement) {
      setValue(row, 'kind', placement.kind);
      setValue(row, 'page_selector', placement.page_selector);
      setValue(row, 'page_numbers', placement.page_numbers || '');
      setValue(row, 'anchor', placement.anchor);
      setValue(row, 'offset_x', placement.offset_x);
      setValue(row, 'offset_y', placement.offset_y);
      setValue(row, 'width', placement.width);
      setValue(row, 'height', placement.height);
    }

    rows.appendChild(row);
    return row;
  }

  function setValue(row, field, value) {
    var input = row.querySelector('[name$="-' + field + '"]');
    if (input) {
      input.value = value;
    }
  }

  function getValue(row, field) {
    var input = row.querySelector('[name$="-' + field + '"]');
    return input ? input.value : '';
  }

  function collect() {
    return Array.prototype.slice
      .call(rows.querySelectorAll('[data-placement-row]'))
      .map(function (row) {
        return {
          kind: getValue(row, 'kind'),
          page_selector: getValue(row, 'page_selector'),
          page_numbers: getValue(row, 'page_numbers'),
          anchor: getValue(row, 'anchor'),
          offset_x: parseFloat(getValue(row, 'offset_x')) || 0,
          offset_y: parseFloat(getValue(row, 'offset_y')) || 0,
          width: parseFloat(getValue(row, 'width')) || 0,
          height: parseFloat(getValue(row, 'height')) || 0,
          opacity: 1,
          is_active: true
        };
      });
  }

  rows.addEventListener('click', function (event) {
    var button = event.target.closest('[data-remove-placement]');

    if (!button) {
      return;
    }

    var row = button.closest('[data-placement-row]');
    if (row) {
      row.remove();
      repaint();
    }
  });

  document.getElementById('addPlacement').addEventListener('click', function () {
    addRow(null);
    repaint();
  });

  // ----------------------------------------------------------------
  // Cargar la disposicion seleccionada
  // ----------------------------------------------------------------
  function loadLayout(pk) {
    rows.innerHTML = '';

    if (!pk) {
      repaint();
      return;
    }

    fetch(config.placementsUrl.replace('/0/', '/' + pk + '/'), {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        (data.placements || []).forEach(function (placement) {
          addRow(placement);
        });
        repaint();
      })
      .catch(function () {
        notify(config.messages.loadFailed, 'warning');
      });
  }

  if (layoutSelect) {
    layoutSelect.addEventListener('change', function () {
      loadLayout(layoutSelect.value);
    });
    loadLayout(layoutSelect.value);
  }

  // ----------------------------------------------------------------
  // Guardar
  // ----------------------------------------------------------------
  function send(url, method, payload) {
    return fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, status: response.status, data: data };
      });
    });
  }

  var saveButton = document.getElementById('savePlacements');

  saveButton.addEventListener('click', function () {
    var pk = layoutSelect ? layoutSelect.value : '';

    if (!pk) {
      notify(config.messages.pickLayout, 'warning');
      return;
    }

    var placements = collect();

    if (!placements.length) {
      notify(config.messages.needPlacement, 'warning');
      return;
    }

    // wrap() devuelve null si el boton ya estaba ocupado: el segundo click
    // durante un guardado en curso se descarta sin llegar a la red.
    window.GEABusy.wrap(saveButton, config.messages.saving, function () {
      return send(
        config.placementsUrl.replace('/0/', '/' + pk + '/'),
        'PATCH',
        { placements: placements }
      ).then(function (result) {
        if (result.ok) {
          notify(result.data.detail, 'success');
          repaint();
        } else {
          notify(result.data.detail || config.messages.saveFailed, 'danger');
        }
      }).catch(function () {
        notify(config.messages.saveFailed, 'danger');
      });
    });
  });

  // ---- Guardar y crear ----
  var modalElement = document.getElementById('newLayoutModal');
  var modal = window.bootstrap ? new window.bootstrap.Modal(modalElement) : null;
  var nameInput = document.getElementById('newLayoutName');
  var descriptionInput = document.getElementById('newLayoutDescription');
  var defaultInput = document.getElementById('newLayoutDefault');
  var modalError = document.getElementById('newLayoutError');

  document.getElementById('savePlacementsAs').addEventListener('click', function () {
    if (!collect().length) {
      notify(config.messages.needPlacement, 'warning');
      return;
    }

    modalError.innerHTML = '';
    nameInput.classList.remove('is-invalid');

    if (modal) {
      modal.show();
    }
  });

  var confirmButton = document.getElementById('confirmNewLayout');

  confirmButton.addEventListener('click', function () {
    var name = (nameInput.value || '').trim();

    modalError.innerHTML = '';
    nameInput.classList.remove('is-invalid');

    if (!name) {
      nameInput.classList.add('is-invalid');
      modalError.innerHTML =
        '<div class="alert alert-warning py-2 small"></div>';
      modalError.firstChild.textContent = config.messages.nameRequired;
      return;
    }

    window.GEABusy.wrap(confirmButton, config.messages.creating, function () {
    return send(config.createUrl, 'POST', {
      name: name,
      description: descriptionInput.value || '',
      is_default: defaultInput.checked,
      placements: collect()
    }).then(function (result) {
      if (!result.ok) {
        modalError.innerHTML =
          '<div class="alert alert-danger py-2 small"></div>';
        modalError.firstChild.textContent =
          result.data.detail || config.messages.saveFailed;
        return;
      }

      // La disposicion nueva se anade al selector y queda seleccionada.
      if (layoutSelect) {
        var option = document.createElement('option');
        option.value = result.data.id;
        option.textContent = result.data.name;
        layoutSelect.appendChild(option);
        layoutSelect.value = result.data.id;
      }

      if (modal) {
        modal.hide();
      }

      nameInput.value = '';
      descriptionInput.value = '';
      defaultInput.checked = false;

      notify(result.data.detail, 'success');
    }).catch(function () {
      modalError.innerHTML =
        '<div class="alert alert-danger py-2 small"></div>';
      modalError.firstChild.textContent = config.messages.saveFailed;
    });
    });
  });

  // Al soltar una caja se avisa de que hay cambios sin guardar.
  document.addEventListener('gea:placement-moved', function () {
    notify(config.messages.unsaved, 'info');
  });
})();
