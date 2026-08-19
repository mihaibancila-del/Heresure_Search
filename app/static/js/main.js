// [EN] The "Send Email" button is still a stub — it only shows a toast.
// Loaded as a classic script (NOT type="module") because the button uses an
// inline onclick="notReady(this)", which resolves against the global scope.
// [RU] Кнопка "Отправить письмо" пока заглушка — только показывает toast.
// Подключается как обычный скрипт (НЕ type="module"), потому что кнопка
// использует инлайновый onclick="notReady(this)", который ищет функцию в
// глобальной области видимости.
function notReady(btn) {
  const toast = document.getElementById('toast');
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1500);
}

// [EN] Copies the one-time invite link next to the button. navigator.clipboard
// only exists in a secure context (https, or localhost), so on a plain-http
// server the select()+execCommand path is the one that actually runs — hence
// both. The link is also always selectable by hand, so a total failure here
// still leaves the admin able to copy it.
// [RU] Копирует одноразовую ссылку-приглашение, стоящую рядом с кнопкой.
// navigator.clipboard существует только в защищённом контексте (https или
// localhost), поэтому на сервере по обычному http реально срабатывает путь
// select()+execCommand — отсюда оба варианта. Ссылку всегда можно выделить
// вручную, поэтому даже полный сбой здесь не мешает админу её скопировать.
function copyInvite(btn) {
  const input = btn.parentElement.querySelector('input');
  if (!input) return;

  const done = () => {
    const original = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = original; }, 1500);
  };

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(input.value).then(done, () => fallbackCopy(input, done));
  } else {
    fallbackCopy(input, done);
  }
}

// [EN] While an import is running, reload the page periodically so the status and
// the log tail move without the user pressing anything. Driven by the
// data-import-active attribute the template renders, so there is no inline script
// and no polling on pages where nothing is happening.
// A full reload (not fetch/JSON) is deliberate: the page is server-rendered, so
// there is no second code path to keep in sync, and the request is cheap.
// [RU] Пока идёт импорт, периодически перезагружаем страницу, чтобы статус и хвост
// лога обновлялись без действий пользователя. Управляется атрибутом
// data-import-active, который отдаёт шаблон, — поэтому нет инлайнового скрипта и нет
// опроса на страницах, где ничего не происходит.
// Полная перезагрузка (а не fetch/JSON) выбрана намеренно: страница рендерится на
// сервере, поэтому не появляется второй путь исполнения, который надо
// синхронизировать, а сам запрос дешёвый.
const IMPORT_POLL_MS = 5000;

document.addEventListener('DOMContentLoaded', () => {
  const panel = document.querySelector('[data-import-active="1"]');
  if (panel) {
    setTimeout(() => window.location.reload(), IMPORT_POLL_MS);
  }
});

function fallbackCopy(input, done) {
  input.select();
  try {
    if (document.execCommand('copy')) done();
  } catch (e) {
    // [EN] Leave it selected — the admin can press Cmd/Ctrl+C.
    // [RU] Оставляем выделенным — админ нажмёт Cmd/Ctrl+C.
  }
}
