package main

import (
	"log"
	"strconv"

	"lasertracker_server/internal"
)

func main() {
	cfg, err := internal.LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}
	log.Printf("%s", "Starting "+cfg.InstanceName+" on port "+strconv.Itoa(cfg.Port))

}
