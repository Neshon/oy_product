/* Выпадающий список.
 *
 * Оформить список вариантов у родного <select> браузер не даёт: внутри
 * системного меню не работают ни шрифт, ни цвета, ни поиск. А вариантов у
 * фильтров бывает под три сотни (см. listing.MAX_FILTER_CHOICES), и найти
 * среди них нужный прокруткой почти невозможно.
 *
 * Поэтому список рисуется сам, а родной <select> остаётся в форме и
 * по-прежнему хранит значение: он же отправляется, он же участвует в
 * проверке, и он же остаётся единственным списком, если скрипт не
 * загрузился. Отсюда правило: значение меняется только через него, а
 * событие change отправляется так, будто выбрал человек, — иначе фильтры с
 * data-autosubmit перестали бы отправлять форму.
 *
 * Меню лежит в body и позиционируется fixed: списки стоят и в панелях с
 * прокруткой, и в шапке таблицы, и любой overflow: hidden обрезал бы его.
 *
 * Список с multiple — это фильтры над таблицей. Там варианты отмечаются
 * галочками, и каждая галочка применяется сразу: список внизу и остальные
 * фильтры должны показывать отобранное, а не то, что было до щелчка.
 *
 * Значения одного фильтра уходят в строку запроса одним параметром через
 * вертикальную черту (`?vendor=TDK|Murata`) — так ссылку проще прочитать и
 * переслать. Браузер сам отправил бы их повторяющимся параметром, поэтому
 * перед отправкой они склеиваются (см. pack). Сервер понимает оба вида, так
 * что без скрипта страница тоже работает.
 */
