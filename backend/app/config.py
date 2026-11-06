from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_ROOT = PROJECT_ROOT / "database"
TENANT_DATABASES = {
    "DEMO-01": DATABASE_ROOT / "clients/demo_01/bookstore_erp.db",
    "DEMO-02": DATABASE_ROOT / "clients/demo_02/bookstore_erp.db",
}
TEMPLATE_DATABASE = DATABASE_ROOT / "template/bookstore_erp.db"
APP_NAME = "VASUDHARE BOOKSTORE ERP"
APP_VERSION = "0.1.0"
