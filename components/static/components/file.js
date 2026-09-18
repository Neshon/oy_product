/* Выбор файла.
 *
 * Родное поле <input type="file"> оформить нельзя: кнопку и надпись
 * «Файл не выбран» рисует сам браузер, в каждом по-своему, и ни шрифт, ни
 * цвета к ним не применяются. Поэтому поле прячется, а рядом ставится
 * обычная кнопка и строка с именами выбранных файлов.
 *
 * Само поле остаётся в форме и остаётся источником файлов: оно
 * отправляется, его же проверяет Django. Без скрипта на странице остаётся
 * обычное системное поле — некрасивое, но рабочее.
 *
 * Заодно работает перетаскивание: BOM-файлы приходят пачкой, и вытащить их
 * из папки мышью быстрее, чем отмечать в системном диалоге.
 */
(function () {
  "use strict";

  var UPLOAD_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    ' class="filepick__icon"><path d="M12 15V3"></path><path d="M7 8l5-5 5 5"></path>' +
    '<path d="M4 15v4a1 1 0 001 1h14a1 1 0 001-1v-4"></path></svg>';

  function plural(count, one, few, many) {
    var tail = count % 100;
    if (tail >= 11 && tail <= 14) { return many; }
    tail = count % 10;
    if (tail === 1) { return one; }
    if (tail >= 2 && tail <= 4) { return few; }
    return many;
  }

  function only(file) {
    // в поле без multiple кладём один файл: перетащить могли несколько
    var carrier = new DataTransfer();
    carrier.items.add(file);
    return carrier.files;
  }

  function enhance(input) {
    if (input.dataset.filepick) { return; }
    input.dataset.filepick = "1";

    var many = input.multiple;
    var box = document.createElement("div");
    box.className = "filepick";
    input.parentNode.insertBefore(box, input);
    box.appendChild(input);
    input.classList.add("filepick__input");

    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn filepick__btn";
    button.innerHTML = UPLOAD_ICON + "<span>"
      + (many ? "Выбрать файлы" : "Выбрать файл") + "</span>";

    var name = document.createElement("span");
    name.className = "filepick__name";

    box.appendChild(button);
    box.appendChild(name);

    function show() {
      var files = input.files;
      if (!files || !files.length) {
        name.className = "filepick__name is-empty";
        name.textContent = many ? "или перетащите файлы сюда"
                                : "или перетащите файл сюда";
        name.removeAttribute("title");
        return;
      }
      name.className = "filepick__name";
      if (files.length === 1) {
        name.textContent = files[0].name;
      } else {
        name.textContent = files.length + " "
          + plural(files.length, "файл", "файла", "файлов");
      }
      // полный список — в подсказке: имена длинные, в строку не влезают
      name.title = Array.prototype.map.call(files, function (file) {
        return file.name;
      }).join(", ");
    }

    button.addEventListener("click", function () { input.click(); });
    input.addEventListener("change", show);

    // рамка подсвечивается, пока файл держат над полем
    ["dragenter", "dragover"].forEach(function (kind) {
      box.addEventListener(kind, function (event) {
        event.preventDefault();
        box.classList.add("is-over");
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (kind) {
      box.addEventListener(kind, function () {
        box.classList.remove("is-over");
      });
    });

    box.addEventListener("drop", function (event) {
      var dropped = event.dataTransfer && event.dataTransfer.files;
      if (!dropped || !dropped.length) { return; }
      event.preventDefault();
      try {
        input.files = many ? dropped : only(dropped[0]);
      } catch (error) {
        // старый браузер не даёт присвоить files — остаётся кнопка
        return;
      }
      show();
      input.dispatchEvent(new Event("change", {bubbles: true}));
    });

    show();
  }

  function guard() {
    // Файл, брошенный мимо поля, браузер открывает вместо страницы — и
    // человек вылетает из наполовину заполненной формы. Гасим это только
    // на страницах, где есть куда бросать, и только для самих файлов:
    // перетаскивание текста и ссылок пусть работает как обычно.
    ["dragover", "drop"].forEach(function (kind) {
      document.addEventListener(kind, function (event) {
        var types = event.dataTransfer && event.dataTransfer.types;
        if (!types || Array.prototype.indexOf.call(types, "Files") === -1) {
          return;
        }
        if (event.target.closest && event.target.closest(".filepick")) {
          return;
        }
        event.preventDefault();
      });
    });
  }

  function start() {
    var inputs = document.querySelectorAll('input[type="file"]');
    if (!inputs.length) { return; }
    inputs.forEach(enhance);
    guard();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
