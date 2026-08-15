package config

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	InstanceName string `json:"instance_name"`
	Version      string `json:"version"`
	DatabaseURL  string `json:"database_url"`
	Port         int    `json:"port"`
	TBAAPIKey    string `json:"tba_api_key"`
	JWTSecret    string `json:"jwt_secret"`
	IsTesting    bool   `json:"is_testing"`
}

func LoadConfig() (*Config, error) {
	if _, err := os.Stat("config.json"); os.IsNotExist(err) {
		if err := FirstRunSetup(); err != nil {
			fmt.Println("Error in setup: %w ", err)
		}
	}

	file, err := os.Open("config.json")
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var cfg Config
	if err := json.NewDecoder(file).Decode(&cfg); err != nil {
		return nil, err
	}

	return &cfg, nil
}

func FirstRunSetup() error {
	reader := bufio.NewReader(os.Stdin)

	fmt.Println("\n===First Run Setup===")
	fmt.Print("Instance name (e.g. Team 2077 Laser Tracker Server): ")
	instName, _ := reader.ReadString('\n')

	fmt.Print("DB Connection URI (e.g. postgres://username:password@localhost:portnum/lasertracker?sslmode=disable): ")
	dbURL, _ := reader.ReadString('\n')

	fmt.Print("Port to use (leave blank for default, 2077): ")
	portStr, _ := reader.ReadString('\n')
	port := 2077
	if portStr != "" {
		p, err := strconv.Atoi(portStr)
		if err != nil {
			fmt.Println("Invalid port entered. Using default (2077).")
		} else {
			port = p
		}
	}

	fmt.Print("The Blue Alliance APIv3 key: ")
	tbaKey, _ := reader.ReadString('\n')

	fmt.Print("JWT Secret (leave blank to auto-generate): ")
	jwtSecret, _ := reader.ReadString('\n')
	jwtSecret = strings.TrimSpace(jwtSecret)
	if jwtSecret == "" {
		s, err := GenerateRandomSecret(32)
		if err != nil {
			fmt.Println(err)
			os.Exit(1)
		} else {
			jwtSecret = s
		}
	}

	cfg := Config{
		InstanceName: strings.TrimSpace(instName),
		Version:      "26.8",
		DatabaseURL:  strings.TrimSpace(dbURL),
		Port:         port,
		TBAAPIKey:    strings.TrimSpace(tbaKey),
		JWTSecret:    jwtSecret,
		IsTesting:    false,
	}

	file, err := os.Create("config.json")
	if err != nil {
		return err
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	return encoder.Encode(cfg)
}

func GenerateRandomSecret(length int) (string, error) {
	bytes := make([]byte, length)

	_, err := rand.Read(bytes)
	if err != nil {
		return "", fmt.Errorf("failed to generate random secret: %w", err)
	}

	return hex.EncodeToString(bytes), nil
}
