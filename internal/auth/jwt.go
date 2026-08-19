package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type Claims struct {
	UserID   int
	Username string
	GroupID  int
	GroupKey string
	IsAdmin  bool
	jwt.RegisteredClaims
}

func GenerateToken(userID int, username string, groupID int, groupKey string, secret string) (string, error) {
	expirationTime := time.Now().Add(96 * time.Hour)

	claims := &Claims{
		UserID:   userID,
		Username: username,
		GroupID:  groupID,
		GroupKey: groupKey,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(expirationTime),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString([]byte(secret))
}

func ValidateToken(tokenString string, secret string) (*Claims, error) {
	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenString, claims, func(token *jwt.Token) (interface{}, error) {
		return []byte(secret), nil
	})

	if err != nil || !token.Valid {
		return nil, errors.New("invalid or expired token")
	}

	return claims, nil
}
