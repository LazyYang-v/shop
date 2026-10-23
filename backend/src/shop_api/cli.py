import argparse
import getpass
import os

from pwdlib import PasswordHash
from sqlalchemy import delete, select

from shop_api.database import make_session_factory
from shop_api.identity import AuthSession, Role, User, now_utc


def create_admin(database_url: str, email: str, password: str) -> None:
    normalized_email = email.strip().lower()
    factory = make_session_factory(database_url)
    with factory.begin() as session:
        existing = session.scalar(select(User).where(User.email == normalized_email))
        hashed = PasswordHash.recommended().hash(password)
        if existing:
            existing.password_hash = hashed
            existing.role = Role.ADMIN.value
            existing.is_active = True
        else:
            session.add(
                User(
                    email=normalized_email,
                    password_hash=hashed,
                    role=Role.ADMIN.value,
                    is_active=True,
                    created_at=now_utc(),
                )
            )
    factory.kw["bind"].dispose()


def cleanup_expired_sessions(database_url: str) -> int:
    factory = make_session_factory(database_url)
    with factory.begin() as session:
        deleted = len(session.scalars(delete(AuthSession).where(AuthSession.expires_at <= now_utc()).returning(AuthSession.id)).all())
    factory.kw["bind"].dispose()
    return deleted


def prepare_demo_addresses(database_url: str) -> int:
    from sqlalchemy.engine import make_url
    from shop_api.addresses import Address

    url = make_url(database_url)
    if url.database != "shop_dev" or url.host not in {"localhost", "127.0.0.1", "db"}:
        raise ValueError("Demo addresses may only be prepared in the local shop_dev database")
    factory = make_session_factory(database_url)
    created = 0
    try:
        with factory.begin() as session:
            buyers = session.scalars(select(User).where(User.role == Role.BUYER.value, User.is_active.is_(True)).order_by(User.id).with_for_update()).all()
            for user in buyers:
                if session.scalar(select(Address.id).where(Address.user_id == user.id)) is not None:
                    continue
                session.add(Address(user_id=user.id, recipient_name="演示收件人", phone="13800138000", province="浙江省", city="杭州市", district="西湖区", detail="文三路 1 号（虚构演示地址）", is_default=True))
                created += 1
    finally:
        factory.kw["bind"].dispose()
    return created


def seed_demo_products(database_url: str) -> int:
    from sqlalchemy.engine import make_url
    from shop_api.demo_catalog import seed_demo_catalog

    url = make_url(database_url)
    if url.database != "shop_dev" or url.host not in {"localhost", "127.0.0.1", "db"}:
        raise ValueError("Demo products may only be created in the local shop_dev database")
    factory = make_session_factory(database_url)
    try:
        with factory.begin() as session:
            admin_id = session.scalar(select(User.id).where(User.role == Role.ADMIN.value, User.is_active.is_(True)).order_by(User.id).limit(1))
            if admin_id is None:
                raise ValueError("An active administrator is required to audit demo inventory")
            return seed_demo_catalog(session, admin_id)
    finally:
        factory.kw["bind"].dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="shop-api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("cleanup-expired-sessions")
    subparsers.add_parser("prepare-demo-addresses")
    subparsers.add_parser("seed-demo-products")
    demo_parser = subparsers.add_parser("initialize-customer-service-demo")
    demo_parser.add_argument("--fixture", required=True)
    demo_parser.add_argument("--fixture-sha256", required=True)
    demo_parser.add_argument("--secrets-file", required=True)
    demo_parser.add_argument("--allow-migration-seed", action="store_true")
    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("--email", required=True)
    arguments = parser.parse_args()

    database_url = os.getenv("SHOP_DATABASE_URL")
    if not database_url:
        parser.error("SHOP_DATABASE_URL must be configured")
    if arguments.command == "initialize-customer-service-demo":
        from shop_api.customer_service_demo import initialize_customer_service_demo, read_demo_passwords

        try:
            count = initialize_customer_service_demo(
                database_url, arguments.fixture, arguments.fixture_sha256,
                read_demo_passwords(arguments.secrets_file),
                allow_migration_seed=arguments.allow_migration_seed,
            )
        except Exception:
            # Neither connection errors nor validation errors may expose credentials.
            parser.exit(1, "Demo initialization refused or failed; no partial fixture was committed.\n")
        print(f"Initialized fictional customer-service demo with {count} products and 3 identities")
    elif arguments.command == "cleanup-expired-sessions":
        print(f"Deleted {cleanup_expired_sessions(database_url)} expired sessions")
    elif arguments.command == "prepare-demo-addresses":
        print(f"Prepared {prepare_demo_addresses(database_url)} fictional demo addresses")
    elif arguments.command == "seed-demo-products":
        print(f"Added {seed_demo_products(database_url)} fictional demo products")
    elif arguments.command == "create-admin":
        password = getpass.getpass("New admin password (12+ characters): ")
        if len(password) < 12:
            parser.error("Admin password must contain at least 12 characters")
        create_admin(database_url, arguments.email, password)
        print("Administrator account created or updated")


if __name__ == "__main__":
    main()
