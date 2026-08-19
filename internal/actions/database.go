package actions

import (
	"context"

	"lasertracker_server/internal"

	"github.com/jackc/pgx/v5/pgxpool"
)

func initDBConn(cfg internal.Config) (*pgxpool.Pool, error) {
	conn, err := pgxpool.New(context.Background(), cfg.DatabaseURL)
	if err != nil {
		return nil, err
	}
	return conn, nil
}

func createTables(ctx context.Context, conn *pgxpool.Pool) error {
	myevilschema := `
	CREATE TABLE IF NOT EXISTS groups (
    	id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL UNIQUE,
        event_key TEXT NOT NULL,
        team_number INTEGER,
        group_key TEXT NOT NULL UNIQUE
    );

	CREATE TABLE IF NOT EXISTS members (
    	id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        pin_hash TEXT NOT NULL,
        job TEXT NOT NULL,
        role TEXT NOT NULL,
        location TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
        UNIQUE(group_id, username)
    );

	CREATE TABLE IF NOT EXISTS logs (
        group_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        timestamp INTEGER NOT NULL
	);

	CREATE TABLE IF NOT EXISTS batteries (
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        matches_used INTEGER NOT NULL,
        notes TEXT,
        status_timestamp INTEGER NOT NULL
    )
	`

	_, err := conn.Exec(ctx, myevilschema)
	return err
}
