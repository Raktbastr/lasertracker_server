package internal

import "time"

type Group struct {
	ID         int
	GroupName  string
	EventKey   string
	TeamNumber int
	GroupKey   string
}

type Member struct {
	ID          int
	GroupID     int
	Username    string
	DisplayName string
	PinHash     string
	Job         string
	Role        string
	Location    string
	IsAdmin     bool
}

type LogEntry struct {
	GroupID   int
	Username  string
	Action    string
	Timestamp time.Time
}

type Battery struct {
	GroupID     int
	Name        string
	Status      string
	MatchesUsed int
	Notes       string
	Timestamp   time.Time
}
