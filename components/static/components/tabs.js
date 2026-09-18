/* Вкладки поверх обычных панелей.
 *
 * Разметка остаётся плоской: панели идут одна за другой и без скрипта
 * читаются как обычная страница — все видны, у каждой свой заголовок.
 * Скрипт лишь собирает из их заголовков полоску вкладок и прячет все,
 * кроме выбранной. Поэтому и без JS, и при ошибке в нём страница остаётся
 * рабочей — потерять карточку ревизии из-за сломанной вкладки нельзя.
 *
 * Включается атрибутом на обёртке:
 *
 *     <div class="tabs" data-tabs>
 *       <div class="panel" data-tab="Документы">…</div>
 *       <div class="panel" data-tab="Чек-лист SMT">…</div>
 *     </div>
 *
 * Выбранная вкладка живёт в адресе (#tab=…): ссылку на конкретный чек-лист
 * можно прислать коллеге, а «назад» возвращает туда, где человек был, а не
 * на первую вкладку.
 */
(function () {
  "use strict";

  var PREFIX = "#tab=";

  function panels(box) {
    // только прямые дети: вложенные панели внутри вкладки своими не считаем
    return Array.prototype.filter.call(box.children, function (node) {
      return node.hasAttribute && node.hasAttribute("data-tab");
    });
  }

  function build(box) {
    var found = panels(box);
    // одна панель — полоска вкладок ничего не добавляет, только шумит
    if (found.length < 2) { return; }

    var bar = document.createElement("div");
    bar.className = "tabs__bar";
    bar.setAttribute("role", "tablist");

    var buttons = found.map(function (panel, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "tabs__btn";
      button.setAttribute("role", "tab");
      button.textContent = panel.getAttribute("data-tab");

      var note = panel.getAttribute("data-tab-note");
      if (note) {
        var badge = document.createElement("span");
        badge.className = "tabs__note";
        badge.textContent = note;
        button.appendChild(badge);
      }

      button.addEventListener("click", function () { show(index, true); });
      bar.appendChild(button);
      return button;
    });

    function show(index, remember) {
      found.forEach(function (panel, i) {
        panel.hidden = i !== index;
        buttons[i].classList.toggle("is-active", i === index);
        buttons[i].setAttribute("aria-selected", i === index ? "true" : "false");
        // невыбранные вкладки убираем из обхода табом: иначе клавиатура
        // проваливается в спрятанное
        buttons[i].tabIndex = i === index ? 0 : -1;
      });
      if (remember) {
        var name = found[index].getAttribute("data-tab");
        history.replaceState(null, "", PREFIX + encodeURIComponent(name));
      }
    }

    // стрелками между вкладками — так ведут себя вкладки везде
    bar.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowRight" ? 1
               : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) { return; }
      event.preventDefault();
      var current = buttons.indexOf(document.activeElement);
      var next = (current + step + buttons.length) % buttons.length;
      buttons[next].focus();
      show(next, true);
    });

    box.insertBefore(bar, found[0]);

    var wanted = 0;
    if (location.hash.indexOf(PREFIX) === 0) {
      var asked = decodeURIComponent(location.hash.slice(PREFIX.length));
      found.forEach(function (panel, index) {
        if (panel.getAttribute("data-tab") === asked) { wanted = index; }
      });
    }
    show(wanted, false);
  }

  document.querySelectorAll("[data-tabs]").forEach(build);
})();
