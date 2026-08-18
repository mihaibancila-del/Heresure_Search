-- [EN] Application users. Access is invite-only: there is no signup route, so a
-- row here is the ONLY way into the site. An invite and a user are the same
-- row — a pending invite is simply a user with no password_hash yet. That keeps
-- "cannot self-register" true by construction: no row, no access.
--
-- Apply to an existing database (compose initdb only runs on a fresh volume):
--     psql -h localhost -p 5434 -U postgres -d Agents_Heresure -f sql/create_users_table.sql
--
-- [RU] Пользователи приложения. Доступ только по приглашению: маршрута
-- регистрации нет, поэтому строка здесь — ЕДИНСТВЕННЫЙ способ попасть на сайт.
-- Приглашение и пользователь — это одна и та же строка: ожидающее приглашение
-- это просто пользователь, у которого ещё нет password_hash. Благодаря этому
-- "нельзя зарегистрироваться самому" верно по построению: нет строки — нет доступа.
--
-- Применить к существующей базе (initdb в compose срабатывает только на пустом томе):
--     psql -h localhost -p 5434 -U postgres -d Agents_Heresure -f sql/create_users_table.sql

CREATE TABLE IF NOT EXISTS users (
    id                BIGSERIAL PRIMARY KEY,
    email             TEXT        NOT NULL,
    -- [EN] NULL until the invite is accepted. NULL means "cannot log in yet".
    -- [RU] NULL до принятия приглашения. NULL означает "войти пока нельзя".
    password_hash     TEXT,
    role              TEXT        NOT NULL DEFAULT 'member',
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    -- [EN] sha256 of the one-time invite token, never the token itself — same
    -- reasoning as password_hash. Cleared once the invite is used.
    -- [RU] sha256 одноразового токена приглашения, а не сам токен — по той же
    -- причине, что и password_hash. Очищается после использования приглашения.
    invite_token_hash TEXT,
    invite_expires_at TIMESTAMPTZ,
    invited_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at       TIMESTAMPTZ,
    last_login_at     TIMESTAMPTZ,
    CONSTRAINT users_role_check CHECK (role IN ('admin', 'member'))
);

-- [EN] Case-insensitive uniqueness: Alice@x.com and alice@x.com are one person.
-- Emails are stored lowercased by the application; the index enforces it even
-- if a row is inserted by hand.
-- [RU] Уникальность без учёта регистра: Alice@x.com и alice@x.com — один
-- человек. Приложение хранит email в нижнем регистре; индекс гарантирует это
-- даже при вставке строки вручную.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email));

-- [EN] Partial index — invite lookups only ever search live tokens, and used
-- invites (the majority over time) stay out of the index.
-- [RU] Частичный индекс — поиск по приглашению всегда идёт только по живым
-- токенам, а использованные приглашения (со временем большинство) в индекс не попадают.
CREATE INDEX IF NOT EXISTS users_invite_token_hash_idx
    ON users (invite_token_hash) WHERE invite_token_hash IS NOT NULL;
