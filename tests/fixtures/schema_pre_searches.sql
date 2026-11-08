CREATE TABLE job (
	id INTEGER NOT NULL, 
	source VARCHAR NOT NULL, 
	external_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	company VARCHAR NOT NULL, 
	location VARCHAR, 
	remote BOOLEAN NOT NULL, 
	url VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	salary_min INTEGER, 
	salary_max INTEGER, 
	salary_currency VARCHAR, 
	tags JSON NOT NULL, 
	posted_at DATETIME, 
	first_seen_at DATETIME NOT NULL, 
	last_seen_at DATETIME NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	content_hash VARCHAR NOT NULL, 
	fingerprint VARCHAR, 
	embedding BLOB, 
	raw JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_job_source_external_id UNIQUE (source, external_id)
);
CREATE INDEX ix_job_last_seen_at ON job (last_seen_at);
CREATE INDEX ix_job_external_id ON job (external_id);
CREATE INDEX ix_job_is_active ON job (is_active);
CREATE INDEX ix_job_source ON job (source);
CREATE INDEX ix_job_fingerprint ON job (fingerprint);
CREATE TABLE run (
	id INTEGER NOT NULL, 
	job VARCHAR NOT NULL, 
	user_id INTEGER, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	ok BOOLEAN NOT NULL, 
	error VARCHAR, 
	counters JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_run_job ON run (job);
CREATE INDEX ix_run_started_at ON run (started_at);
CREATE INDEX ix_run_user_id ON run (user_id);
CREATE TABLE user (
	id INTEGER NOT NULL, 
	email VARCHAR NOT NULL, 
	locale VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_user_email ON user (email);
CREATE TABLE "match" (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	similarity FLOAT NOT NULL, 
	score INTEGER, 
	reasoning VARCHAR, 
	matched_skills JSON NOT NULL, 
	missing_skills JSON NOT NULL, 
	red_flags JSON NOT NULL, 
	status VARCHAR NOT NULL, 
	llm_model VARCHAR, 
	notified_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_match_job_user UNIQUE (job_id, user_id), 
	FOREIGN KEY(job_id) REFERENCES job (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE INDEX ix_match_user_status ON "match" (user_id, status);
CREATE INDEX ix_match_job_id ON "match" (job_id);
CREATE INDEX ix_match_user_id ON "match" (user_id);
CREATE INDEX ix_match_notified_at ON "match" (notified_at);
CREATE INDEX ix_match_status ON "match" (status);
CREATE TABLE user_preferences (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	titles JSON NOT NULL, 
	seniority JSON NOT NULL, 
	work_modes JSON NOT NULL, 
	regions JSON NOT NULL, 
	excluded_regions JSON NOT NULL, 
	min_salary INTEGER, 
	salary_currency VARCHAR, 
	required_skills JSON NOT NULL, 
	nice_to_have_skills JSON NOT NULL, 
	excluded_keywords JSON NOT NULL, 
	profile_summary VARCHAR NOT NULL, 
	search_terms JSON NOT NULL, 
	profile_hash VARCHAR, 
	profile_embedding BLOB, 
	min_score_to_notify INTEGER NOT NULL, 
	notify_email VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE UNIQUE INDEX ix_user_preferences_user_id ON user_preferences (user_id);
