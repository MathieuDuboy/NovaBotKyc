"""
Seed MySQL — sandbox ISOLÉ du bot Interlace (infra nova_il, port 3307).

Crée les tables attendues par le code (noms de colonnes exacts, fautes d'origine
comprises) + la table **interlace_accounts** qui porte, par utilisateur Telegram,
son SOUS-COMPTE Interlace (sub-merchant) et son état KYC (flux consumer/gateway).

Injecte un code de parrainage de test + des adresses pool factices.
Idempotent. Usage : ./venv/bin/python config/seed_sandbox.py
"""

import pymysql

# Infra nova_kyc (bot KYC) — distincte de nova_sbx (3306) et nova_il (3307)
DB = dict(
    host="localhost", port=3308,
    user="nova_user", password="SFdsfg2345-dsfsa342",
    database="nova", charset="utf8mb4",
)

TEST_REFERRAL = {
    "code": "SANDBOX",
    "deposit_fee": 2.5,
    "foreign_fee": 2.5,
    "name": "Sandbox Test Code",
    "valid": 1,
}

FAKE_POOL_ADDRESSES = [
    "TSandboxFakeAddr0000000000000000001",
    "TSandboxFakeAddr0000000000000000002",
    "TSandboxFakeAddr0000000000000000003",
    "TSandboxFakeAddr0000000000000000004",
    "TSandboxFakeAddr0000000000000000005",
]

DDL = [
    # --- referralcodes : noms de colonnes EXACTS lus par le code ---
    """
    CREATE TABLE IF NOT EXISTS referralcodes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        `referal code` VARCHAR(64) UNIQUE,
        `deposit fee`  DECIMAL(10,4),
        `foregin fee`  DECIMAL(10,4),
        `name`         VARCHAR(128),
        `valid`        TINYINT DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # --- pool : adresses de dépôt disponibles ---
    """
    CREATE TABLE IF NOT EXISTS pool (
        id INT AUTO_INCREMENT PRIMARY KEY,
        `nova_address` VARCHAR(128) UNIQUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # --- users : 13 colonnes exactes écrites par add_user_to_db ---
    """
    CREATE TABLE IF NOT EXISTS users (
        `USER_ID`               BIGINT,
        `USERNAME`              VARCHAR(255),
        `CREATION DATE`         DATETIME,
        `CARD NAME`             VARCHAR(255),
        `CARD SURNAME`          VARCHAR(255),
        `EMAIL`                 VARCHAR(255),
        `TELEPHONE`             VARCHAR(64),
        `REFERRAL CODE`         VARCHAR(64),
        `Telegram FirstName`    VARCHAR(255),
        `Telegram LastName`     VARCHAR(255),
        `Telegram LANGUAGE_CODE` VARCHAR(16),
        `CARD ID`               VARCHAR(255),
        `nova_address`          VARCHAR(128),
        KEY idx_user_id (`USER_ID`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # --- interlace_accounts : 1 utilisateur Telegram -> 1 sous-compte Interlace
    # (sub-merchant) + son état KYC. Le `account_id` est le sous-compte créé via
    # /accounts/register ; il sert AUSSI à router le webhook (account_id -> user).
    """
    CREATE TABLE IF NOT EXISTS interlace_accounts (
        `id`            BIGINT AUTO_INCREMENT PRIMARY KEY,
        `USER_ID`       BIGINT NULL,               -- chat_id Telegram (NULL = enrollment admin non réclamé)
        `created_by`    BIGINT NULL,               -- admin créateur (enrollments en masse)
        `account_id`    VARCHAR(64),               -- sous-compte Interlace (sub-merchant)
        `cardholder_id` VARCHAR(64),
        `card_id`       VARCHAR(64),               -- id carte Interlace
        `card_number`   VARCHAR(32),               -- PAN (si dispo)
        `bin`           VARCHAR(32),
        `kyc_status`    VARCHAR(24) DEFAULT 'NONE',-- NONE/PENDING/PASSED/REJECTED
        `kyc_case_id`   VARCHAR(64),
        `profile_json`  TEXT,                      -- profil mini app (pour créer le cardholder après PASS)
        `handoff_token` VARCHAR(64),               -- token unique du lien vers Bot B (utilisation carte)
        `created_at`    DATETIME,
        `updated_at`    DATETIME,
        UNIQUE KEY uq_ia_user (`USER_ID`),
        KEY idx_ia_account (`account_id`),
        KEY idx_ia_cardholder (`cardholder_id`),
        KEY idx_ia_card (`card_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def main():
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)
            # migrations idempotentes (multi-enrollment admin) : USER_ID nullable
            # + colonne created_by.
            for alter in (
                "ALTER TABLE interlace_accounts MODIFY `USER_ID` BIGINT NULL",
                "ALTER TABLE interlace_accounts ADD COLUMN `created_by` BIGINT NULL",
            ):
                try:
                    cur.execute(alter)
                except Exception:
                    pass
            cur.execute(
                "INSERT IGNORE INTO referralcodes "
                "(`referal code`, `deposit fee`, `foregin fee`, `name`, `valid`) "
                "VALUES (%s, %s, %s, %s, %s)",
                (TEST_REFERRAL["code"], TEST_REFERRAL["deposit_fee"],
                 TEST_REFERRAL["foreign_fee"], TEST_REFERRAL["name"],
                 TEST_REFERRAL["valid"]),
            )
            for addr in FAKE_POOL_ADDRESSES:
                cur.execute(
                    "INSERT IGNORE INTO pool (`nova_address`) VALUES (%s)", (addr,))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM referralcodes WHERE valid=1")
            n_ref = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pool")
            n_pool = cur.fetchone()[0]
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]

        print("✅ Seed sandbox KYC (nova_kyc:3308) terminé.")
        print(f"   Tables        : {', '.join(tables)}")
        print(f"   Codes valides : {n_ref} (code de test: '{TEST_REFERRAL['code']}')")
        print(f"   Adresses pool : {n_pool}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
