# VASUDHARE BOOKSTORE ERP - Database

- template/bookstore_erp.db: clean database template
- clients/demo_01/bookstore_erp.db: isolated Demo 1 database
- clients/demo_02/bookstore_erp.db: isolated Demo 2 database
- schema.sql: initial database schema

Each customer will receive a separate database created from the template.
The application must validate the authenticated tenant and select only that
tenant's database for every request. SQLite foreign keys must be enabled on
every database connection. Never put production customer data in demo databases.
