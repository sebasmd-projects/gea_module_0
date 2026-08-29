/**
 * Buscador para desplegables largos.
 *
 * Marca un `<select>` con `data-searchable` y este modulo le pone una caja de
 * busqueda encima. El `<select>` original **se queda en el DOM**, oculto: sigue
 * enviandose con el formulario y el resto del JS puede seguir leyendo su
 * `.value` sin enterarse de nada. Esto es a proposito -- reemplazarlo por un
 * campo propio habria obligado a tocar `summary_composer.js` y compania.
 *
 * Sin dependencias: select2 solo esta disponible dentro del admin, y estas
 * paginas son del dashboard.
 */
(function () {
  'use strict';

  var OPEN_CLASS = 'gea-select--open';

  function normalize(text) {
    // Sin acentos y en minusculas: buscar "bono" debe encontrar "Bonó".
    return (text || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '');
  }

  function SearchableSelect(select) {
    this.select = select;
    this.placeholder =
      select.getAttribute('data-search-placeholder') || 'Search…';
    this.emptyText =
      select.getAttribute('data-search-empty') || 'No matches';

    this.build();
    this.bind();
    this.syncFromSelect();
  }

  SearchableSelect.prototype.build = function () {
    var select = this.select;

    this.wrap = document.createElement('div');
    this.wrap.className = 'gea-select';

    select.parentNode.insertBefore(this.wrap, select);
    this.wrap.appendChild(select);
    select.classList.add('gea-select__native');

    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.className = 'form-control gea-select__input';
    this.input.placeholder = this.placeholder;
    this.input.autocomplete = 'off';
    this.input.setAttribute('role', 'combobox');
    this.input.setAttribute('aria-expanded', 'false');
    this.input.setAttribute('aria-autocomplete', 'list');

    if (select.disabled) {
      this.input.disabled = true;
    }

    this.list = document.createElement('ul');
    this.list.className = 'gea-select__list';
    this.list.setAttribute('role', 'listbox');

    this.wrap.appendChild(this.input);
    this.wrap.appendChild(this.list);
  };

  /** Opciones del `<select>`, saltando la vacia de "elige una". */
  SearchableSelect.prototype.options = function () {
    return Array.prototype.filter.call(
      this.select.options,
      function (option) { return option.value !== ''; }
    );
  };

  SearchableSelect.prototype.syncFromSelect = function () {
    var option = this.select.options[this.select.selectedIndex];
    this.input.value = option && option.value ? option.text.trim() : '';
  };

  SearchableSelect.prototype.open = function (query) {
    var self = this;
    var needle = normalize(query);

    this.list.innerHTML = '';

    var matches = this.options().filter(function (option) {
      return !needle || normalize(option.text).indexOf(needle) !== -1;
    });

    if (!matches.length) {
      var empty = document.createElement('li');
      empty.className = 'gea-select__empty';
      empty.textContent = this.emptyText;
      this.list.appendChild(empty);
    }

    matches.slice(0, 200).forEach(function (option) {
      var item = document.createElement('li');

      item.className = 'gea-select__option';
      item.textContent = option.text.trim();
      item.setAttribute('role', 'option');
      item.dataset.value = option.value;

      if (option.value === self.select.value) {
        item.classList.add('is-selected');
      }

      // `mousedown` y no `click`: el blur del input llega antes que el click y
      // cerraria la lista sin que el item llegase a recibirlo.
      item.addEventListener('mousedown', function (event) {
        event.preventDefault();
        self.choose(option.value);
      });

      self.list.appendChild(item);
    });

    this.wrap.classList.add(OPEN_CLASS);
    this.input.setAttribute('aria-expanded', 'true');
    this.active = -1;
  };

  SearchableSelect.prototype.close = function () {
    this.wrap.classList.remove(OPEN_CLASS);
    this.input.setAttribute('aria-expanded', 'false');
  };

  SearchableSelect.prototype.choose = function (value) {
    this.select.value = value;

    // El resto del codigo escucha al `<select>`, no a este componente.
    this.select.dispatchEvent(new Event('change', { bubbles: true }));

    this.syncFromSelect();
    this.close();
  };

  SearchableSelect.prototype.move = function (delta) {
    var items = this.list.querySelectorAll('.gea-select__option');

    if (!items.length) {
      return;
    }

    this.active = Math.max(
      0, Math.min(items.length - 1, (this.active || 0) + delta)
    );

    Array.prototype.forEach.call(items, function (item, index) {
      item.classList.toggle('is-active', index === this.active);
    }, this);

    items[this.active].scrollIntoView({ block: 'nearest' });
  };

  SearchableSelect.prototype.bind = function () {
    var self = this;

    this.input.addEventListener('focus', function () {
      self.open('');
      self.input.select();
    });

    this.input.addEventListener('input', function () {
      self.open(self.input.value);
    });

    this.input.addEventListener('blur', function () {
      // Al salir sin elegir, se repone lo que hubiera seleccionado: dejar
      // texto suelto que no corresponde a ninguna opcion engana.
      window.setTimeout(function () {
        self.close();
        self.syncFromSelect();
      }, 120);
    });

    this.input.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!self.wrap.classList.contains(OPEN_CLASS)) {
          self.open(self.input.value);
        }
        self.move(1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        self.move(-1);
      } else if (event.key === 'Enter') {
        var active = self.list.querySelector('.gea-select__option.is-active')
          || self.list.querySelector('.gea-select__option');

        if (self.wrap.classList.contains(OPEN_CLASS) && active) {
          event.preventDefault();
          self.choose(active.dataset.value);
        }
      } else if (event.key === 'Escape') {
        self.close();
        self.syncFromSelect();
      }
    });

    // Si otro script cambia el `<select>` -- al recargar la lista de
    // candidatos, por ejemplo -- la caja de texto tiene que enterarse.
    this.select.addEventListener('change', function () {
      self.syncFromSelect();
    });
  };

  function initAll(scope) {
    var selects = (scope || document).querySelectorAll(
      'select[data-searchable]'
    );

    Array.prototype.forEach.call(selects, function (select) {
      if (select.dataset.geaSearchableReady === 'true') {
        return;
      }
      select.dataset.geaSearchableReady = 'true';
      select.__geaSearchable = new SearchableSelect(select);
    });
  }

  window.GEASearchableSelect = { init: initAll };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { initAll(); });
  } else {
    initAll();
  }
})();
