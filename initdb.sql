CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    group_name TEXT NOT NULL UNIQUE,
    event_key TEXT NOT NULL,
    team_number INTEGER,
    group_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
    id SERIAL PRIMARY KEY,
    group_id INT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    job TEXT NOT NULL DEFAULT 'Unknown',
    role TEXT NOT NULL DEFAULT 'Unknown',
    location TEXT NOT NULL DEFAULT 'Unknown',
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_group
        FOREIGN KEY(group_id) 
        REFERENCES groups(id) 
        ON DELETE CASCADE,
        
    UNIQUE(group_id, username)
);

CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    group_key TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_groups_group_key ON groups(group_key);
CREATE INDEX idx_members_group_user ON members(group_id, username);
CREATE INDEX idx_logs_group_key ON logs(group_key);