(function () {
  "use strict";

  // с какого числа вариантов показывать поиск: до этого он только мешает
  var SEARCH_FROM = 8;
  // на сколько меню может быть шире кнопки: у фильтров кнопка узкая
  // (110px), а значения в ней длинные
  var MIN_MENU = 200;
  var GAP = 6;

  var SEPARATOR = "|";

  var counter = 0;
  var open = null;   // открытый список; одновременно он всегда один

  function text(node) {
    return (node.textContent || "").trim();
  }

  function build(select) {
    var many = select.multiple;
    var pick = document.createElement("div");
    pick.className = many ? "pick pick--multi" : "pick";
    select.parentNode.insertBefore(pick, select);
    pick.appendChild(select);

    select.classList.add("pick__native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var id = "pick-" + (++counter);
    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = id + "-btn";
    // классы родного списка переносим на кнопку: от них зависит и размер
    // (field--select), и вид запертого поля (field--locked)
    trigger.className = ("pick__trigger " + select.className)
      .replace("pick__native", "").replace(/\s+/g, " ").trim();
    trigger.disabled = select.disabled;
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", id);

    // подпись поля вела на скрытый теперь <select>: клик по ней ставил
    // фокус туда, где ничего не видно. Переводим её на кнопку
    var caption = select.id
      ? document.querySelector('label[for="' + select.id + '"]') : null;
    if (caption) {
      caption.htmlFor = trigger.id;
      if (!caption.id) { caption.id = id + "-label"; }
      trigger.setAttribute("aria-labelledby", caption.id);
    } else if (select.getAttribute("aria-label")) {
      // подписи рядом нет — списку её заменяет aria-label, и кнопке она
      // нужна так же: без неё чтение с экрана назовёт её просто «кнопка»
      trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    }
    // подсказку при наведении тоже переносим; у фильтров её ставит show(),
    // там в ней перечислено выбранное
    if (select.title && !many) { trigger.title = select.title; }

    var label = document.createElement("span");
    label.className = "pick__label";
    trigger.appendChild(label);
    trigger.insertAdjacentHTML("beforeend",
      '<svg class="pick__arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
      ' stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M6 9l6 6 6-6"></path></svg>');
    pick.appendChild(trigger);

    var menu = document.createElement("div");
    menu.className = "pick__menu";
    menu.id = id;
    menu.hidden = true;

    var find = null;
    if (select.options.length >= SEARCH_FROM) {
      find = document.createElement("input");
      find.type = "text";
      find.className = "pick__find";
      find.placeholder = "Поиск";
      find.autocomplete = "off";
      menu.appendChild(find);
    }

    var list = document.createElement("ul");
    list.className = "pick__list";
    list.setAttribute("role", "listbox");
    if (many) { list.setAttribute("aria-multiselectable", "true"); }
    list.tabIndex = -1;
    menu.appendChild(list);

    var empty = document.createElement("p");
    empty.className = "pick__empty";
    empty.textContent = "Ничего не найдено";
    empty.hidden = true;
    menu.appendChild(empty);

    var items = [];
    Array.prototype.forEach.call(select.options, function (option, index) {
      var item = document.createElement("li");
      item.className = "pick__option";
      item.setAttribute("role", "option");
      item.id = id + "-o" + index;
      item.textContent = text(option) || option.value;
      item.dataset.value = option.value;
      item.dataset.search = item.textContent.toLowerCase();
      list.appendChild(item);
      items.push(item);
    });

    document.body.appendChild(menu);

    return {select: select, pick: pick, trigger: trigger, label: label,
            menu: menu, list: list, find: find, empty: empty, items: items,
            active: -1, many: many,
            // название фильтра: стоит на кнопке, пока ничего не выбрано
            title: select.dataset.title || ""};
  }

  function chosen(box) {
    return Array.prototype.filter.call(box.select.options, function (option) {
      return option.selected;
    });
  }

  function summary(box, picked) {
    // на кнопке видно, что включено; когда значений много, хвост
    // сворачивается в счётчик — иначе кнопка растянется на всю панель
    var names = picked.map(text);
    var head = box.title ? box.title + ": " : "";
    if (!names.length) { return box.title; }
    if (names.length <= 2) { return head + names.join(", "); }
    return head + names.slice(0, 2).join(", ") + " +" + (names.length - 2);
  }

  function show(box) {
    var picked = chosen(box);

    if (box.many) {
      box.label.textContent = summary(box, picked);
      box.trigger.classList.toggle("is-set", picked.length > 0);
      if (picked.length > 2) {
        box.trigger.title = picked.map(text).join(", ");
      } else {
        box.trigger.removeAttribute("title");
      }
    } else {
      box.label.textContent = picked.length
        ? (text(picked[0]) || picked[0].value) : "";
      // «фильтр задан» — это когда в списке есть пустой вариант («все»),
      // и выбран не он. У обычных полей формы пустого варианта нет
      var hasEmpty = Array.prototype.some.call(box.select.options, function (o) {
        return o.value === "";
      });
      box.trigger.classList.toggle("is-set",
                                   hasEmpty && box.select.value !== "");
    }

    box.items.forEach(function (item, index) {
      item.setAttribute("aria-selected",
                        box.select.options[index].selected ? "true" : "false");
    });
  }

  function place(box) {
    var rect = box.trigger.getBoundingClientRect();
    var menu = box.menu;
    menu.style.minWidth = Math.max(rect.width, MIN_MENU) + "px";

    // сначала показываем, потом меряем: у скрытого меню размеров нет
    var height = menu.offsetHeight;
    var width = menu.offsetWidth;
    var below = window.innerHeight - rect.bottom - GAP;
    var above = rect.top - GAP;
    // не помещается снизу, а сверху места больше — открываем вверх
    var up = below < height && above > below;

    var top = up ? Math.max(GAP, rect.top - GAP - height) : rect.bottom + GAP;
    var left = Math.min(rect.left, window.innerWidth - width - GAP);
    menu.style.top = Math.round(top) + "px";
    menu.style.left = Math.round(Math.max(GAP, left)) + "px";
  }

  function highlight(box, index) {
    var visible = box.items.filter(function (item) { return !item.hidden; });
    if (!visible.length) { return; }
    if (index < 0) { index = visible.length - 1; }
    if (index >= visible.length) { index = 0; }

    box.items.forEach(function (item) { item.classList.remove("is-active"); });
    var item = visible[index];
    item.classList.add("is-active");
    box.active = box.items.indexOf(item);
    box.list.setAttribute("aria-activedescendant", item.id);

    var top = item.offsetTop;
    var bottom = top + item.offsetHeight;
    if (top < box.list.scrollTop) { box.list.scrollTop = top; }
    else if (bottom > box.list.scrollTop + box.list.clientHeight) {
      box.list.scrollTop = bottom - box.list.clientHeight;
    }
  }

  function visibleIndex(box) {
    var visible = box.items.filter(function (item) { return !item.hidden; });
    return visible.indexOf(box.items[box.active]);
  }

  function filter(box) {
    var term = (box.find.value || "").trim().toLowerCase();
    var shown = 0;
    box.items.forEach(function (item) {
      var fits = !term || item.dataset.search.indexOf(term) !== -1;
      item.hidden = !fits;
      if (fits) { shown++; }
    });
    box.empty.hidden = shown > 0;
    highlight(box, 0);
    place(box);
  }

  function openMenu(box) {
    if (open === box) { return; }
    closeMenu();
    open = box;

    show(box);
    box.menu.hidden = false;
    box.pick.classList.add("is-open");
    box.trigger.setAttribute("aria-expanded", "true");

    if (box.find) {
      box.find.value = "";
      box.items.forEach(function (item) { item.hidden = false; });
      box.empty.hidden = true;
    }
    place(box);

    // подсветка начинается с выбранного варианта, а не с первого
    var chosen = box.items[box.select.selectedIndex];
    var visible = box.items.filter(function (item) { return !item.hidden; });
    highlight(box, chosen ? Math.max(0, visible.indexOf(chosen)) : 0);

    (box.find || box.list).focus({preventScroll: true});
  }

  function closeMenu(focusTrigger) {
    if (!open) { return; }
    var box = open;
    open = null;
    box.menu.hidden = true;
    box.pick.classList.remove("is-open");
    box.trigger.setAttribute("aria-expanded", "false");
    if (focusTrigger) { box.trigger.focus(); }
  }

  function choose(box, item) {
    // скрытого поиском варианта в списке сейчас нет — выбирать нечего
    if (!item || item.hidden) { return; }

    if (box.many) {
      // отметку и ставим, и снимаем; меню при этом не закрывается, но
      // отбор применяется сразу — страница перезагрузится с новым набором
      var option = box.select.options[box.items.indexOf(item)];
      option.selected = !option.selected;
      show(box);
      place(box);
      box.select.dispatchEvent(new Event("change", {bubbles: true}));
      return;
    }

    var changed = box.select.value !== item.dataset.value;
    box.select.value = item.dataset.value;
    show(box);
    closeMenu(true);
    if (changed) {
      // событие должно выглядеть как выбор человека: на нём висит
      // автоотправка формы у фильтров
      box.select.dispatchEvent(new Event("change", {bubbles: true}));
    }
  }

  function wire(box) {
    show(box);

    box.trigger.addEventListener("click", function () {
      if (open === box) { closeMenu(true); } else { openMenu(box); }
    });

    box.trigger.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openMenu(box);
      }
    });

    box.list.addEventListener("click", function (event) {
      var item = event.target.closest(".pick__option");
      if (item) { choose(box, item); }
    });

    box.list.addEventListener("mousemove", function (event) {
      var item = event.target.closest(".pick__option");
      if (!item || item.classList.contains("is-active")) { return; }
      var visible = box.items.filter(function (each) { return !each.hidden; });
      highlight(box, visible.indexOf(item));
    });

    if (box.find) {
      box.find.addEventListener("input", function () { filter(box); });
    }

    box.menu.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        highlight(box, visibleIndex(box) + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        highlight(box, visibleIndex(box) - 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        highlight(box, 0);
      } else if (event.key === "End") {
        event.preventDefault();
        highlight(box, -1);   // -1 — последний из видимых
      } else if (event.key === "Enter") {
        event.preventDefault();
        choose(box, box.items[box.active]);
      } else if (event.key === "Escape" || event.key === "Tab") {
        // Фокус в обоих случаях возвращается на кнопку: Esc на ней и
        // остаётся, а Tab (его не отменяем) уходит с неё дальше по форме.
        // Иначе фокус остался бы на спрятанном меню и потерялся совсем.
        closeMenu(true);
      }
    });
  }

  function pack(form) {
    // Значения одного фильтра — одним параметром через `|`. Само поле из
    // отправки убираем, иначе те же значения уйдут ещё и по одному
    form.querySelectorAll("select[multiple][name]").forEach(function (select) {
      var picked = Array.prototype.filter.call(select.options, function (o) {
        return o.selected;
      }).map(function (option) { return option.value; });

      var carrier = document.createElement("input");
      carrier.type = "hidden";
      carrier.name = select.name;
      carrier.value = picked.join(SEPARATOR);
      select.removeAttribute("name");
      if (picked.length) { form.appendChild(carrier); }
    });
  }

  function enhance(select) {
    if (select.size > 1 || select.dataset.pick) { return; }
    select.dataset.pick = "1";

    var form = select.form;
    if (select.multiple && form && !form.dataset.pickPacked) {
      form.dataset.pickPacked = "1";
      form.addEventListener("submit", function (event) { pack(event.target); });
    }

    var box = build(select);
    if (!select.disabled) { wire(box); } else { show(box); }
  }

  function start() {
    document.querySelectorAll("select.field").forEach(enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  // клик мимо меню закрывает его; клик по своей же кнопке обрабатывает она
  document.addEventListener("mousedown", function (event) {
    if (!open) { return; }
    if (open.menu.contains(event.target) || open.pick.contains(event.target)) {
      return;
    }
    closeMenu();
  });

  // страница поехала под меню — оно должно поехать вместе с ней
  window.addEventListener("scroll", function () {
    if (open) { place(open); }
  }, true);
  window.addEventListener("resize", function () {
    if (open) { place(open); }
  });
})();
