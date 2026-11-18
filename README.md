# Keitaro Wrapper

Обёртка над [Keitaro](https://keitaro.io) Admin API из двух частей:

1. **Создаватор кампаний.** Принимает название, гео (несколько стран) и оффер с автокомплитом. Создаёт кампанию с доменом, группой и источником и двумя потоками:
   - **поток 1**: всех из указанных стран редиректит на Google;
   - **поток 2**: всех остальных отправляет на выбранный оффер.
2. **Редактор существующей кампании** повторяет логику из видео к ТЗ: офферы можно добавлять, удалять и возвращать, веса закреплять (pin), изменения копятся как черновик и публикуются кнопкой «Push to Keitaro».

**Стек:** FastAPI, SQLAlchemy 2 (async), Alembic, httpx, Pydantic v2 · React 19, TypeScript, Vite, TanStack Query · pytest, respx, Hypothesis, Vitest, Testing Library · uv, ruff, mypy (strict), oxlint · Docker · GitHub Actions.

---

## Быстрый старт

Нужны **Python 3.12+** с [uv](https://docs.astral.sh/uv/) и **Node.js 20+**.

```bash
git clone https://github.com/mra12nayhctrkm/keitaro-wrapper.git
cd keitaro-wrapper
cp .env.example .env        # впишите KEITARO_API_KEY
make install                # uv sync + npm ci
make start                  # миграции, сборка фронта, сервер
```

Откройте http://localhost:8000. API-документация (Swagger) — http://localhost:8000/docs.

**Ключ API.** В админке Keitaro: «Обслуживание → Пользователи → API-ключи» (или в профиле) → создать ключ и вставить его в `.env` как `KEITARO_API_KEY`. Файл `.env` в git не попадает.

### Через Docker

```bash
cp .env.example .env        # впишите KEITARO_API_KEY
docker compose up --build
```

Поднимаются два контейнера: приложение и **PostgreSQL 17**. Миграции применяются при старте приложения, данные лежат в томе `pgdata`.

### Режим разработки

```bash
make dev    # API на :8000 с авто-перезагрузкой + Vite на :5173 с hot reload
```

UI открывается на http://localhost:5173, запросы `/api` проксируются на бэкенд.

Без `make`:

```bash
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload --port 8000
# во втором терминале
cd frontend && npm ci && npm run dev
```

---

## Миграции

Схема БД управляется **Alembic** (`backend/migrations/`). Адрес базы берётся из `DATABASE_URL` (`.env`), по умолчанию это SQLite-файл `backend/keitaro_wrapper.db`.

```bash
cd backend
uv run alembic upgrade head                            # применить все миграции
uv run alembic downgrade -1                            # откатить последнюю
uv run alembic revision --autogenerate -m "описание"   # новая миграция после правки app/models.py
uv run alembic check                                   # модели и миграции совпадают?
```

PostgreSQL поддерживается из коробки (драйвер `asyncpg` уже в зависимостях): задайте `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`. `docker compose` делает это сам.

Тесты собирают схему через `alembic upgrade head`, как в продакшене, и проверяют, что модели не разошлись с миграциями.

---

## Как это работает

### Создание кампании

`POST /api/campaigns`:

1. Название получает префикс `CAMPAIGN_PREFIX` (`test_mkrtchyan_campaign1`), если его ещё нет.
2. Гео: `MX, au;RO` превращается в `["MX", "AU", "RO"]` с проверкой по ISO 3166-1, дубли убираются.
3. Оффер проверяется в Keitaro.
4. Домен, группа и источник выбираются в форме. По умолчанию из `.env` подставляются `in.posdk.xyz`, `FORTESTS`, `FORTESTS`, Keitaro ищет их по имени. Если такого нет, но в Keitaro доступен ровно один вариант, берётся он: тестовому пользователю виден только домен `kylovoa.com`.
5. В Keitaro создаётся кампания (`type: position`) и два потока:
   - `Geo AU, MX → Google`: фильтр `country accept [...]`, `schema: redirect` на `https://google.com`;
   - `Offers`: без фильтров, `schema: landings`, оффер с долей 100%.
6. **Всё или ничего.** Если поток не создался, кампания удаляется, чтобы в трекере не осталось полунастроенной кампании.

### Редактор

Логика повторяет видео из ТЗ.

| Действие | Что происходит |
|---|---|
| **Fetch streams from Keitaro** | потоки и офферы загружаются из Keitaro; потоки без офферов показываются, но не разбираются |
| **Add** | оффер добавляется как черновик, веса пересчитываются (4 оффера по 25%), поток желтеет |
| **Remove** | оффер сереет, его доля 0%, остальные пересчитываются |
| **Bring back** | удалённый оффер возвращается (черновик) |
| **📌 / клик по %** | вес закрепляется: при пересчёте он не меняется, остальные делят оставшееся |
| **Push to Keitaro** | черновик публикуется в Keitaro, поток снова белый |
| **Cancel** | черновик отменяется: добавленные офферы исчезают, удалённые возвращаются |

Удалённые офферы **остаются в архиве** обёртки (серые, с кнопкой «Bring back»). Это касается и офферов, которые удалили прямо в Keitaro: после следующего Fetch они станут серыми, а не пропадут.

**Модель данных.** У каждого оффера в потоке хранятся два состояния:

- **желаемое** (`state`, `share`) — то, что редактирует пользователь;
- **опубликованное** (`published_state`, `published_share`) — то, что сейчас в Keitaro.

Поток «грязный» (жёлтый), пока они различаются. Cancel возвращает желаемое к опубликованному. Push отправляет желаемое и делает его опубликованным. Fetch обновляет опубликованное и переносит его в желаемое только там, где нет черновика, поэтому несохранённые правки не теряются.

**Веса.** Доли в Keitaro целые, сумма 100%. Закреплённые доли не трогаются, остаток делится поровну между незакреплёнными, а остаток от деления по одному проценту получают первые: 100/3 → 34, 33, 33; закреплённые 25% и ещё два оффера → 38, 37 (`app/services/weights.py`). Невозможные комбинации, например закреплено больше 100%, отклоняются с понятной ошибкой.

**Выключенные офферы.** Если оффер в потоке выключен в Keitaro (`disabled`), Push сохраняет его выключенным и не включает его молча обратно.

**Защита от перезаписи.** Перед Push обёртка заново читает поток из Keitaro. Если его успели изменить в трекере после последнего Fetch, Push отклоняется (409) с просьбой обновить данные. Так обёртка не затрёт чужие правки.

---

### Журнал публикаций

Каждый Push записывается в журнал: кто опубликовал, когда, и какие офферы с какими долями были в Keitaro до и после. В карточке потока кнопка **History** показывает журнал, у каждой записи две кнопки:

- **Restore** загружает результат той публикации как черновик;
- **Undo** загружает состояние до неё.

И то, и другое публикуется обычным Push, так что прошлую версию можно сначала посмотреть.

### Доступ

Если в `.env` задан `APP_PASSWORD`, вся обёртка, кроме `/api/health`, закрывается HTTP Basic авторизацией: браузер сам спросит логин и пароль. Имя пользователя (`APP_USERNAME`) записывается в журнал публикаций. Пароль сравнивается за постоянное время, чтобы по времени ответа нельзя было подбирать его.

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/meta` | домены, группы, источники и значения по умолчанию для формы |
| GET | `/api/offers?q=` | поиск офферов по ID или названию (кэш 60 с) |
| GET | `/api/campaigns?q=` | кампании из Keitaro |
| POST | `/api/campaigns` | создать кампанию |
| GET | `/api/campaigns/{id}` | кампания из БД обёртки |
| POST | `/api/campaigns/{id}/fetch` | загрузить потоки из Keitaro |
| POST | `/api/streams/{id}/offers` | добавить оффер |
| POST | `/api/streams/{id}/push` | опубликовать |
| POST | `/api/streams/{id}/cancel` | отменить черновик |
| POST | `/api/stream-offers/{id}/remove` | удалить оффер |
| POST | `/api/stream-offers/{id}/bring-back` | вернуть оффер |
| PATCH | `/api/stream-offers/{id}` | `{"pinned": true}` или `{"share": 40}` (задать и закрепить) |
| GET | `/api/streams/{id}/history` | журнал публикаций, новые сверху |
| POST | `/api/streams/{id}/history/{log}/restore?version=after\|before` | вернуть версию (или отменить публикацию) как черновик |

Ошибки Keitaro превращаются в понятные ответы:
- 422, если Keitaro отклонил данные, например `Keitaro: name: Name has already used`;
- 502 при прочих ошибках, а при неверном ключе с подсказкой «check KEITARO_API_KEY»;
- 503, если Keitaro недоступен.

GET, PUT и DELETE к Keitaro повторяются при сетевых сбоях и 5xx с нарастающей паузой. POST не повторяется, чтобы не создать дубли.

---

## Тесты и проверки

```bash
make test     # backend (pytest) + frontend (vitest)
make check    # + ruff, mypy --strict, oxlint, tsc — то же, что в CI
```

- **Backend: 102 теста, покрытие 98%.** Каждый тест поднимает схему через `alembic upgrade head` и откатывает через `downgrade base`, так что обе стороны миграций проверяются постоянно. Keitaro подменяется фейком в памяти (`tests/fake_keitaro.py`), сценарий из видео пройден по шагам через HTTP API (`tests/test_editor.py`). HTTP-клиент проверяется отдельно через respx: заголовки, ошибки, повторы. Распределение весов дополнительно проверяется property-based тестами на Hypothesis: сумма всегда 100, закреплённые доли не меняются, разница между незакреплёнными не больше 1.
- **Frontend: 13 тестов на Vitest + Testing Library.** Кнопки шлют правильные запросы, ответ сразу попадает в кэш, ошибки показываются пользователю.
- **CI** (GitHub Actions): линтеры, типы, миграции, тесты бэкенда **на SQLite и на PostgreSQL**, тесты и сборка фронта, сборка Docker-образа.

Локально на PostgreSQL:

```bash
docker run -d --name kw-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres uv run pytest
```

### Проверка на настоящем Keitaro

На `tlgk.host` создана кампания `test_mkrtchyan_campaign2` (#214529) и проверена напрямую через API Keitaro:

- домен, группа и источник проставлены;
- поток 1 фильтрует `country accept [AU, MX]` и ведёт на Google;
- поток 2 без фильтров ведёт на оффер со 100%.

Сценарий редактора на ней проверен целиком: удаление и отмена, удаление и публикация (оффер пропал из Keitaro и остался в архиве), Fetch, возврат, закрепление и публикация.

## Структура

```
backend/
  app/
    main.py            фабрика приложения, обработка ошибок, раздача собранного фронта
    config.py          настройки из .env
    models.py          SQLAlchemy-модели: Campaign, Stream, StreamOffer
    keitaro/client.py  типизированный клиент Keitaro Admin API
    services/
      creator.py       создание кампании
      editor.py        черновики, push, синхронизация
      weights.py       распределение долей
      offers.py        каталог офферов с кэшем
    api/               роуты и зависимости FastAPI
  migrations/          Alembic
  tests/
frontend/src/
  pages/               список и создание кампаний, редактор
  components/          StreamCard, OfferSearch (автокомплит)
```

## Настройки (`.env`)

| Переменная | По умолчанию | |
|---|---|---|
| `KEITARO_URL` | `https://tlgk.host` | адрес трекера |
| `KEITARO_API_KEY` | — | ключ Admin API |
| `DATABASE_URL` | `sqlite+aiosqlite:///./keitaro_wrapper.db` | база обёртки |
| `CAMPAIGN_PREFIX` | `test_mkrtchyan_` | префикс названий кампаний |
| `DEFAULT_DOMAIN` / `DEFAULT_GROUP` / `DEFAULT_TRAFFIC_SOURCE` | `in.posdk.xyz` / `FORTESTS` / `FORTESTS` | что подставлять в форму |
| `GEO_REDIRECT_URL` | `https://google.com` | куда ведёт гео-поток |
| `APP_USERNAME` / `APP_PASSWORD` | `admin` / пусто | вход в обёртку (HTTP Basic); пустой пароль отключает вход |
