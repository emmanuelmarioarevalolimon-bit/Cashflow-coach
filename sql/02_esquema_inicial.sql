-- COMPRIA v4 · esquema inicial (compilado por SQLAlchemy).
-- NO ejecutado contra una instancia SQL Server durante la preparación.
-- Ejecutar con administrador en una BASE NUEVA, antes del usuario de aplicación.
USE [C1Tesoreria];
GO
IF OBJECT_ID(N'dbo.companies', N'U') IS NULL
BEGIN
CREATE TABLE companies (
	id VARCHAR(36) NOT NULL, 
	name NVARCHAR(160) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
END;
GO
IF OBJECT_ID(N'dbo.schema_versions', N'U') IS NULL
BEGIN
CREATE TABLE schema_versions (
	version INTEGER NOT NULL, 
	PRIMARY KEY (version)
);
END;
GO
IF OBJECT_ID(N'dbo.app_users', N'U') IS NULL
BEGIN
CREATE TABLE app_users (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	UNIQUE (email)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_app_users_company_id' AND object_id=OBJECT_ID(N'dbo.app_users'))
CREATE INDEX ix_app_users_company_id ON app_users (company_id);
GO
IF OBJECT_ID(N'dbo.analysis_runs', N'U') IS NULL
BEGIN
CREATE TABLE analysis_runs (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	name NVARCHAR(160) NOT NULL, 
	input_json NVARCHAR(max) NOT NULL, 
	result_json NVARCHAR(max) NOT NULL, 
	sources_json NVARCHAR(max) NOT NULL, 
	engine_version VARCHAR(60) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_analysis_runs_company_id' AND object_id=OBJECT_ID(N'dbo.analysis_runs'))
CREATE INDEX ix_analysis_runs_company_id ON analysis_runs (company_id);
GO
IF OBJECT_ID(N'dbo.audit_events', N'U') IS NULL
BEGIN
CREATE TABLE audit_events (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	target VARCHAR(80) NOT NULL, 
	details_json NVARCHAR(max) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_audit_events_company_id' AND object_id=OBJECT_ID(N'dbo.audit_events'))
CREATE INDEX ix_audit_events_company_id ON audit_events (company_id);
GO
IF OBJECT_ID(N'dbo.documents', N'U') IS NULL
BEGIN
CREATE TABLE documents (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	name NVARCHAR(180) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	extension VARCHAR(12) NOT NULL, 
	content VARBINARY(max) NOT NULL, 
	extraction_json NVARCHAR(max) NOT NULL, 
	proposal_json NVARCHAR(max) NULL, 
	confirmed_json NVARCHAR(max) NULL, 
	state VARCHAR(20) NOT NULL, 
	revision INTEGER NOT NULL, 
	ai_model VARCHAR(100) NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_documents_company_hash UNIQUE (company_id, sha256), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_documents_company_id' AND object_id=OBJECT_ID(N'dbo.documents'))
CREATE INDEX ix_documents_company_id ON documents (company_id);
GO
IF OBJECT_ID(N'dbo.financial_reports', N'U') IS NULL
BEGIN
CREATE TABLE financial_reports (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	content_json NVARCHAR(max) NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_financial_reports_company_id' AND object_id=OBJECT_ID(N'dbo.financial_reports'))
CREATE INDEX ix_financial_reports_company_id ON financial_reports (company_id);
GO
IF OBJECT_ID(N'dbo.login_sessions', N'U') IS NULL
BEGIN
CREATE TABLE login_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF OBJECT_ID(N'dbo.financial_metrics', N'U') IS NULL
BEGIN
CREATE TABLE financial_metrics (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	name NVARCHAR(120) NOT NULL, 
	period_start DATETIME NOT NULL, 
	period_end DATETIME NOT NULL, 
	value NUMERIC(19, 4) NOT NULL, 
	unit NVARCHAR(40) NOT NULL, 
	source_location NVARCHAR(160) NOT NULL, 
	source_quote NVARCHAR(max) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_financial_metrics_company_id' AND object_id=OBJECT_ID(N'dbo.financial_metrics'))
CREATE INDEX ix_financial_metrics_company_id ON financial_metrics (company_id);
GO
IF OBJECT_ID(N'dbo.ledger_entries', N'U') IS NULL
BEGIN
CREATE TABLE ledger_entries (
	id VARCHAR(36) NOT NULL, 
	company_id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	source_key VARCHAR(80) NOT NULL, 
	source_location NVARCHAR(160) NOT NULL, 
	source_quote NVARCHAR(max) NOT NULL, 
	reference NVARCHAR(120) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	event_date DATETIME NOT NULL, 
	counterparty NVARCHAR(120) NOT NULL, 
	amount NUMERIC(19, 4) NOT NULL, 
	direction VARCHAR(10) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	category NVARCHAR(80) NOT NULL, 
	confidence NUMERIC(8, 6) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ledger_positive CHECK (amount > 0), 
	CONSTRAINT ck_ledger_confidence CHECK (confidence >= 0 AND confidence <= 1), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	UNIQUE (source_key)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_ledger_entries_company_id' AND object_id=OBJECT_ID(N'dbo.ledger_entries'))
CREATE INDEX ix_ledger_entries_company_id ON ledger_entries (company_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_ledger_entries_event_date' AND object_id=OBJECT_ID(N'dbo.ledger_entries'))
CREATE INDEX ix_ledger_entries_event_date ON ledger_entries (event_date);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_ledger_entries_fingerprint' AND object_id=OBJECT_ID(N'dbo.ledger_entries'))
CREATE INDEX ix_ledger_entries_fingerprint ON ledger_entries (fingerprint);
GO
IF OBJECT_ID(N'dbo.product_catalog', N'U') IS NULL
BEGIN
CREATE TABLE product_catalog (
	id VARCHAR(36) NOT NULL,
	company_id VARCHAR(36) NOT NULL,
	user_id VARCHAR(36) NOT NULL,
	sku NVARCHAR(80) NOT NULL,
	name NVARCHAR(160) NOT NULL,
	supplier NVARCHAR(160) NOT NULL,
	stock_on_hand NUMERIC(19, 4) NOT NULL,
	average_daily_demand NUMERIC(19, 4) NOT NULL,
	unit_cost NUMERIC(19, 4) NOT NULL,
	lead_time_days INTEGER NOT NULL,
	incoming_units NUMERIC(19, 4) NOT NULL,
	safety_stock_units NUMERIC(19, 4) NOT NULL,
	minimum_order_units NUMERIC(19, 4) NOT NULL,
	order_multiple NUMERIC(19, 4) NOT NULL,
	unit_price NUMERIC(19, 4) NULL,
	payment_terms_days INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_product_catalog_company_sku UNIQUE (company_id, sku),
	FOREIGN KEY(company_id) REFERENCES companies (id),
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_product_catalog_company_id' AND object_id=OBJECT_ID(N'dbo.product_catalog'))
CREATE INDEX ix_product_catalog_company_id ON product_catalog (company_id);
GO
IF OBJECT_ID(N'dbo.product_stockout_reports', N'U') IS NULL
BEGIN
CREATE TABLE product_stockout_reports (
	id VARCHAR(36) NOT NULL,
	company_id VARCHAR(36) NOT NULL,
	product_id VARCHAR(36) NOT NULL,
	user_id VARCHAR(36) NOT NULL,
	occurred_on DATE NOT NULL,
	missing_units NUMERIC(19, 4) NOT NULL,
	note NVARCHAR(500) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_stockout_positive CHECK (missing_units > 0),
	FOREIGN KEY(company_id) REFERENCES companies (id),
	FOREIGN KEY(product_id) REFERENCES product_catalog (id),
	FOREIGN KEY(user_id) REFERENCES app_users (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_product_stockout_reports_company_id' AND object_id=OBJECT_ID(N'dbo.product_stockout_reports'))
CREATE INDEX ix_product_stockout_reports_company_id ON product_stockout_reports (company_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_product_stockout_reports_product_id' AND object_id=OBJECT_ID(N'dbo.product_stockout_reports'))
CREATE INDEX ix_product_stockout_reports_product_id ON product_stockout_reports (product_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_product_stockout_reports_occurred_on' AND object_id=OBJECT_ID(N'dbo.product_stockout_reports'))
CREATE INDEX ix_product_stockout_reports_occurred_on ON product_stockout_reports (occurred_on);
GO
IF OBJECT_ID(N'dbo.company_work_schedules', N'U') IS NULL
BEGIN
CREATE TABLE company_work_schedules (
	company_id VARCHAR(36) NOT NULL,
	working_weekdays VARCHAR(20) NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (company_id),
	FOREIGN KEY(company_id) REFERENCES companies (id)
);
END;
GO
IF OBJECT_ID(N'dbo.company_non_working_days', N'U') IS NULL
BEGIN
CREATE TABLE company_non_working_days (
	id VARCHAR(36) NOT NULL,
	company_id VARCHAR(36) NOT NULL,
	event_date DATE NOT NULL,
	label NVARCHAR(160) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_non_working_company_date UNIQUE (company_id, event_date),
	FOREIGN KEY(company_id) REFERENCES companies (id)
);
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_company_non_working_days_company_id' AND object_id=OBJECT_ID(N'dbo.company_non_working_days'))
CREATE INDEX ix_company_non_working_days_company_id ON company_non_working_days (company_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_company_non_working_days_event_date' AND object_id=OBJECT_ID(N'dbo.company_non_working_days'))
CREATE INDEX ix_company_non_working_days_event_date ON company_non_working_days (event_date);
GO
IF NOT EXISTS (SELECT 1 FROM dbo.schema_versions WHERE version = 1)
    INSERT INTO dbo.schema_versions (version) VALUES (1);
GO
