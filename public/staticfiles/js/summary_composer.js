/*
 * summary_composer.js — composicion de una caja AEGIS.
 *
 * Dos cosas a la vez:
 *
 *   - los miembros de la caja (que documentos y con que codigo), y
 *   - donde se estampan sus codigos de barras sobre el PDF del resumen.
 *
 * «Traer los codigos de barras» crea una posicion por miembro, ya enlazada a
 * su codigo. A partir de ahi se arrastran como cualquier otra caja:
 * `stamp_preview.js` las lee de la misma tabla.
 */
(function () {
  'use strict';

  var root = document.getElementById('memberRows');

  if (!root) {
    return;
  }

  var config = window.GEA_SUMMARY_CONFIG || {};

  var placementRows = document.getElementById('placementRows');
  var placementTemplate = document.getElementById('placementRowTemplate');
  var layoutSelect = document.getElementById('summaryLayout');
  var feedback = document.getElementById('summaryFeedback');

  var nextIndex = 0;

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
        if (alert.parentElement) { alert.parentElement.removeChild(alert); }
      }, 5000);
    }
  }

  function send(url, method, payload) {
    return fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(payload || {})
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    });
  }

  function repaint() {
    document.dispatchEvent(new CustomEvent('gea:formset-changed'));
  }

  // ----------------------------------------------------------------
  // Miembros
  // ----------------------------------------------------------------
  function memberRows() {
    return Array.prototype.slice.call(
      root.querySelectorAll('[data-member-row]')
    );
  }

  function collectMembers() {
    return memberRows().map(function (row) {
      var input = row.querySelector('[data-member-code]');
      return {
        code: (input ? input.value : '').trim().toUpperCase(),
        document_id: row.getAttribute('data-document-id'),
        document_type: row.getAttribute('data-title') || ''
      };
    });
  }

  document.getElementById('addMember').addEventListener('click', function () {
    var select = document.getElementById('candidateSelect');
    var value = select.value;

    if (!value) {
      notify(config.messages.pickDocument, 'warning');
      return;
    }

    var already = memberRows().some(function (row) {
      return row.getAttribute('data-document-id') === value;
    });

    if (already) {
      notify(config.messages.alreadyIn, 'warning');
      return;
    }

    var option = select.options[select.selectedIndex];
    var title = option.getAttribute('data-title') || option.text;

    var row = document.createElement('tr');
    row.setAttribute('data-member-row', '');
    row.setAttribute('data-document-id', value);
    row.setAttribute('data-title', title);

    // El codigo por defecto sigue la serie AEGIS-N.
    var code = 'AEGIS-' + (memberRows().length + 1);

    row.innerHTML =
      '<td><input type="text" class="form-control form-control-sm" ' +
      'data-member-code size="10" /></td>' +
      '<td class="text-break"></td>' +
      '<td class="text-end"><button type="button" ' +
      'class="btn btn-outline-danger btn-sm" data-remove-member>' +
      '<i class="bi bi-trash"></i></button></td>';

    row.querySelector('[data-member-code]').value = code;
    row.querySelector('td:nth-child(2)').textContent = title;

    root.appendChild(row);
    select.remove(select.selectedIndex);
    select.value = '';
  });

  root.addEventListener('click', function (event) {
    var button = event.target.closest('[data-remove-member]');

    if (!button) {
      return;
    }

    var row = button.closest('[data-member-row]');
    if (row) { row.remove(); }
  });

  document.getElementById('saveMembers').addEventListener('click', function () {
    var button = this;
    var members = collectMembers();

    if (!members.length) {
      notify(config.messages.needMembers, 'warning');
      return;
    }

    window.GEABusy.wrap(button, null, function () {
      return send(config.membersUrl, 'PATCH', { members: members })
        .then(function (result) {
          if (!result.ok) {
            notify(result.data.detail || config.messages.saveFailed, 'danger');
            return;
          }
          notify(result.data.detail, 'success');
          refreshState(result.data);
        })
        .catch(function () {
          notify(config.messages.saveFailed, 'danger');
        });
    });
  });

  // ----------------------------------------------------------------
  // Sellado y envio a la cadena de bloques
  //
  // Son dos actos separados, y por eso hay tres botones y no uno. Sellar es
  // una escritura nuestra, instantanea. Enviar sale a la red: puede tardar o
  // fallar, y cuando falla el sello ya esta guardado, asi que el servidor
  // responde 200 con `anchor_result: 'failed'`. Eso NO es un error de la
  // operacion -- se avisa en amarillo y el boton de enviar queda disponible.
  // ----------------------------------------------------------------
  function runSealAction(button, url, payload) {
    window.GEABusy.wrap(button, null, function () {
      return send(url, 'POST', payload)
        .then(function (result) {
          if (!result.ok) {
            notify(result.data.detail || config.messages.saveFailed, 'danger');
            return;
          }

          notify(
            result.data.detail,
            result.data.anchor_result === 'failed' ? 'warning' : 'success'
          );

          refreshState(result.data);
        })
        .catch(function () {
          notify(config.messages.saveFailed, 'danger');
        });
    });
  }

  bindSealButton('sealAndSend', config.sealUrl, { anchor: true });
  bindSealButton('sealSummary', config.sealUrl, { anchor: false });
  bindSealButton('sendToBlockchain', config.anchorUrl, {});

  function bindSealButton(id, url, payload) {
    var button = document.getElementById(id);

    if (!button) { return; }

    button.addEventListener('click', function () {
      runSealAction(this, url, payload);
    });
  }

  function refreshState(data) {
    var hash = document.getElementById('masterHash');
    var status = document.getElementById('summaryStatus');
    var chain = document.getElementById('blockchainStatus');
    var sendButton = document.getElementById('sendToBlockchain');

    if (hash) { hash.textContent = data.master_hash || '—'; }
    if (status) { status.textContent = data.status_label || ''; }

    if (chain && data.blockchain_label) {
      chain.textContent = data.blockchain_label;
      chain.className = 'badge ' + (
        data.sent_to_blockchain ? 'bg-warning text-dark' : 'bg-secondary'
      );
    }

    // Solo se puede enviar lo que esta sellado y no se ha enviado ya. Al
    // resellar con miembros distintos el master hash cambia, el envio anterior
    // deja de cubrirlo y el boton vuelve a habilitarse solo.
    if (sendButton && typeof data.can_send_to_blockchain === 'boolean') {
      sendButton.disabled = !data.can_send_to_blockchain;
    }
  }

  // ----------------------------------------------------------------
  // Posiciones
  // ----------------------------------------------------------------
  function addPlacement(values) {
    var html = placementTemplate.innerHTML.replace(/IDX/g, nextIndex);
    nextIndex += 1;

    var holder = document.createElement('tbody');
    holder.innerHTML = html.trim();

    var row = holder.querySelector('tr');
    if (!row) { return null; }

    if (values) {
      Object.keys(values).forEach(function (field) {
        var input = row.querySelector('[name$="-' + field + '"]');
        if (input) { input.value = values[field]; }
      });
    }

    placementRows.appendChild(row);
    return row;
  }

  document.getElementById('addPlacement').addEventListener('click', function () {
    addPlacement(null);
    repaint();
  });

  placementRows.addEventListener('click', function (event) {
    var button = event.target.closest('[data-remove-placement]');

    if (!button) { return; }

    var row = button.closest('[data-placement-row]');
    if (row) { row.remove(); repaint(); }
  });

  // «Traer los codigos de barras de los miembros»: una posicion por miembro,
  // apiladas para que se vean todas y se puedan arrastrar una a una.
  document.getElementById('addMemberBarcodes')
    .addEventListener('click', function () {
      var members = collectMembers().filter(function (m) { return m.code; });

      if (!members.length) {
        notify(config.messages.needMembers, 'warning');
        return;
      }

      var existing = Array.prototype.slice
        .call(placementRows.querySelectorAll('[name$="-member_code"]'))
        .map(function (input) { return input.value.trim().toUpperCase(); });

      var added = 0;

      members.forEach(function (member, index) {
        if (existing.indexOf(member.code) !== -1) {
          return;
        }

        addPlacement({
          kind: 'MEMBER',
          member_code: member.code,
          page_selector: 'LAST',
          anchor: 'BL',
          offset_x: 40,
          // Se reparten en vertical para que no queden una encima de otra.
          offset_y: 60 + index * 70,
          width: 216,
          height: 54
        });

        added += 1;
      });

      repaint();

      if (added) {
        notify(config.messages.broughtBarcodes, 'info');
      }
    });

  document.getElementById('savePlacements').addEventListener('click', function () {
    var button = this;
    var pk = layoutSelect ? layoutSelect.value : '';

    if (!pk) {
      notify(config.messages.pickLayout, 'warning');
      return;
    }

    var placements = Array.prototype.slice
      .call(placementRows.querySelectorAll('[data-placement-row]'))
      .map(function (row) {
        function value(field) {
          var input = row.querySelector('[name$="-' + field + '"]');
          return input ? input.value : '';
        }
        return {
          kind: value('kind'),
          member_code: value('member_code'),
          page_selector: value('page_selector'),
          page_numbers: value('page_numbers'),
          anchor: value('anchor'),
          offset_x: parseFloat(value('offset_x')) || 0,
          offset_y: parseFloat(value('offset_y')) || 0,
          width: parseFloat(value('width')) || 0,
          height: parseFloat(value('height')) || 0,
          opacity: 1,
          is_active: true
        };
      });

    window.GEABusy.wrap(button, null, function () {
      return send(
        config.placementsUrl.replace('/0/', '/' + pk + '/'),
        'PATCH',
        { placements: placements }
      ).then(function (result) {
        if (!result.ok) {
          notify(result.data.detail || config.messages.saveFailed, 'danger');
          return;
        }
        notify(result.data.detail, 'success');
        repaint();
      }).catch(function () {
        notify(config.messages.saveFailed, 'danger');
      });
    });
  });

  // ----------------------------------------------------------------
  // Carga inicial de las posiciones del layout elegido
  // ----------------------------------------------------------------
  function loadPlacements(pk) {
    placementRows.innerHTML = '';

    if (!pk) { repaint(); return; }

    fetch(config.placementsUrl.replace('/0/', '/' + pk + '/'), {
      credentials: 'same-origin'
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        (data.placements || []).forEach(function (placement) {
          addPlacement({
            kind: placement.kind,
            member_code: placement.member_code || '',
            page_selector: placement.page_selector,
            page_numbers: placement.page_numbers || '',
            anchor: placement.anchor,
            offset_x: placement.offset_x,
            offset_y: placement.offset_y,
            width: placement.width,
            height: placement.height
          });
        });
        repaint();
      })
      .catch(function () { /* la vista previa es opcional */ });
  }

  if (layoutSelect) {
    layoutSelect.addEventListener('change', function () {
      loadPlacements(layoutSelect.value);
    });
    loadPlacements(layoutSelect.value);
  }
})();
