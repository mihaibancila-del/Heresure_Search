"""
[EN]
Starting background work from a request.

An import takes minutes and downloads ~330MB, so it cannot run inside the
request. It is started as a DETACHED SUBPROCESS rather than a thread for two
reasons:

  1. AGENTS.md §2 — the web app must not import scripts/. Spawning a process is
     not importing, so the boundary holds; a thread would require the import.
  2. Gunicorn runs 2 workers and may restart them. A thread dies with its worker
     mid-download; a detached process (start_new_session=True) survives, and even
     survives a full app restart.

The child reports progress by writing to `import_runs`, which is why nothing here
needs to capture its output — the history page reads the database instead.

[RU]
Запуск фоновой работы из запроса.

Импорт занимает минуты и скачивает ~330MB, поэтому он не может выполняться внутри
запроса. Он запускается ОТСОЕДИНЁННЫМ ПОДПРОЦЕССОМ, а не потоком, по двум причинам:

  1. AGENTS.md §2 — веб-приложение не должно импортировать scripts/. Запуск
     процесса — не импорт, поэтому граница сохраняется; поток потребовал бы импорта.
  2. Gunicorn запускает 2 воркера и может их перезапускать. Поток умрёт вместе со
     своим воркером посреди загрузки; отсоединённый процесс (start_new_session=True)
     выживет, и выживет даже при полном перезапуске приложения.

Дочерний процесс сообщает о прогрессе записью в `import_runs` — поэтому здесь не
нужно перехватывать его вывод: страница истории читает базу.
"""

import subprocess
import sys

from app.config import PROJECT_ROOT


def start_import(run_id: int, trigger: str, started_by: str | None) -> None:
    """[EN] Launches scripts/run_import.py for an already-created run row.

    sys.executable is this interpreter — under gunicorn that is the venv's python,
    so the child gets the same dependencies without hardcoding a path. cwd is the
    project root because `-m scripts.run_import` only resolves from there
    (AGENTS.md §1).

    Output goes to DEVNULL on purpose: the child writes its progress into the
    database, and an unread PIPE would fill its buffer and block the import
    part-way through.

    [RU] Запускает scripts/run_import.py для уже созданной строки запуска.

    sys.executable — это текущий интерпретатор; под gunicorn это python из venv,
    поэтому дочерний процесс получает те же зависимости без жёстко прописанного
    пути. cwd — корень проекта, потому что `-m scripts.run_import` разрешается
    только оттуда (AGENTS.md §1).

    Вывод намеренно уходит в DEVNULL: дочерний процесс пишет прогресс в базу, а
    непрочитанный PIPE переполнил бы буфер и заблокировал импорт на середине."""
    command = [
        sys.executable, "-m", "scripts.run_import",
        "--trigger", trigger,
        "--run-id", str(run_id),
    ]
    if started_by:
        command += ["--started-by", started_by]

    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # [EN] Detach from the worker's process group so a gunicorn reload or a
        # Ctrl-C in the dev server does not take the import down with it.
        # [RU] Отсоединяем от группы процессов воркера, чтобы перезагрузка gunicorn
        # или Ctrl-C в dev-сервере не утащили импорт за собой.
        start_new_session=True,
    )
