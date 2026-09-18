/* Просмотр снимка поверх страницы.
 *
 * Ссылка на файл остаётся ссылкой и без скрипта работает как работала:
 * браузер откроет картинку сам. Скрипт только перехватывает щелчок и
 * показывает её поверх карточки — чтобы посмотреть плату крупно и вернуться
 * к тому, на что смотрел, не уходя со страницы и не теряя прокрутку.
 *
 * Почему не <dialog>. Он умеет ровно это и сам, но `showModal()` забирает
 * фокус и рисует свой ::backdrop, который нечем затемнить плавно, а на
 * тёмной теме он отличается от наших поверхностей. Разница в коде — десяток
 * строк, поэтому слой свой.
 *
 * Закрывается тремя способами, и все три обязательны: Esc (клавиатура),
 * щелчок мимо снимка (мышь) и кнопка в углу (сенсорный экран, где «мимо»
 * попадается случайно и раздражает).
 */
(function () {
  "use strict";

  var CLOSE_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
    ' stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12"></path>' +
    '<path d="M18 6L6 18"></path></svg>';

  var layer = null;      // слой создаётся при первом открытии, а не заранее
  var picture = null;
  var caption = null;
  var opener = null;     // куда вернуть фокус после закрытия

  function build() {
    layer = document.createElement("div");
    layer.className = "lightbox";
    layer.hidden = true;
    // роль и подпись — чтобы экранный диктор объявил слой окном, а не
    // очередным куском страницы
    layer.setAttribute("role", "dialog");
    layer.setAttribute("aria-modal", "true");
    layer.setAttribute("aria-label", "Просмотр изображения");

    layer.innerHTML =
      '<button type="button" class="lightbox__close" aria-label="Закрыть">' +
      CLOSE_ICON + "</button>" +
      '<figure class="lightbox__frame">' +
      '<img class="lightbox__image" alt="">' +
      '<figcaption class="lightbox__caption"></figcaption>' +
      "</figure>";

    picture = layer.querySelector(".lightbox__image");
    caption = layer.querySelector(".lightbox__caption");

    layer.querySelector(".lightbox__close").addEventListener("click", close);

    // щелчок мимо снимка закрывает; по самому снимку — нет, иначе
    // промахнуться мышью по краю картинки значит потерять её
    layer.addEventListener("mousedown", function (event) {
      if (event.target === layer) { close(); }
    });

    document.body.appendChild(layer);
  }

  function open(link) {
    if (!layer) { build(); }

    var image = link.querySelector("img");
    var label = image ? image.getAttribute("alt") || "" : "";

    opener = link;
    picture.src = link.getAttribute("href");
    picture.alt = label;
    caption.textContent = label;
    caption.hidden = !label;

    layer.hidden = false;
    // страница под слоем не должна прокручиваться: иначе колесо мыши
    // уводит карточку, а видно всё равно только снимок
    document.body.classList.add("lightbox-open");
    layer.querySelector(".lightbox__close").focus();
  }

  function close() {
    if (!layer || layer.hidden) { return; }
    layer.hidden = true;
    document.body.classList.remove("lightbox-open");
    // снимок отпускаем: большой файл незачем держать в памяти после закрытия
    picture.removeAttribute("src");
    if (opener) { opener.focus(); opener = null; }
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a.shot__link");
    if (!link) { return; }
    // средняя кнопка, Ctrl и Cmd — это «открой отдельно», и мешать
    // человеку так делать нельзя
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    open(link);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { close(); }
  });
})();
